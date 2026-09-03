from semantic_discovery import semantic_score

industry = {"id": "battery", "name": "储能电池", "keywords": ["储能", "电池"]}
profile = {"concepts": ["扩产", "新增产线", "固定资产投资"], "actions": ["开工", "投产"]}
config = {"evidence_terms": ["亿元", "同比", "项目"], "negative_terms": ["培训", "加盟"]}
feedback = {"accepted_terms": {}, "rejected_terms": {}, "examples": []}

good, reasons = semantic_score("浙江储能电池企业新建产线", "项目计划投资20亿元，2026年开工", industry, "浙江", "finance", profile, feedback, config)
bad, _ = semantic_score("英语培训加盟课程", "面向全国招生", industry, "浙江", "finance", profile, feedback, config)
assert good >= 0.55, (good, reasons)
assert bad < 0.30, bad
print("semantic discovery tests passed")
