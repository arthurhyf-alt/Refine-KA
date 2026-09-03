import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pipeline import extract_observations, extract_scale_metrics, html_to_text

source = {"region": "全国", "dimension": "industrial", "source_grade": "A"}
industries = [
    {"id": "digital", "name": "数字基础设施", "keywords": ["信息传输业"]},
    {"id": "transport", "name": "交通运输", "keywords": ["航空运输业"]},
]
page = """
<html><head><title>测试页面</title></head><body>
<p>1—6月份，信息传输业投资同比增长25.6%。</p>
<p>航空运输业投资增长11.0%。</p>
</body></html>
"""
observations = extract_observations(html_to_text(page), source, industries)
values = {(o["industry_id"], o["raw_value"]) for o in observations}
assert ("digital", 25.6) in values
assert ("transport", 11.0) in values
assert all(0 <= o["score"] <= 100 for o in observations)

finance = extract_scale_metrics("半导体赛道发生611起融资事件，融资金额408.9亿元。", "finance")
assert any(value == 408.9 and unit == "亿元" for value, unit, _, _ in finance)
assert any(value == 611 and unit == "起" for value, unit, _, _ in finance)

jobs = extract_scale_metrics("人工智能工程师需供比为2.62。", "jobs")
assert any(value == 2.62 and unit == "需供比" for value, unit, _, _ in jobs)
print("pipeline extraction tests passed")
