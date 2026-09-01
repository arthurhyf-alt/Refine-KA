from __future__ import annotations

"""融资/资本情况采集与评分模块（Refine-KA 企业 Top50 增强）。

数据来源：东方财富公开数据中心 / 新浪行情接口（无需密钥）。

三信号（全部公开、可溯源）：
  1. margin    —— 个股融资余额（东财 RPTA_WEB_RZRQ_GGMX），除以流通市值得到两融参与度；
  2. mainflow  —— 当日主力资金净流入（新浪 MoneyFlow r0_net），除以流通市值得到资金活跃度；
  3. block     —— 当日大宗交易（东财 RPT_DATA_BLOCKTRADE，含折价率），聚合当日成交额/折价率。

设计原则：
- 全市场数据（流通市值/主力资金/大宗）一次批量拉取；两融按个股并发查询（ThreadPoolExecutor）。
- 尽力采集：单项失败则该子项缺失，按剩余子项归一化；全部缺失则 financing 不计分（confidence=0），
  前端展示覆盖率下降，不会误导排名。
- 结果缓存到 data/financing.json，供 company_pipeline 复用，避免重复请求。
"""

import json
import math
import pathlib
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = pathlib.Path(__file__).resolve().parent
CACHE = ROOT / "data" / "financing.json"

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "close",
    "Referer": "https://data.eastmoney.com/",
}

# 沪深 A 股（主板+创业板+科创板）
CLIST_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _fetch(url, referer=None, retries=4, encoding="utf-8"):
    headers = dict(UA)
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.read().decode(encoding, "replace")
        except Exception as error:
            last_error = error
            time.sleep(1.2 * (attempt + 1) + 0.3 * attempt * attempt)
    raise RuntimeError(f"融资数据请求失败：{last_error}")


