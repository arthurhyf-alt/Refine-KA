from __future__ import annotations

import hashlib
import html
import json
import math
import pathlib
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "semantic_profiles.json"
FEEDBACK_PATH = ROOT / "data" / "semantic_feedback.json"
CURSOR_PATH = ROOT / "data" / "semantic_cursor.json"
REPORT_PATH = ROOT / "data" / "discovery-report.json"
USER_AGENT = "RefineKA/4.1 semantic discovery (+public evidence research)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def character_ngrams(text, size=2):
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())
    return {compact[i:i + size] for i in range(max(0, len(compact) - size + 1))}


def cosine_overlap(left, right):
    a, b = character_ngrams(left), character_ngrams(right)
    return len(a & b) / math.sqrt(len(a) * len(b)) if a and b else 0.0


def term_variants(term):
    clean = re.sub(r"[、，,（）()及和与]", " ", term).strip()
    values = {term, clean}
    for part in clean.split():
        values.add(part)
        reduced = re.sub(r"(?:制造业|服务业|运输业|采选业|开采业|加工业|生产供应业|产业|行业|制造|服务)$", "", part)
        if len(reduced) >= 2:
            values.add(reduced)
    return {item for item in values if len(item) >= 2}


def concept_match(text, term):
    if term in text:
        return True
    # Common metric phrases vary morphologically: 出口增长/出口增、海外订单/海外市场.
    stems = {term[:2], term[-2:]}
    return any(len(stem) == 2 and stem in text for stem in stems)


def canonical_url(url):
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not k.lower().startswith(("utm_", "spm", "from"))]
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))


def host_grade(url, trusted_domains):
    host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
    if host.endswith("gov.cn") or host.endswith("stats.gov.cn"):
        return "A"
    if any(host == item or host.endswith("." + item) for item in trusted_domains):
        return "A"
    return "B" if host else "C"


def semantic_score(title, excerpt, industry, region, dimension, profile, feedback, config):
    text = re.sub(r"<[^>]+>", " ", html.unescape(f"{title} {excerpt}"))
    industry_terms = list({variant for term in [industry.get("name", ""), *industry.get("keywords", [])] for variant in term_variants(term)})
    concepts = [*profile.get("concepts", []), *profile.get("actions", [])]
    accepted = feedback.get("accepted_terms", {}).get(dimension, [])
    rejected = feedback.get("rejected_terms", {}).get(dimension, [])
    industry_hit = max([cosine_overlap(text, term) for term in industry_terms if term] or [0])
    industry_exact = any(term and term in text for term in industry_terms)
    concept_hits = sum(1 for term in [*concepts, *accepted] if term and concept_match(text, term))
    evidence_hits = sum(1 for term in config.get("evidence_terms", []) if term in text)
    region_hit = region == "全国" or region in text
    negative_hits = sum(1 for term in [*config.get("negative_terms", []), *rejected] if term in text)
    score = (0.30 if industry_exact else min(0.24, industry_hit * 0.6))
    score += min(0.32, concept_hits * 0.08)
    score += min(0.18, evidence_hits * 0.045)
    score += 0.10 if region_hit else 0
    score += 0.08 if re.search(r"202[5-9]|最新|上半年|[1-9]月", text) else 0
    comparable_examples = [item for item in feedback.get("examples", []) if item.get("dimension") == dimension]
    for example in comparable_examples[-100:]:
        similarity = cosine_overlap(text, example.get("text", ""))
        if similarity >= 0.30:
            score += (0.10 if example.get("verdict") == "accepted" else -0.16) * similarity
    score -= min(0.40, negative_hits * 0.15)
    if not industry_exact and industry_hit < 0.20:
        score = min(score, 0.29)
    return max(0.0, min(1.0, score)), {
        "industryExact": industry_exact, "conceptHits": concept_hits,
        "evidenceHits": evidence_hits, "regionHit": region_hit,
        "negativeHits": negative_hits,
    }


def fetch_rss(query, endpoint, timeout=15):
    url = endpoint.format(query=urllib.parse.quote(query))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except OSError:
        body = subprocess.run(
            ["curl.exe", "-L", "--compressed", "--silent", "--show-error", "--max-time", str(timeout), "-A", USER_AGENT, url],
            check=True, capture_output=True, timeout=timeout + 5, creationflags=NO_WINDOW,
        ).stdout
    root = ET.fromstring(body)
    return [{
        "url": (item.findtext("link") or "").strip(),
        "title": (item.findtext("title") or "").strip(),
        "excerpt": re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or "")),
        "published": (item.findtext("pubDate") or "").strip(),
    } for item in root.findall(".//item")]


