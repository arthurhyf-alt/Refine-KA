from policy_monitor import LinkCollector, is_policy_link, normalize_url

parser = LinkCollector()
parser.feed('<a href="../policy/a.html">关于公布智能工厂名单的通知</a><a href="b.html">领导讲话</a>')
assert parser.links[0]["text"] == "关于公布智能工厂名单的通知"
assert normalize_url("https://example.gov.cn/col/index.html", parser.links[0]["href"]) == "https://example.gov.cn/policy/a.html"
assert is_policy_link(parser.links[0]["text"], parser.links[0]["href"], ["名单", "政策"], ["领导讲话"])
assert not is_policy_link(parser.links[1]["text"], parser.links[1]["href"], ["名单", "政策"], ["领导讲话"])
print("policy monitor tests passed")
