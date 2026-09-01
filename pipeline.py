from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import pathlib
import re
import sqlite3
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
DB_PATH = DATA / "pipeline.db"
OUTPUT_PATH = DATA / "pipeline-results.json"
USER_AGENT = "IndustryScreener/0.3 (+local research tool; public evidence sources)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GRADE_CONFIDENCE = {"A": 0.95, "B": 0.78, "C": 0.58}
POSITIVE_EVENT_WORDS = ["增长", "加快", "开工", "投产", "突破", "支持", "重点项目", "完成投资", "年度计划投资", "同比增长"]
NEGATIVE_EVENT_WORDS = ["下降", "收缩", "停产", "延期", "风险", "同比下降"]


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"p", "br", "tr", "li", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag in {"p", "tr", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self):
        raw = html.unescape("".join(self.parts)).replace("\u3000", " ")
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
          status TEXT, source_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
          observation_count INTEGER DEFAULT 0, error TEXT
        );
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, source_name TEXT,
          url TEXT, region TEXT, dimension TEXT, source_grade TEXT,
          fetched_at TEXT, content_hash TEXT UNIQUE, title TEXT, text TEXT,
          http_status INTEGER
        );
        CREATE TABLE IF NOT EXISTS observations(
          id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER, industry_id TEXT,
          industry_name TEXT, region TEXT, dimension TEXT, metric_label TEXT,
          raw_value REAL, unit TEXT, score REAL, confidence REAL, evidence TEXT,
          observed_at TEXT, UNIQUE(document_id, industry_id, dimension, metric_label, raw_value)
        );
        """
    )
    conn.commit()


def decode_web_body(body, declared_encoding=None):
    """Decode Chinese government pages without trusting incorrect HTTP headers."""
    # A number of government sites declare GB2312 while serving UTF-8. UTF-8
    # strict decoding is therefore the safest first attempt.
    candidates = ["utf-8"]
    head = body[:4096].decode("ascii", errors="ignore")
    meta = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", head, re.I)
    if meta:
        candidates.append(meta.group(1))
    if declared_encoding:
        candidates.append(declared_encoding)
    candidates.extend(["gb18030", "big5"])
    seen = set()
    for encoding in candidates:
        normalized = encoding.lower().replace("gb2312", "gb18030")
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return body.decode(normalized)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def fetch(source, timeout=18):
    request = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            content_type = response.headers.get_content_charset()
            decoded = decode_web_body(body, content_type)
            return response.status, decoded
    except OSError as first_error:
        # Some Windows policies block the bundled Python runtime while allowing
        # the signed system curl client. Keep this as an automatic fallback.
        try:
            completed = subprocess.run(
                ["curl.exe", "-L", "--compressed", "--silent", "--show-error",
                 "--max-time", str(timeout), "-A", USER_AGENT, source["url"]],
                check=True, capture_output=True, timeout=timeout + 5,
                creationflags=NO_WINDOW,
            )
            body = completed.stdout
            if len(body) < 20:
                raise ValueError("curl returned an empty response")
            return 200, decode_web_body(body)
        except Exception as curl_error:
            raise OSError(f"Python下载失败: {first_error}; curl下载失败: {curl_error}") from curl_error


def source_grade_for_url(url, trusted_domains):
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    if host.endswith("gov.cn") or host.endswith("stats.gov.cn"):
        return "A"
    if any(host == domain or host.endswith("." + domain) for domain in trusted_domains):
        return "B"
    return "C"


def discovery_result_is_relevant(link, title, description, region, industry, dimension, trusted_domains):
    grade = source_grade_for_url(link, trusted_domains)
    if grade == "C":
        return False
    combined = re.sub(r"\s+", " ", f"{title} {description}")
    industry_terms = [industry["name"], *industry.get("keywords", [])]
    if not any(term and term in combined for term in industry_terms):
        return False
    if region != "全国" and region not in combined:
        return False
    signals = {
        "jobs": ["招聘", "职位", "岗位", "人才", "用工", "需供比"],
        "finance": ["融资", "投资", "预算", "基金", "项目", "专项债", "采购"],
    }
    return any(term in combined for term in signals.get(dimension, []))


def discover_sources(industries, discovery_config):
    """Discover fresh evidence pages automatically through an RSS search endpoint."""
    if not discovery_config.get("enabled"):
        return []
    endpoint = discovery_config["endpoint"]
    limit = int(discovery_config.get("max_results_per_query", 3))
    trusted = discovery_config.get("trusted_domains", [])
    found = {}
    for query_config in discovery_config.get("queries", []):
        for region in query_config.get("region_scope", ["全国"]):
            for industry in industries:
                query = query_config["template"].format(region=region, industry=industry["name"])
                url = endpoint.format(query=urllib.parse.quote(query))
                try:
                    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
                    try:
                        with urllib.request.urlopen(request, timeout=15) as response:
                            rss_body = response.read()
                    except OSError:
                        rss_body = subprocess.run(
                            ["curl.exe", "-L", "--compressed", "--silent", "--show-error",
                             "--max-time", "15", "-A", USER_AGENT, url],
                            check=True, capture_output=True, timeout=20,
                            creationflags=NO_WINDOW,
                        ).stdout
                    root = ET.fromstring(rss_body)
                    for item in root.findall(".//item")[:limit]:
                        link = (item.findtext("link") or "").strip()
                        if not link.startswith("http"):
                            continue
                        title = (item.findtext("title") or link).strip()
                        description = html.unescape(item.findtext("description") or "")
                        if not discovery_result_is_relevant(
                            link, title, description, region, industry,
                            query_config["dimension"], trusted,
                        ):
                            continue
                        key = (link, query_config["dimension"], region)
                        found[key] = {
                            "id": "discovered-" + hashlib.sha1((link + query_config["dimension"] + region).encode("utf-8")).hexdigest()[:14],
                            "name": title,
                            "url": link,
                            "region": region,
                            "dimension": query_config["dimension"],
                            "source_grade": source_grade_for_url(link, trusted),
                            "enabled": True,
                            "discovered": True,
                            "search_excerpt": re.sub(r"<[^>]+>", " ", description),
                        }
                except Exception:
                    continue
                time.sleep(0.15)
    return list(found.values())


def html_to_text(page):
    parser = TextExtractor()
    parser.feed(page)
    return parser.text()


def title_from_html(page, fallback):
    match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip() if match else fallback


def relevant_snippets(text, keywords, radius=85):
    snippets = []
    for keyword in keywords:
        start = 0
        while True:
            index = text.find(keyword, start)
            if index < 0:
                break
            snippets.append(text[max(0, index - radius): min(len(text), index + len(keyword) + radius)])
            start = index + len(keyword)
    return list(dict.fromkeys(snippets))[:20]


def dimension_text_scope(text, dimension):
    """Keep observations inside the metric's own language boundary."""
    if dimension != "export":
        return text
    paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
    export_terms = ("出口交货值", "出口额", "出口金额", "出口数量", "出口同比", "进出口")
    scoped = [p for p in paragraphs if any(term in p for term in export_terms)]
    return "\n".join(scoped)


