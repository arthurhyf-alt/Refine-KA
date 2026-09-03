from __future__ import annotations

import json
import math
import pathlib
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "data" / "companies.json"
SECTOR_API = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
DETAIL_API = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

# Public market-sector labels are mapped to Schneider NS industries. One
# company may enter several project/OEM views when its products serve both.
NS_KEYWORDS = {
    "commercial-buildings": ["房地产", "建筑建材", "开发区"],
    "public-buildings": ["建筑建材", "机械", "仪器仪表"],
    "residential": ["房地产", "家具", "家电"],
    "psb": ["电器", "发电设备", "仪器仪表"],
    "oem-core": ["机械", "仪器仪表", "电器"],
    "metro": ["交通运输", "机械", "建筑建材"],
    "hospital": ["医疗器械", "生物制药"],
    "data-telecom": ["电子信息", "电子器件", "仪器仪表"],
    "data-telecom-project": ["电子信息", "电子器件", "仪器仪表"],
    "data-telecom-oem": ["电子信息", "电子器件", "电器"],
    "electronics": ["电子信息", "电子器件", "仪器仪表"],
    "aerospace": ["飞机制造"],
    "aerospace-project": ["飞机制造"],
    "low-altitude-oem": ["飞机制造"],
    "water-environment": ["环保", "供水供气"],
    "chemical": ["化工", "化纤", "农药化肥"],
    "oil-gas": ["石油", "供水供气"],
    "new-energy": ["发电设备", "电器", "有色金属"],
    "new-energy-project": ["发电设备", "电力", "电器"],
    "new-energy-oem": ["发电设备", "电器", "机械"],
    "railway": ["交通运输", "机械", "建筑建材"],
    "mining-materials": ["有色金属", "煤炭", "水泥", "玻璃", "建筑建材"],
    "metallurgy": ["钢铁", "有色金属", "机械"],
    "life-science": ["生物制药", "医疗器械"],
    "roads-bridges": ["公路桥梁", "建筑建材", "水泥", "机械"],
    "shipbuilding": ["船舶制造"],
    "shipbuilding-project": ["船舶制造"],
    "shipbuilding-oem": ["船舶制造"],
    "automotive": ["汽车制造", "摩托车"],
    "food-beverage": ["食品", "酿酒", "农林牧渔"],
    "smart-lighting": ["电子器件", "电器", "家电"],
    "port": ["交通运输", "公路桥梁"],
    "nuclear": ["电力", "发电设备", "机械"],
    "thermal-power": ["电力", "煤炭", "发电设备", "环保"],
    "hydropower": ["电力", "供水供气", "发电设备"],
    "paper": ["造纸", "印刷包装"],
    "other": ["综合", "其它", "物资外贸", "商业百货"],
}


def fetch_json(url, params=None, encoding="utf-8"):
    params = params or {}
    request = urllib.request.Request(
        url + ("?" + urllib.parse.urlencode(params) if params else ""),
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/stock/sl/"},
    )
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                text = response.read().decode(encoding, "replace")
                object_pos, array_pos = text.find("{"), text.find("[")
                starts = [pos for pos in (object_pos, array_pos) if pos >= 0]
                start = min(starts)
                end = text.rfind("}") + 1 if start == object_pos else text.rfind("]") + 1
                return json.loads(text[start:end])
        except Exception as error:
            last_error = error
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"企业底池下载失败：{last_error}")


def fetch_universe():
    sectors = fetch_json(SECTOR_API, encoding="gbk")
    wanted = {name for keywords in NS_KEYWORDS.values() for name in keywords}
    rows = []
    for node, value in sectors.items():
        sector_name = value.split(",")[1]
        if not any(keyword in sector_name or sector_name in keyword for keyword in wanted):
            continue
        detail = fetch_json(DETAIL_API, {"page": 1, "num": 1000, "sort": "mktcap", "asc": 0, "node": node, "symbol": "", "_s_r_a": "page"}, encoding="gbk")
        for item in detail:
            item["f12"], item["f14"], item["f20"], item["f100"] = item.get("code"), item.get("name"), item.get("mktcap"), sector_name
            rows.append(item)
        time.sleep(0.15)
    return rows


def matches(label: str, keywords):
    return any(keyword in label or label in keyword for keyword in keywords if label)


def quote_url(code: str):
    prefix = "sh" if code.startswith("6") else "sz"
    return f"https://quote.eastmoney.com/{prefix}{code}.html"


def build_companies(universe):
    output = []
    for ns_id, keywords in NS_KEYWORDS.items():
        candidates = [row for row in universe if matches(str(row.get("f100") or ""), keywords)]
        candidates.sort(key=lambda row: float(row.get("f20") or 0), reverse=True)
        for rank, row in enumerate(candidates[:50], start=1):
            code = str(row["f12"])
            market_cap = float(row.get("f20") or 0)
            score = round(max(55, 96 - 41 * math.log1p(rank - 1) / math.log(50)), 1)
            evidence = f"公开A股行业分类：{row.get('f100') or '待确认'}；按公开总市值形成候选池，行业内排序第{rank}。"
            metrics = {key: {"score": None, "confidence": 0, "evidence": "尚未采集公司级证据", "evidenceItems": []}
                       for key in ("budget", "expansion", "technology", "product", "market", "talent", "policy")}
            metrics["market"] = {
                "score": score, "confidence": 0.78, "evidence": evidence,
                "evidenceItems": [{"source": "公开A股行业与市值数据", "url": quote_url(code), "text": evidence}],
            }
            output.append({
                "id": f"company-{ns_id}-{code}", "industry": row["f14"], "companyName": row["f14"],
                "companyCode": code, "nsIndustryId": ns_id, "region": "全国",
                "updatedAt": time.strftime("%Y-%m-%d"), "sourceUrl": quote_url(code),
                "marketSector": row.get("f100") or "", "metrics": metrics,
            })
    return output


def run_company_pipeline():
    companies = build_companies(fetch_universe())
    OUT.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"companyCount": len(companies), "coveredIndustries": len({row["nsIndustryId"] for row in companies})}


if __name__ == "__main__":
    print(json.dumps(run_company_pipeline(), ensure_ascii=False))
