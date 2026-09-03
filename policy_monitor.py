from __future__ import annotations

import hashlib
import html
import json
import pathlib
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "policy_sections.json"
STATE_PATH = ROOT / "data" / "policy_section_state.json"
REPORT_PATH = ROOT / "data" / "policy-monitor-report.json"
USER_AGENT = "RefineKA/4.2 policy section monitor (+public government sources)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href", "")
            self.current = {"href": href, "parts": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["parts"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            text = re.sub(r"\s+", " ", html.unescape("".join(self.current["parts"]))).strip()
            self.links.append({"href": self.current["href"], "text": text})
            self.current = None


def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def fetch_page(url, timeout=18):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except OSError:
        body = subprocess.run(
            ["curl.exe", "-L", "--compressed", "--silent", "--show-error", "--max-time", str(timeout), "-A", USER_AGENT, url],
            check=True, capture_output=True, timeout=timeout + 5, creationflags=NO_WINDOW,
        ).stdout
    for encoding in ("utf-8", "gb18030"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def normalize_url(base, href):
    if not href or href.startswith(("javascript:", "mailto:", "#")):
        return ""
    url = urllib.parse.urljoin(base, href)
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))


def is_policy_link(text, url, includes, excludes):
    combined = f"{text} {urllib.parse.unquote(url)}"
    if any(term in combined for term in excludes):
        return False
    return any(term in combined for term in includes)


def scan_sections():
    config = load_json(CONFIG_PATH, {})
    if not config.get("enabled", True):
        return [], {"status": "disabled"}
    state = load_json(STATE_PATH, {"sections": {}})
    sources, errors, discovered = [], [], 0
    limit = int(config.get("max_links_per_section", 30))
    for section in config.get("sections", []):
        try:
            page = fetch_page(section["url"])
            parser = LinkCollector()
            parser.feed(page)
            current = []
            seen_urls = set()
            for link in parser.links:
                url = normalize_url(section["url"], link["href"])
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if not is_policy_link(link["text"], url, config.get("include_terms", []), config.get("exclude_terms", [])):
                    continue
                current.append({"url": url, "title": link["text"] or url})
                if len(current) >= limit:
                    break
            previous = set(state.get("sections", {}).get(section["id"], {}).get("urls", []))
            new_items = [item for item in current if item["url"] not in previous]
            for item in new_items:
                discovered += 1
                sources.append({
                    "id": "section-" + hashlib.sha1((section["id"] + item["url"]).encode("utf-8")).hexdigest()[:16],
                    "name": item["title"], "url": item["url"], "region": section["region"],
                    "dimension": "policy", "source_grade": "A", "enabled": True,
                    "discovered": True, "section_discovery": True,
                    "section_id": section["id"], "section_name": section["name"],
                    "search_excerpt": item["title"],
                })
            state.setdefault("sections", {})[section["id"]] = {
                "name": section["name"], "url": section["url"],
                "urls": [item["url"] for item in current],
                "checkedAt": datetime.now().isoformat(timespec="seconds"),
                "listed": len(current), "new": len(new_items),
            }
        except Exception as exc:
            errors.append(f"{section['name']}: {exc}")
    state["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"updatedAt": state["updatedAt"], "sectionsConfigured": len(config.get("sections", [])),
              "sectionsSucceeded": len(config.get("sections", [])) - len(errors), "newPolicyLinks": discovered,
              "errors": errors[:20], "mode": "government_section_monitor"}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return sources, report