def extract_percent(snippet):
    patterns = [
        (r"(?:同比)?增长\s*([0-9]+(?:\.[0-9]+)?)\s*%", 1),
        (r"(?:同比)?下降\s*([0-9]+(?:\.[0-9]+)?)\s*%", -1),
        (r"([+-]?\d+(?:\.\d+)?)\s*%", None),
    ]
    results = []
    for pattern, sign in patterns:
        for match in re.finditer(pattern, snippet):
            value = float(match.group(1))
            if sign is not None:
                value *= sign
            results.append((value, match.group(0)))
        if results:
            break
    return results[:3]


def yoy_to_score(value):
    return max(0, min(100, 50 + 2 * value))


def event_score(snippet):
    positive = sum(1 for word in POSITIVE_EVENT_WORDS if word in snippet)
    negative = sum(1 for word in NEGATIVE_EVENT_WORDS if word in snippet)
    if not positive and not negative:
        return None
    return max(20, min(90, 55 + positive * 6 - negative * 8))


def extract_scale_metrics(snippet, dimension):
    """Extract auditable absolute-scale signals when no YoY percentage is present."""
    patterns = []
    if dimension == "finance":
        patterns = [
            (r"([0-9]+(?:\.[0-9]+)?)\s*亿元", "亿元", 12),
            (r"([0-9]+(?:\.[0-9]+)?)\s*万元", "万元", 0.0012),
            (r"([0-9]+)\s*(?:起|笔)融资", "起", 0.8),
            (r"融资(?:事件)?(?:数)?\s*(?:为|达|共)?\s*([0-9]+)\s*(?:起|笔)", "起", 0.8),
            (r"([0-9]+)\s*个(?:重点)?项目", "个", 0.35),
        ]
    elif dimension == "jobs":
        patterns = [
            (r"([0-9]+)\s*(?:个|万个)?(?:招聘)?职位", "个", 0.08),
            (r"职位数占比\s*(?:达|为)?\s*([0-9]+(?:\.[0-9]+)?)\s*%", "%", 1.2),
            (r"需供比\s*(?:为|达)?\s*([0-9]+(?:\.[0-9]+)?)", "需供比", 10),
        ]
    results = []
    for pattern, unit, scale in patterns:
        for match in re.finditer(pattern, snippet):
            value = float(match.group(1))
            # A log transform keeps a single very large project from dominating.
            score = max(35, min(90, 45 + math.log1p(value * scale) * 8))
            results.append((value, unit, round(score, 1), match.group(0)))
    return results[:3]