def to_float(value, default=0.0):
    """容错转换：'-' / None / 空串 / 非法文本 → default。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def fetch_quote_map():
    """全市场流通市值，新浪全 A 股接口（node=hs_a，翻页）。

    返回 {code: {"circMktcap": float(元), "mainflow": None}}
    （mainflow 由 fetch_mainflow 逐股补充；此处不依赖易受风控的东财 clist。）
    """
    result = {}
    page_no = 1
    while page_no <= 80:
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1"
            "&node=hs_a&symbol=&_s_r_a=page".format(page=page_no)
        )
        try:
            rows = json.loads(_fetch(url, encoding="gbk", referer="https://finance.sina.com.cn/stock/sl/"))
        except RuntimeError:
            break
        if not rows:
            break
        for row in rows:
            code = str(row.get("code") or "")
            if not code:
                continue
            # 新浪 mktcap/nmc 单位为万元，统一换算为元
            circ = (to_float(row.get("nmc")) or to_float(row.get("mktcap"))) * 10000
            result[code] = {"circMktcap": circ, "mainflow": None}
        if len(rows) < 100:
            break
        page_no += 1
        time.sleep(0.08)
    return result


def fetch_margin(code: str):
    """个股最新融资余额（元）。查询失败返回 None。"""
    # filter 值手工 quote 后拼接 URL，避免 urlencode 二次编码
    query = (
        "reportName=RPTA_WEB_RZRQ_GGMX&columns=ALL&pageSize=1"
        "&sortColumns=DATE&sortTypes=-1&filter=" + urllib.parse.quote(f'(SCODE="{code}")')
    )
    url = DATACENTER + "?" + query
    try:
        payload = json.loads(_fetch(url))
    except RuntimeError:
        return None
    rows = (payload.get("result") or {}).get("data") or []
    if not rows:
        return None
    value = rows[0].get("RZYE")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_mainflow(code: str):
    """个股当日主力资金净流入（元）。查询失败返回 None。"""
    prefix = "sh" if code.startswith("6") else "sz"
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"MoneyFlow.ssl_qsfx_zjlrqs?daima={prefix}{code}"
    )
    try:
        rows = json.loads(_fetch(url, encoding="gbk", referer="https://finance.sina.com.cn/money/"))
    except RuntimeError:
        return None
    if not rows:
        return None
    value = rows[0].get("r0_net")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_block_today():
    """当日全市场大宗交易聚合：{code: {"amt": 成交额元, "discount": 平均折价率%}}。

    取最新交易日（接口按 TRADE_DATE 降序），翻页聚合同一交易日的全部记录。
    """
    result = {}
    first_date = None
    for page in (1, 2, 3):
        params = {
            "reportName": "RPT_DATA_BLOCKTRADE", "columns": "ALL", "pageSize": "500",
            "pageNumber": str(page), "sortColumns": "TRADE_DATE", "sortTypes": "-1",
        }
        url = DATACENTER + "?" + urllib.parse.urlencode(params)
        try:
            payload = json.loads(_fetch(url))
        except RuntimeError:
            break
        rows = (payload.get("result") or {}).get("data") or []
        if not rows:
            break
        for row in rows:
            date = str(row.get("TRADE_DATE") or "")[:10]
            if first_date is None:
                first_date = date
            if date != first_date:
                continue
            code = str(row.get("SECURITY_CODE") or "")
            if not code:
                continue
            amt = float(row.get("DEAL_AMT") or 0)
            discount = float(row.get("DISCOUNT_RATIO") or 0)
            item = result.setdefault(code, {"amt": 0.0, "discount": 0.0, "n": 0})
            item["amt"] += amt
            item["discount"] += discount
            item["n"] += 1
        if len(rows) < 500:
            break
    for item in result.values():
        if item["n"]:
            item["discount"] = round(item["discount"] / item["n"], 2)
    return {code: {"amt": item["amt"], "discount": item["discount"]} for code, item in result.items()}


def build_financing_map(codes):
    """构建融资/资本信号表：{code: {margin, mainflow, block, blockDiscount, circMktcap}}。

    优先使用缓存；缓存缺失或过期（>6 小时）或覆盖不足时重新采集。
    """
    cached = load_cache()
    fresh = False
    if cached and cached.get("map"):
        values = list(cached["map"].values())
        good = sum(1 for value in values if value and value.get("circMktcap"))
        cache_codes = set(cached["map"].keys())
        wanted = set(codes)
        missing = len(wanted - cache_codes)
        fresh = (
            (time.time() - cached.get("fetchedAt", 0)) < 6 * 3600
            and good >= max(1, len(values) // 2)
            and missing <= max(5, len(wanted) * 0.1)   # 缓存覆盖不足 90% 时重建
        )
    if fresh:
        return cached["map"]

    quote = fetch_quote_map()
    block = fetch_block_today()

    targets = sorted({code for code in codes if code})
    margin = {}
    mainflow = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = {executor.submit(fetch_margin, code): ("margin", code) for code in targets}
        jobs.update({executor.submit(fetch_mainflow, code): ("mainflow", code) for code in targets})
        for job in as_completed(jobs):
            kind, code = jobs[job]
            try:
                value = job.result()
                if kind == "margin":
                    margin[code] = value
                else:
                    mainflow[code] = value
            except Exception:
                continue

    result = {}
    for code in targets:
        quote_item = quote.get(code, {})
        block_item = block.get(code, {})
        result[code] = {
            "margin": margin.get(code),
            "mainflow": mainflow.get(code),
            "block": block_item.get("amt"),
            "blockDiscount": block_item.get("discount"),
            "circMktcap": quote_item.get("circMktcap"),
        }
    save_cache(result)
    return result


def financing_score(signal):
    """把个股融资/资本信号折算为 0-100 分 + 置信度 + 证据。

    子项分数：
      margin   —— 融资余额占流通市值比例，0%→45，≥6%→100；
      mainflow —— 主力净流入占流通市值，1%→90，-1%→30；
      block    —— 大宗成交额占流通市值 0.5% 封顶 90，平均折价率每 1% 扣 1 分（≤10）。

    加权：margin 35% + mainflow 35% + block 30%；缺失子项按剩余权重归一化。
    """
    circ = float(signal.get("circMktcap") or 0)
    if not circ:
        return None

    parts = []
    margin = signal.get("margin")
    if margin is not None:
        m_pct = float(margin) / circ * 100
        parts.append((0.35, 45 + 55 * clamp(m_pct / 6.0, 0, 1)))

    mainflow = signal.get("mainflow")
    if mainflow is not None:
        f_pct = float(mainflow) / circ * 100
        if f_pct >= 0:
            score_flow = 50 + (f_pct / 1.0) * 40
        else:
            score_flow = 50 + (f_pct / 1.0) * 20
        parts.append((0.35, clamp(score_flow, 30, 90)))

    block = signal.get("block")
    if block is not None:
        b_pct = float(block) / circ * 100
        base = 50 + 40 * clamp(b_pct / 0.5, 0, 1)
        discount = float(signal.get("blockDiscount") or 0)
        parts.append((0.30, clamp(base - min(10, max(0, -discount) * 2), 30, 95)))

    if not parts:
        return None
    total_weight = sum(weight for weight, _ in parts)
    score = sum(weight * value for weight, value in parts) / total_weight
    covered = len(parts)
    confidence = {3: 0.75, 2: 0.68, 1: 0.58}[covered]
    return {"score": round(score, 1), "confidence": confidence, "coveredSignals": covered}


def financing_evidence(code, signal, result):
    """生成可溯源的证据文本与来源链接。"""
    items = []
    if result is None:
        return "尚未采集到该公司的融资/资本信号（两融、主力资金、大宗交易均缺失），本维度不计分。", items
    circ = signal.get("circMktcap") or 0
    if signal.get("margin") is not None and circ:
        pct = float(signal["margin"]) / circ * 100
        items.append({"source": "东方财富-个股融资融券明细", "url": f"https://data.eastmoney.com/rzrq/detail/{code}.html",
                      "text": f"最新融资余额 {signal['margin'] / 1e8:.2f} 亿元，占流通市值 {pct:.2f}%"})
    if signal.get("mainflow") is not None and circ:
        pct = float(signal["mainflow"]) / circ * 100
        items.append({"source": "新浪-主力资金流向", "url": f"https://finance.sina.com.cn/money/?symbol={code}",
                      "text": f"当日主力资金净流入 {signal['mainflow'] / 1e8:.2f} 亿元，占流通市值 {pct:.3f}%"})
    if signal.get("block") is not None and circ:
        pct = float(signal["block"]) / circ * 100
        items.append({"source": "东方财富-大宗交易", "url": f"https://data.eastmoney.com/dzjy/detail/{code}.html",
                      "text": f"最新交易日大宗交易成交 {signal['block'] / 1e8:.2f} 亿元（占流通市值 {pct:.3f}%），平均折价率 {signal.get('blockDiscount') or 0:.2f}%"})
    if not items:
        items.append({"source": "东方财富公开数据", "url": f"https://quote.eastmoney.com/{'sh' if code.startswith('6') else 'sz'}{code}.html",
                      "text": "融资/资本信号采集为空（如当日无大宗交易、未开通两融等），按中性 55 分处理"})
    return "融资/资本情况：" + "；".join(item["text"] for item in items) + "。", items


def load_cache():
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(financing_map):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(
        {"fetchedAt": time.time(), "updatedAt": time.strftime("%Y-%m-%d %H:%M"), "map": financing_map},
        ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] or ["600519", "300750", "000002"]
    result = build_financing_map(codes)
    for code in codes:
        signal = result.get(code)
        print(code, signal)
        score = financing_score(signal)
        print("  score:", score)