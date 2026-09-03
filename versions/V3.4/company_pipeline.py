from __future__ import annotations

import json
import math
import pathlib
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def build_companies(universe):
    output = []
    for ns_id, keywords in NS_KEYWORDS.items():
        base = [row for row in universe if matches(str(row.get("f100") or ""), keywords)]
        for region in ("全国", "上海", "浙江", "福建", "江西"):
            candidates = base if region == "全国" else [row for row in base if row.get("region") == region]
            unique = {}
            for row in candidates:
                code = str(row.get("f12") or "")
                if code not in unique or float(row.get("f20") or 0) > float(unique[code].get("f20") or 0):
                    unique[code] = row
            candidates = sorted(unique.values(), key=lambda row: float(row.get("f20") or 0), reverse=True)
            for rank, row in enumerate(candidates[:50], start=1):
                code = str(row["f12"])
                score = round(max(55, 96 - 41 * math.log1p(rank - 1) / math.log(50)), 1)
                evidence = f"公开A股地区：{row.get('region') or '待确认'}；行业分类：{row.get('f100') or '待确认'}；在{region}候选池按公开总市值排序第{rank}。"
                metrics = {key: {"score": None, "confidence": 0, "evidence": "尚未采集公司级证据", "evidenceItems": []}
                           for key in ("budget", "expansion", "technology", "product", "market", "talent", "policy")}
                metrics["market"] = {
                    "score": score, "confidence": 0.82, "evidence": evidence,
                    "evidenceItems": [{"source": "公开A股地区、行业与市值数据", "url": quote_url(code), "text": evidence}],
                }
                output.append({
                    "id": f"company-{ns_id}-{region}-{code}", "industry": row["f14"], "companyName": row["f14"],
                    "companyCode": code, "nsIndustryId": ns_id, "region": region,
                    "registeredRegion": row.get("region") or "其他", "subregion": row.get("subregion") or "",
                    "registeredAddress": row.get("registeredAddress") or "", "updatedAt": time.strftime("%Y-%m-%d"),
                    "sourceUrl": quote_url(code), "marketSector": row.get("f100") or "", "metrics": metrics,
                })
    return output


def run_company_pipeline():
    companies = build_companies(fetch_universe())
    OUT.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"companyCount": len(companies), "coveredIndustries": len({row["nsIndustryId"] for row in companies})}


if __name__ == "__main__":
    print(json.dumps(run_company_pipeline(), ensure_ascii=False))