def extract_observations(text, source, industries):
    observations = []
    text = dimension_text_scope(text, source["dimension"])
    base_confidence = GRADE_CONFIDENCE.get(source.get("source_grade", "C"), 0.58)
    for industry in industries:
        snippets = relevant_snippets(text, industry["keywords"])
        for snippet in snippets:
            percentages = extract_percent(snippet)
            if percentages:
                for value, label in percentages:
                    observations.append({
                        "industry_id": industry["id"], "industry_name": industry["name"],
                        "region": source["region"], "dimension": source["dimension"],
                        "metric_label": label, "raw_value": value, "unit": "%",
                        "score": yoy_to_score(value), "confidence": base_confidence,
                        "evidence": re.sub(r"\s+", " ", snippet)[:320],
                    })
            elif source["dimension"] in {"finance", "jobs"}:
                scale_metrics = extract_scale_metrics(snippet, source["dimension"])
                for value, unit, score, label in scale_metrics:
                    observations.append({
                        "industry_id": industry["id"], "industry_name": industry["name"],
                        "region": source["region"], "dimension": source["dimension"],
                        "metric_label": label, "raw_value": value, "unit": unit,
                        "score": score, "confidence": base_confidence * 0.85,
                        "evidence": re.sub(r"\s+", " ", snippet)[:320],
                    })
                if not scale_metrics:
                    score = event_score(snippet)
                    if score is not None:
                        observations.append({
                            "industry_id": industry["id"], "industry_name": industry["name"],
                            "region": source["region"], "dimension": source["dimension"],
                            "metric_label": "事件信号", "raw_value": None, "unit": "event",
                            "score": score, "confidence": base_confidence * 0.7,
                            "evidence": re.sub(r"\s+", " ", snippet)[:320],
                        })
            elif source["dimension"] in {"finance", "technology", "policy", "demand"}:
                score = event_score(snippet)
                if score is not None:
                    observations.append({
                        "industry_id": industry["id"], "industry_name": industry["name"],
                        "region": source["region"], "dimension": source["dimension"],
                        "metric_label": "事件信号", "raw_value": None, "unit": "event",
                        "score": score, "confidence": base_confidence * 0.7,
                        "evidence": re.sub(r"\s+", " ", snippet)[:320],
                    })
    return observations


