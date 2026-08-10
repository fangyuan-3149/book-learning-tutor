"""discover.py 非 LLM 逻辑的冒烟测试（不联网、不调 deepseek）。
验证：detect_format / looks_like_login_page / _extract_json / validate_source。
运行：
    python tests/test_discover_smoke.py   # 或用本仓库 venv_slim/Scripts/python.exe（相对仓库根）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "acquire"))

import discover as D  # noqa: E402


def test_detect_format():
    assert D.detect_format('{"a":1}') == "json"
    assert D.detect_format('[{"a":1}]') == "json"
    assert D.detect_format("<html>hi</html>") == "html"
    print("[OK] detect_format")


def test_looks_like_login_page():
    login = '<html><head><title>请登录</title></head><body><input type="password"></body></html>'
    assert D.looks_like_login_page(login) is True
    normal = '<html><head><title>小说搜索</title></head><body><a href="/b/1">书</a></body></html>'
    assert D.looks_like_login_page(normal) is False
    # 有 input 但非登录页 title → 不应误判
    reg = '<html><head><title>注册</title></head><body><input type="text" placeholder="用户名"></body></html>'
    assert D.looks_like_login_page(reg) is False
    print("[OK] looks_like_login_page")


def test_extract_json():
    fenced = "```json\n{\"bookSourceName\":\"x\"}\n```"
    assert D._extract_json(fenced) == {"bookSourceName": "x"}
    raw = '前情 {"a":1} 后情'
    assert D._extract_json(raw) == {"a": 1}
    assert D._extract_json("no json here") is None
    print("[OK] _extract_json")


def test_validate_source():
    html = """<html><body>
<div class="result-list">
  <div class="book"><a class="name" href="/b/1.html">书名一</a><span class="author">作者甲</span></div>
  <div class="book"><a class="name" href="/b/2.html">书名二</a><span class="author">作者乙</span></div>
</div></body></html>"""
    src = {
        "bookSourceName": "冒烟测试源",
        "bookSourceUrl": "https://example.com",
        "ruleSearch": {
            "bookList": "class.result-list@tag.div@class.book",
            "name": "class.name@text",
            "author": "class.author@text",
            "bookUrl": "class.name@href",
        },
    }
    ok, detail = D.validate_source(src, "https://example.com/s?k=x", html, "html")
    assert ok, detail
    assert "ruleSearch: OK(2 条)" in detail, detail
    print("[OK] validate_source ->", detail)


def test_validate_source_fails_on_wrong_rule():
    html = "<html><body><div class='x'>无结构</div></body></html>"
    src = {
        "bookSourceName": "坏规则源",
        "bookSourceUrl": "https://example.com",
        "ruleSearch": {
            "bookList": "class.result-list@tag.div@class.book",
            "name": "class.name@text",
        },
    }
    ok, detail = D.validate_source(src, "https://example.com", html, "html")
    assert not ok
    assert "ruleSearch: 空" in detail, detail
    print("[OK] validate_source(错误规则) 正确返回失败 ->", detail)


def test_discover_from_source():
    """agent 驱动入口：agent 写好源 + 内联样本（不联网），应回放通过并落盘（写到临时目录，不污染仓库）。"""
    import discover as D2
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    D2.DISCOVERED_DIR = tmp  # 重定向落盘到临时目录
    html = """<html><body>
<div class="result-list">
  <div class="book"><a class="name" href="/b/1.html">书名一</a><span class="author">作者甲</span></div>
  <div class="book"><a class="name" href="/b/2.html">书名二</a><span class="author">作者乙</span></div>
</div></body></html>"""
    src = {
        "bookSourceName": "agent驱动入口测试",
        "bookSourceUrl": "https://example.com",
        "ruleSearch": {
            "bookList": "class.result-list@tag.div@class.book",
            "name": "class.name@text",
            "author": "class.author@text",
            "bookUrl": "class.name@href",
        },
    }
    res = D2.discover_from_source(src, "https://example.com/s?k=x", text=html, fmt="html")
    assert "saved" in res and "validated" in res, res
    assert "ruleSearch: OK(2 条)" in res["validated"], res
    assert Path(res["saved"]).exists(), res
    print("[OK] discover_from_source(agent 驱动入口) ->", res["validated"])


if __name__ == "__main__":
    test_detect_format()
    test_looks_like_login_page()
    test_extract_json()
    test_validate_source()
    test_validate_source_fails_on_wrong_rule()
    test_discover_from_source()
    print("\n全部冒烟测试通过 ✅")