def generate_queries(industries, config):
    queries = []
    for dimension, profile in config.get("profiles", {}).items():
        for region in config.get("regions", ["全国"]):
            for industry in industries:
                for template in profile.get("query_templates", []):
                    queries.append({"dimension": dimension, "region": region, "industry": industry,
                                    "query": template.format(region=region, industry=industry["name"])})
    return queries


def select_query_batch(queries, limit):
    cursor = load_json(CURSOR_PATH, {"offset": 0})
    start = int(cursor.get("offset", 0)) % max(1, len(queries))
    batch = [queries[(start + i) % len(queries)] for i in range(min(limit, len(queries)))] if queries else []
    CURSOR_PATH.write_text(json.dumps({"offset": (start + len(batch)) % max(1, len(queries)), "updatedAt": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=2), encoding="utf-8")
    return batch


def discover(industries, endpoint="https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"):
    config = load_json(CONFIG_PATH, {})
    feedback = load_json(FEEDBACK_PATH, {})
    all_queries = generate_queries(industries, config)
    batch = select_query_batch(all_queries, int(config.get("max_queries_per_run", 72)))
    threshold = float(config.get("minimum_semantic_score", 0.38))
    result_limit = int(config.get("max_results_per_query", 5))
    candidates, errors, seen = [], [], set()
    searched = 0
    for spec in batch:
        try:
            results = fetch_rss(spec["query"], endpoint)[:result_limit]
            searched += 1
            for result in results:
                if not result["url"].startswith("http"):
                    continue
                url = canonical_url(result["url"])
                key = (url, spec["dimension"], spec["region"], spec["industry"]["id"])
                if key in seen:
                    continue
                seen.add(key)
                profile = config["profiles"][spec["dimension"]]
                score, reasons = semantic_score(result["title"], result["excerpt"], spec["industry"], spec["region"], spec["dimension"], profile, feedback, config)
                if score < threshold:
                    continue
                grade = host_grade(url, config.get("trusted_domains", []))
                candidates.append({
                    "id": "semantic-" + hashlib.sha1((url + spec["dimension"] + spec["region"] + spec["industry"]["id"]).encode("utf-8")).hexdigest()[:16],
                    "name": result["title"] or url, "url": url,
                    "region": spec["region"] if reasons["regionHit"] else "全国",
                    "dimension": spec["dimension"], "source_grade": grade, "enabled": True,
                    "discovered": True, "semantic_discovery": True, "semantic_score": round(score, 3),
                    "target_industry_id": spec["industry"]["id"], "search_query": spec["query"],
                    "search_excerpt": result["excerpt"], "published": result["published"],
                    "semantic_reasons": reasons,
                })
        except Exception as exc:
            errors.append(f"{spec['query']}: {exc}")
    candidates.sort(key=lambda item: (-item["semantic_score"], item["source_grade"], item["url"]))
    report = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"), "queryUniverse": len(all_queries),
        "queriesScheduled": len(batch), "queriesSucceeded": searched, "candidatesSeen": len(seen),
        "candidatesAccepted": len(candidates), "errors": errors[:20],
        "mode": "semantic_web_discovery", "nextOffset": load_json(CURSOR_PATH, {}).get("offset", 0),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidates, report


def record_feedback(dimension, verdict, text, url="", industry_id=""):
    if verdict not in {"accepted", "rejected"}:
        raise ValueError("verdict must be accepted or rejected")
    feedback = load_json(FEEDBACK_PATH, {"accepted_terms": {}, "rejected_terms": {}, "domain_adjustments": {}, "examples": []})
    example = {"dimension": dimension, "verdict": verdict, "text": re.sub(r"\s+", " ", text).strip()[:1000],
               "url": url, "industryId": industry_id, "createdAt": datetime.now().isoformat(timespec="seconds")}
    fingerprint = hashlib.sha1(json.dumps(example, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    example["id"] = fingerprint[:16]
    feedback.setdefault("examples", []).append(example)
    feedback["examples"] = feedback["examples"][-1000:]
    FEEDBACK_PATH.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")
    return example