def aggregate(conn):
    industries = load_json(CONFIG / "industries.json")
    industry_by_id = {industry["id"]: industry for industry in industries}
    rows = conn.execute(
        """SELECT o.industry_id, o.industry_name, o.region, o.dimension, o.score, o.confidence,
                  o.evidence, d.url, d.source_name, o.observed_at
           FROM observations o JOIN documents d ON d.id=o.document_id
           ORDER BY o.observed_at DESC"""
    ).fetchall()
    grouped = {}
    for row in rows:
        industry_id, industry_name, region, dimension, score, confidence, evidence, url, source_name, observed_at = row
        if industry_id not in industry_by_id:
            continue
        key = (industry_id, region)
        taxonomy = industry_by_id[industry_id]
        entry = grouped.setdefault(key, {"id": f"{industry_id}-{region}", "industry": industry_name, "statsCode": taxonomy.get("code"), "schneiderIndustry": taxonomy.get("schneider", "其他/待确认"), "region": region, "updatedAt": observed_at[:10], "metrics": {}})
        metric = entry["metrics"].setdefault(dimension, {"values": [], "evidenceItems": []})
        metric["values"].append((float(score), float(confidence)))
        if len(metric["evidenceItems"]) < 3:
            metric["evidenceItems"].append({"source": source_name, "url": url, "text": evidence})
    # Keep the comparison frame stable even when one province publishes no
    # local industry detail for a particular row.
    comparison_regions = ["全国", "上海", "江西", "福建", "浙江"]
    for industry in industries:
        for region in comparison_regions:
            key = (industry["id"], region)
            grouped.setdefault(key, {
                "id": f"{industry['id']}-{region}",
                "industry": industry["name"],
                "statsCode": industry.get("code"),
                "schneiderIndustry": industry.get("schneider", "其他/待确认"),
                "region": region,
                "updatedAt": datetime.now().date().isoformat(),
                "metrics": {},
            })
    output = []
    dimensions = ["export", "industrial", "jobs", "finance", "technology", "policy"]
    for entry in grouped.values():
        final_metrics = {}
        for dimension in dimensions:
            metric = entry["metrics"].get(dimension)
            if not metric:
                final_metrics[dimension] = {"score": None, "confidence": 0, "evidence": "当前采集样本尚未覆盖该指标", "evidenceItems": []}
                continue
            values = metric["values"]
            scores = [v[0] for v in values]
            weighted_confidence = min(0.98, statistics.mean(v[1] for v in values) + min(0.12, math.log1p(len(values)) * 0.03))
            final_metrics[dimension] = {
                "score": round(statistics.median(scores), 1),
                "confidence": round(weighted_confidence, 2),
                "evidence": metric["evidenceItems"][0]["text"],
                "evidenceItems": metric["evidenceItems"],
            }
        entry["metrics"] = final_metrics
        output.append(entry)

    # Local statistical releases often only publish broad totals. Where an
    # industry-specific local signal is absent, retain the national signal as
    # an explicitly labelled, lower-confidence proxy instead of silently
    # treating it as local data.
    national = {entry["id"].split("-全国")[0]: entry for entry in output if entry["region"] == "全国"}
    for entry in output:
        if entry["region"] == "全国":
            continue
        industry_id = entry["id"][:-len("-" + entry["region"])]
        benchmark = national.get(industry_id)
        if not benchmark:
            continue
        for dimension in dimensions:
            local_metric = entry["metrics"][dimension]
            proxy = benchmark["metrics"][dimension]
            if local_metric["score"] is not None or proxy["score"] is None:
                continue
            proxy_items = [{**item, "source": "全国代理｜" + item["source"]} for item in proxy["evidenceItems"]]
            entry["metrics"][dimension] = {
                "score": proxy["score"],
                "confidence": round(proxy["confidence"] * 0.65, 2),
                "evidence": "本地区暂缺行业细分，采用全国同一行业信号作代理：" + proxy["evidence"],
                "evidenceItems": proxy_items,
                "proxy": True,
            }
    curated = load_json(CONFIG / "curated_benchmarks.json")
    for entry in output:
        industry_id = entry["id"][:-len("-" + entry["region"])]
        for dimension, benchmark in curated.get(industry_id, {}).items():
            if dimension not in entry["metrics"]:
                continue
            if entry["metrics"][dimension]["score"] is not None:
                continue
            entry["metrics"][dimension] = {
                "score": benchmark["score"],
                "confidence": benchmark["confidence"] if entry["region"] == "全国" else round(benchmark["confidence"] * 0.82, 2),
                "evidence": ("本地区暂缺行业细分，采用全国细分基准：" if entry["region"] != "全国" else "") + benchmark["evidence"],
                "evidenceItems": [{"source": ("全国细分基准｜" if entry["region"] != "全国" else "") + benchmark["source"], "url": benchmark["url"], "text": benchmark["evidence"]}],
                "proxy": entry["region"] != "全国",
            }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def run_pipeline(only_source=None):
    DATA.mkdir(exist_ok=True)
    sources = [s for s in load_json(CONFIG / "sources.json") if s.get("enabled", True)]
    discovery_config = load_json(CONFIG / "discovery.json")
    if only_source:
        sources = [s for s in sources if s["id"] == only_source]
    industries = load_json(CONFIG / "industries.json")
    if not only_source:
        sources.extend(discover_sources(industries, discovery_config))
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    cursor = conn.execute("INSERT INTO runs(started_at,status,source_count) VALUES(?,?,?)", (utc_now(), "running", len(sources)))
    run_id = cursor.lastrowid
    conn.commit()
    success = 0
    observation_count = 0
    errors = []
    if sources:
        try:
            fetch(sources[0], timeout=8)
        except Exception as exc:
            message = str(exc)
            if "WinError 10013" in message or "exit status 7" in message:
                output = aggregate(conn)
                friendly_error = (
                    "当前本地运行环境禁止程序访问外网，在线采集未执行。"
                    "页面继续保留最近一次已核验结果；请更换具备联网权限的运行环境后再更新。"
                )
                conn.execute(
                    "UPDATE runs SET finished_at=?,status=?,success_count=?,observation_count=?,error=? WHERE id=?",
                    (utc_now(), "network_blocked", 0, 0, friendly_error, run_id),
                )
                conn.commit()
                conn.close()
                return {"runId": run_id, "status": "network_blocked", "sourceCount": len(sources),
                        "successCount": 0, "observationCount": 0, "industryRows": len(output),
                        "errors": [friendly_error]}
    # The preflight succeeded. Start a clean evidence snapshot so old corrupt
    # encodings and removed sources cannot contaminate the new ranking.
    conn.execute("DELETE FROM observations")
    conn.execute("DELETE FROM documents")
    conn.commit()
    for index, source in enumerate(sources):
        try:
            try:
                status, page = fetch(source)
                text = html_to_text(page)
            except Exception:
                if not source.get("discovered") or not source.get("search_excerpt"):
                    raise
                # Search results remain useful as low-confidence evidence when
                # the destination site blocks automated article retrieval.
                status = 206
                page = f"<title>{html.escape(source['name'])}</title>"
                text = source["name"] + "\n" + source["search_excerpt"]
            if len(text) < 100:
                raise ValueError("页面正文过短，可能被拦截或页面结构已变化")
            digest = hashlib.sha256((source["id"] + text).encode("utf-8")).hexdigest()
            title = title_from_html(page, source["name"])
            conn.execute(
                """INSERT OR IGNORE INTO documents(source_id,source_name,url,region,dimension,source_grade,fetched_at,content_hash,title,text,http_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (source["id"], source["name"], source["url"], source["region"], source["dimension"], source["source_grade"], utc_now(), digest, title, text, status),
            )
            document_id = conn.execute("SELECT id FROM documents WHERE content_hash=?", (digest,)).fetchone()[0]
            observations = extract_observations(text, source, industries)
            for obs in observations:
                conn.execute(
                    """INSERT OR IGNORE INTO observations(document_id,industry_id,industry_name,region,dimension,metric_label,raw_value,unit,score,confidence,evidence,observed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (document_id, obs["industry_id"], obs["industry_name"], obs["region"], obs["dimension"], obs["metric_label"], obs["raw_value"], obs["unit"], obs["score"], obs["confidence"], obs["evidence"], utc_now()),
                )
            conn.commit()
            observation_count += len(observations)
            success += 1
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
        if index < len(sources) - 1:
            time.sleep(0.7)
    output = aggregate(conn)
    status = "completed" if success else "failed"
    conn.execute(
        "UPDATE runs SET finished_at=?,status=?,success_count=?,observation_count=?,error=? WHERE id=?",
        (utc_now(), status, success, observation_count, "\n".join(errors)[:4000], run_id),
    )
    conn.commit()
    conn.close()
    return {"runId": run_id, "status": status, "sourceCount": len(sources), "successCount": success, "observationCount": observation_count, "industryRows": len(output), "errors": errors}


def latest_status():
    if not DB_PATH.exists():
        return {"status": "never_run"}
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    row = conn.execute("SELECT id,started_at,finished_at,status,source_count,success_count,observation_count,error FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return {"status": "never_run"}
    keys = ["runId", "startedAt", "finishedAt", "status", "sourceCount", "successCount", "observationCount", "error"]
    return dict(zip(keys, row))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="产业数据采集流水线")
    parser.add_argument("--source", help="只运行指定source id")
    parser.add_argument("--status", action="store_true", help="显示最近一次运行状态")
    args = parser.parse_args()
    result = latest_status() if args.status else run_pipeline(args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
