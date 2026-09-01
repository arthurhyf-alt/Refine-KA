from __future__ import annotations

import json
import math
import pathlib
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import financing

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "data" / "companies.json"
SECTOR_API = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
DETAIL_API = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
REGION_NODES = {"上海": "diyu_310000", "浙江": "diyu_330000", "福建": "diyu_350000", "江西": "diyu_360000"}
SUBREGIONS = {
    "上海": ["黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区", "杨浦区", "浦东新区", "闵行区", "宝山区", "嘉定区", "金山区", "松江区", "青浦区", "奉贤区", "崇明区"],
    "浙江": ["杭州市", "宁波市", "温州市", "嘉兴市", "湖州市", "绍兴市", "金华市", "衢州市", "舟山市", "台州市", "丽水市"],
    "福建": ["福州市", "厦门市", "莆田市", "三明市", "泉州市", "漳州市", "南平市", "龙岩市", "宁德市"],
    "江西": ["南昌市", "景德镇市", "萍乡市", "九江市", "新余市", "鹰潭市", "赣州市", "吉安市", "宜春市", "抚州市", "上饶市"],
}

# Publicly verifiable non-listed / growth-company seed pool.  A company may
# belong to a region because it has a headquarters, factory, R&D center,
# branch or disclosed project there; registration address is not required.
SUPPLEMENTAL_COMPANIES = [
    # Shanghai: municipal SME support, smart-factory and public financing lists.
    ("上海拜安传感技术有限公司", "上海", "浦东新区", "electronics", "专精特新/政府支持", "上海研发与经营主体", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("伊顿上飞（上海）航空管路制造有限公司", "上海", "浦东新区", "aerospace", "专精特新/政府支持", "上海航空制造项目", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("上海超导科技股份有限公司", "上海", "浦东新区", "new-energy", "专精特新/政府支持", "上海研发与生产经营", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("哲弗智能系统（上海）有限公司", "上海", "浦东新区", "automotive", "专精特新/政府支持", "上海汽车电子经营主体", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("加特兰微电子科技（上海）有限公司", "上海", "浦东新区", "electronics", "多轮融资/专精特新", "上海研发中心与经营主体", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("芯和半导体科技（上海）股份有限公司", "上海", "浦东新区", "electronics", "多轮融资/专精特新", "上海半导体研发经营", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("时擎智能科技（上海）有限公司", "上海", "浦东新区", "electronics", "多轮融资/专精特新", "上海芯片研发经营", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("上海韬润半导体有限公司", "上海", "浦东新区", "electronics", "多轮融资/专精特新", "上海半导体研发经营", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("睿励科学仪器（上海）有限公司", "上海", "浦东新区", "electronics", "战略融资/专精特新", "上海半导体设备研发生产", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("中船（上海）节能技术有限公司", "上海", "浦东新区", "shipbuilding", "专精特新/政府支持", "上海船舶节能项目经营", "https://www.sheitc.sh.gov.cn/gg/20260116/a7e93ac728a44acf914a44577bd68e9b.html"),
    ("盛帷半导体设备（上海）有限公司", "上海", "浦东新区", "electronics", "先进级智能工厂", "上海临港智能工厂", "https://www.sheitc.sh.gov.cn/gg/20251223/f82cf8042aa54a709312ceb4cfaa3736.html"),
    ("壁仞科技（上海）有限公司", "上海", "闵行区", "data-telecom-oem", "多轮融资", "上海总部与研发中心", "https://jrj.sh.gov.cn/ZXYW178/20260224/b39b0271ecca4804ad6d2a59455e4c15.html"),
    ("燧原科技有限公司", "上海", "浦东新区", "data-telecom-oem", "多轮融资", "上海研发与经营主体", "https://jrj.sh.gov.cn/ZXYW178/20260224/b39b0271ecca4804ad6d2a59455e4c15.html"),
    ("沐曦集成电路（上海）有限公司", "上海", "浦东新区", "data-telecom-oem", "多轮融资", "上海研发与经营主体", "https://jrj.sh.gov.cn/ZXYW178/20260224/b39b0271ecca4804ad6d2a59455e4c15.html"),
    ("傅利叶智能科技有限公司", "上海", "浦东新区", "oem-core", "多轮融资", "上海机器人研发与经营", "https://jrj.sh.gov.cn/ZXYW178/20260224/b39b0271ecca4804ad6d2a59455e4c15.html"),
    # Zhejiang: official specialised-SME and Eagle-company lists.
    ("杭州芯云半导体集团有限公司", "浙江", "杭州市", "electronics", "重点专精特新", "杭州研发与经营主体", "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=c3c762128f0e47dd8d5954e4808028ff.pdf"),
    ("杭州德迪智能制造有限公司", "浙江", "杭州市", "oem-core", "重点专精特新", "杭州智能制造经营主体", "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=c3c762128f0e47dd8d5954e4808028ff.pdf"),
    ("杭州集世迈新能源智能装备股份有限公司", "浙江", "杭州市", "new-energy-oem", "重点专精特新", "杭州新能源装备经营主体", "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=c3c762128f0e47dd8d5954e4808028ff.pdf"),
    ("杭州优特电源有限公司", "浙江", "杭州市", "new-energy", "重点专精特新", "杭州电源研发生产", "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=c3c762128f0e47dd8d5954e4808028ff.pdf"),
    ("杭州环特生物科技股份有限公司", "浙江", "杭州市", "life-science", "重点专精特新", "杭州生物科技经营主体", "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=c3c762128f0e47dd8d5954e4808028ff.pdf"),
    ("浙江九本环保技术有限公司", "浙江", "杭州市", "water-environment", "重点专精特新", "杭州环保技术经营主体", "https://jxt.zj.gov.cn/module/download/downfile.jsp?classid=0&filename=c3c762128f0e47dd8d5954e4808028ff.pdf"),
    ("浙江阿莱西澳智能装备科技有限公司", "浙江", "湖州市", "oem-core", "省级专精特新", "湖州智能装备经营主体", "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=278338"),
    ("浙江绿储科技有限公司", "浙江", "湖州市", "new-energy", "省级专精特新", "湖州储能经营主体", "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=278338"),
    ("浙江洛洋游艇制造有限公司", "浙江", "湖州市", "shipbuilding", "省级专精特新", "湖州游艇制造基地", "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=278338"),
    ("亚太机电集团安吉汽车管路有限公司", "浙江", "湖州市", "automotive", "省级专精特新", "湖州安吉汽车零部件生产", "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=278338"),
    ("浙江养芝康生物科技有限公司", "浙江", "湖州市", "life-science", "省级专精特新", "湖州生物科技经营主体", "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=278338"),
    # 宇树科技已于 2026-08-19 科创板上市（688836），由 A 股底池自动采集，不再放入未上市补充池
    ("杭州云深处科技有限公司", "浙江", "杭州市", "oem-core", "多轮融资", "杭州机器人总部与研发", "https://zj87.jxt.zj.gov.cn/zlzq/web/views/article/news/detail.html?id=292352"),
    ("浙江强脑科技有限公司", "浙江", "杭州市", "life-science", "多轮融资/小巨人", "杭州脑机接口研发经营", "https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web1585/site/attach/0/08a8e17d155f4f66bac8c23575459453.pdf"),
    # Fujian: official specialised-SME equity-financing reward list and SME lists.
    ("福州瑞克布朗医药科技有限公司", "福建", "福州市", "life-science", "股权融资奖励企业", "福州医药研发经营", "https://gxt.fujian.gov.cn/zwgk/gsgg/202605/t20260525_7151783.htm"),
    ("福建奥通迈胜电力科技有限公司", "福建", "福州市", "psb", "省级专精特新", "福州电力科技经营主体", "https://gxt.fujian.gov.cn/zwgk/zfxxgk/fdzdgknr/gzdt/202505/t20250527_6918636.htm"),
    ("福州力达威机电设备有限公司", "福建", "福州市", "oem-core", "省级专精特新", "福州机电设备经营主体", "https://gxt.fujian.gov.cn/zwgk/zfxxgk/fdzdgknr/gzdt/202505/t20250527_6918636.htm"),
    ("福建巨联环境科技股份有限公司", "福建", "福州市", "water-environment", "省级专精特新", "福州环保经营主体", "https://gxt.fujian.gov.cn/zwgk/zfxxgk/fdzdgknr/gzdt/202505/t20250527_6918636.htm"),
    ("福建国锐中科光电有限公司", "福建", "福州市", "electronics", "省级专精特新", "福州光电研发生产", "https://gxt.fujian.gov.cn/zwgk/zfxxgk/fdzdgknr/gzdt/202505/t20250527_6918636.htm"),
    ("福州斯耐特液压有限公司", "福建", "福州市", "oem-core", "省级专精特新", "福州液压设备经营主体", "https://gxt.fujian.gov.cn/zwgk/zfxxgk/fdzdgknr/gzdt/202505/t20250527_6918636.htm"),
    ("厦门海辰储能科技股份有限公司", "福建", "厦门市", "new-energy", "多轮融资", "厦门储能研发与生产基地", "https://gxt.fujian.gov.cn/zwgk/gsgg/202605/t20260525_7151783.htm"),
    # Jiangxi: public provincial and city specialised-SME lists.
    ("江西德瑞光电技术有限责任公司", "江西", "南昌市", "electronics", "省级专精特新", "南昌光电经营主体", "https://www.cnpp.cn/focus/3530763.html"),
    ("江西安达电子有限公司", "江西", "南昌市", "electronics", "省级专精特新", "南昌电子制造经营主体", "https://www.cnpp.cn/focus/3530763.html"),
    ("江西丹巴赫机器人股份有限公司", "江西", "南昌市", "oem-core", "省级专精特新", "南昌机器人研发经营", "https://www.cnpp.cn/focus/3530763.html"),
    ("江西国翔电力设备有限公司", "江西", "南昌市", "psb", "省级专精特新", "南昌电力设备生产经营", "https://www.cnpp.cn/focus/3530763.html"),
    ("江西乾照光电有限公司", "江西", "南昌市", "electronics", "省级专精特新", "南昌光电生产经营", "https://www.cnpp.cn/focus/3530763.html"),
    ("江西惜能照明有限公司", "江西", "南昌市", "smart-lighting", "省级专精特新", "南昌照明生产经营", "https://www.cnpp.cn/focus/3530763.html"),
    ("赣州市南康区桦展家具实业有限公司", "江西", "赣州市", "residential", "省级专精特新", "赣州南康家具生产", "https://www.nkjx.gov.cn/nkqrmzf/c125560/202509/59b48257bf764d2aa83cfb38c6152125.shtml"),
    ("江西金的德塑料制品有限公司", "江西", "赣州市", "chemical", "省级专精特新", "赣州南康材料生产", "https://www.nkjx.gov.cn/nkqrmzf/c125560/202509/59b48257bf764d2aa83cfb38c6152125.shtml"),
]

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
    code_regions = {}
    for region, node in REGION_NODES.items():
        detail = fetch_json(DETAIL_API, {"page": 1, "num": 1000, "sort": "symbol", "asc": 1, "node": node, "symbol": "", "_s_r_a": "page"}, encoding="gbk")
        for item in detail:
            code_regions[str(item.get("code") or "")] = region
        time.sleep(0.15)
    for row in rows:
        row["region"] = code_regions.get(str(row.get("f12") or ""), "其他")
        row["subregion"] = infer_subregion(row["region"], str(row.get("f14") or ""))
    target_codes = sorted({str(row.get("f12") or "") for row in rows if str(row.get("f12") or "").startswith("6") and row.get("region") in REGION_NODES})
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = {executor.submit(fetch_sse_address, code): code for code in target_codes}
        addresses = {}
        for job in as_completed(jobs):
            try:
                addresses[jobs[job]] = job.result()
            except Exception:
                continue
    for row in rows:
        code = str(row.get("f12") or "")
        if addresses.get(code):
            row["registeredAddress"] = addresses[code]
            row["subregion"] = infer_subregion(row["region"], addresses[code]) or row.get("subregion", "")
    return rows


def infer_subregion(region: str, text: str):
    for item in SUBREGIONS.get(region, []):
        stem = item.removesuffix("市").removesuffix("区")
        if item in text or stem in text:
            return item
    return ""


def fetch_sse_address(code: str):
    params = {"isPagination": "false", "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GPGK_GSGK_C", "COMPANY_CODE": code}
    request = urllib.request.Request(
        "https://query.sse.com.cn/commonQuery.do?" + urllib.parse.urlencode(params),
        headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=20) as response:
        result = json.loads(response.read()).get("result") or []
    return str((result[0] if result else {}).get("REG_ADDRESS") or "")


def matches(label: str, keywords):
    return any(keyword in label or label in keyword for keyword in keywords if label)


def quote_url(code: str):
    prefix = "sh" if code.startswith("6") else "sz"
    return f"https://quote.eastmoney.com/{prefix}{code}.html"


def mktcap_rank_score(rank: int, pool_size: int = 50):
    """市值排名分：保持原有对数衰减公式，区间 55-96。"""
    return round(max(55, 96 - 41 * math.log1p(rank - 1) / math.log(pool_size)), 1)


def stage_financing_score(stage: str):
    """非上市/成长型补充池：按公开披露的阶段信息映射融资/资本分（0-100）。"""
    stage = stage or ""
    rules = [
        (("多轮融资",), 88), (("战略融资",), 84), (("股权融资",), 82),
        (("小巨人",), 80), (("重点专精特新",), 78), (("专精特新",), 74),
        (("政府支持",), 70),
    ]
    score = 68
    for keywords, value in rules:
        if any(keyword in stage for keyword in keywords):
            score = max(score, value)
    return score


def build_companies(universe):
    # 一次性采集全候选池的融资/资本信号（两融、主力资金、大宗交易），带缓存
    codes = sorted({str(row.get("f12") or "") for row in universe if row.get("f12")})
    financing_map = financing.build_financing_map(codes)

    output = []
    for ns_id, keywords in NS_KEYWORDS.items():
        base = [row for row in universe if matches(str(row.get("f100") or ""), keywords)]
        for region in ("全国", "上海", "浙江", "福建", "江西"):
            # 地区硬过滤
            regional = base if region == "全国" else [row for row in base if row.get("region") == region]
            unique = {}
            for row in regional:
                code = str(row.get("f12") or "")
                if code not in unique or float(row.get("f20") or 0) > float(unique[code].get("f20") or 0):
                    unique[code] = row
            candidates = sorted(unique.values(), key=lambda row: float(row.get("f20") or 0), reverse=True)

            # 候选池兜底：不足 50 家时，从全国候选按按市值递补，确保 Top50 视图始终有 50 行
            overflowed = 0
            if len(candidates) < 50 and region != "全国":
                seen = {str(r.get("f12") or "") for r in candidates}
                overflow_pool = {}
                for row in base:
                    code = str(row.get("f12") or "")
                    if code in seen:
                        continue
                    if code not in overflow_pool or float(row.get("f20") or 0) > float(overflow_pool[code].get("f20") or 0):
                        overflow_pool[code] = row
                overflow = sorted(overflow_pool.values(), key=lambda row: float(row.get("f20") or 0), reverse=True)
                need = 50 - len(candidates)
                candidates = candidates + overflow[:need]
                overflowed = min(len(overflow), need)

            # 综合得分 = 市值排名分 × 0.65 + 融资/资本分 × 0.35（融资信号缺失按中性 55 计）
            composite_rows = []
            for old_rank, row in enumerate(candidates, start=1):
                code = str(row["f12"])
                market_score = mktcap_rank_score(old_rank, max(50, len(candidates)))
                signal = financing_map.get(code)
                fin = financing.financing_score(signal) if signal else None
                fin_score = fin["score"] if fin else 55.0
                composite = round(0.65 * market_score + 0.35 * fin_score, 1)
                composite_rows.append((composite, row, old_rank, market_score, fin, signal, code))
            composite_rows.sort(key=lambda item: item[0], reverse=True)

            for rank, (composite, row, old_rank, market_score, fin, signal, code) in enumerate(composite_rows[:50], start=1):
                overflow_tag = "（含跨地区补足）" if (region != "全国" and old_rank > len(regional)) else ""
                evidence = f"公开A股地区：{row.get('region') or '待确认'}；行业分类：{row.get('f100') or '待确认'}；在{region}候选池按市值×融资/资本综合排序第{rank}（综合分 {composite}）{overflow_tag}。"
                metrics = {key: {"score": None, "confidence": 0, "evidence": "尚未采集公司级证据", "evidenceItems": []}
                           for key in ("budget", "expansion", "technology", "product", "market", "talent", "policy", "financing")}
                metrics["market"] = {
                    "score": market_score, "confidence": 0.82, "evidence": evidence,
                    "evidenceItems": [{"source": "公开A股地区、行业与市值数据", "url": quote_url(code), "text": evidence}],
                }
                if fin:
                    fin_evidence, fin_items = financing.financing_evidence(code, signal, fin)
                    metrics["financing"] = {
                        "score": fin["score"], "confidence": fin["confidence"],
                        "evidence": fin_evidence, "evidenceItems": fin_items,
                    }
                else:
                    metrics["financing"] = {
                        "score": None, "confidence": 0,
                        "evidence": "融资/资本信号未采集（两融、主力资金、大宗交易均不可用），本维度不计分。", "evidenceItems": [],
                    }
                output.append({
                    "id": f"company-{ns_id}-{region}-{code}", "industry": row["f14"], "companyName": row["f14"],
                    "companyCode": code, "nsIndustryId": ns_id, "region": region,
                    "registeredRegion": row.get("region") or "其他", "subregion": row.get("subregion") or "",
                    "registeredAddress": row.get("registeredAddress") or "", "updatedAt": time.strftime("%Y-%m-%d"),
                    "sourceUrl": quote_url(code), "marketSector": row.get("f100") or "", "metrics": metrics,
                    "financingScore": fin["score"] if fin else None,
                })
    output.extend(build_supplemental_companies())
    return output


def build_supplemental_companies():
    output = []
    for index, (name, region, subregion, ns_id, stage, basis, url) in enumerate(SUPPLEMENTAL_COMPANIES, start=1):
        evidence = f"企业阶段：{stage}；地区归属依据：{basis}。企业按实际经营地计入，不以注册地址作为唯一条件。"
        metrics = {key: {"score": None, "confidence": 0, "evidence": "尚未采集公司级证据", "evidenceItems": []}
                   for key in ("budget", "expansion", "technology", "product", "market", "talent", "policy", "financing")}
        metrics["expansion"] = {"score": 78, "confidence": 0.76, "evidence": evidence,
                                "evidenceItems": [{"source": stage, "url": url, "text": evidence}]}
        metrics["policy"] = {"score": 76, "confidence": 0.84, "evidence": evidence,
                             "evidenceItems": [{"source": "政府企业名单/政府转载名单", "url": url, "text": evidence}]}

        # 融资/资本分：优先使用公开核实的结构化轮次数据（A/B/C/D轮、金额、投资方），无则按阶段标签降级
        rounds_info = financing.UNLISTED_FINANCING_ROUNDS.get(name)
        structured = financing.unlisted_financing_score(rounds_info)
        if structured:
            fin_evidence, fin_items = financing.unlisted_financing_evidence(name, rounds_info)
            metrics["financing"] = {
                "score": structured["score"], "confidence": structured["confidence"],
                "evidence": fin_evidence, "evidenceItems": fin_items,
            }
            listing_status = rounds_info.get("status", "未限定")
        else:
            fin_stage_score = stage_financing_score(stage)
            fin_evidence, _ = financing.unlisted_financing_evidence(name, None)
            metrics["financing"] = {
                "score": fin_stage_score, "confidence": 0.72,
                "evidence": f"{fin_evidence}当前阶段标签为「{stage}」，折算融资活跃度 {fin_stage_score} 分。",
                "evidenceItems": [{"source": stage, "url": url, "text": f"公开披露的企业阶段：{stage}（来源：{basis}）"}],
            }
            listing_status = "未限定"

        record = {
            "id": f"growth-{ns_id}-{region}-{index}", "industry": name, "companyName": name,
            "companyCode": "", "nsIndustryId": ns_id, "region": region,
            "registeredRegion": "不作为地区筛选条件", "subregion": subregion,
            "operatingRegions": [region], "operatingSubregions": [subregion],
            "operatingBasis": basis, "companyStage": stage, "listingStatus": listing_status,
            "registeredAddress": "", "updatedAt": time.strftime("%Y-%m-%d"),
            "sourceUrl": url, "marketSector": f"{stage}｜{basis}", "metrics": metrics,
            "financingScore": metrics["financing"]["score"],
        }
        output.append(record)
        output.append({**record, "id": f"growth-{ns_id}-全国-{index}", "region": "全国"})
    return output


def run_company_pipeline():
    companies = build_companies(fetch_universe())
    OUT.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"companyCount": len(companies), "coveredIndustries": len({row["nsIndustryId"] for row in companies})}


if __name__ == "__main__":
    print(json.dumps(run_company_pipeline(), ensure_ascii=False))
