"""确定性自测：用本地 fixtures 跑通 搜→下→md 三步，证明引擎+管道逻辑正确。

不依赖任何外部站点（外部书源普遍 403/404/空/规则过期，属源站问题）。
运行：
    python selftest.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from source_engine import SourceEngine, load_sources
from pipeline import REF_DIR, PREP_DIR, convert
from fetcher import Fetcher

FIX = ROOT / "tests" / "fixtures"


class LocalFetcher(Fetcher):
    """把 URL 映射到本地 fixture 文件，不发真实网络请求。"""
    def __init__(self):
        self.timeout = 20
        self.proxy = None
        self.delay = 0
        self.session = None
        self.last_post = None   # 记录最近一次 POST，供 B-01 断言

    def parse_header(self, s):
        return {}

    def get(self, url, headers=None):
        u = url
        if "search" in u:
            return (FIX / "search.html").read_text(encoding="utf-8")
        if u.rstrip("/").endswith("/book/1"):
            return (FIX / "book_1.html").read_text(encoding="utf-8")
        if u.rstrip("/").endswith("ch1"):
            return (FIX / "chapter_1.html").read_text(encoding="utf-8")
        if u.rstrip("/").endswith("ch2"):
            return (FIX / "chapter_2.html").read_text(encoding="utf-8")
        raise FileNotFoundError(f"未映射的本地 URL: {u}")

    def post(self, url, headers=None, data=None, json_body=None):
        self.last_post = {"url": url, "headers": dict(headers or {}), "data": data}
        if "/api/search" in url:
            return (FIX / "search_post.json").read_text(encoding="utf-8")
        raise FileNotFoundError(f"未映射的本地 POST: {url}")


def check_jsonpath():
    """B-26 回归：JSONPath 常用子集（通配/切片/并集/递归下降）。"""
    from rules import json_query, eval_json, jsonpath_single
    d = {"code": 0,
         "data": [{"id": 1, "title": "A", "sub": {"x": "p"}},
                  {"id": 2, "title": "B", "sub": {"x": "q"}}],
         "meta": {"data": [{"id": 9}]}}
    cases = [
        ("$.data[*]", 2), ("$.data[0]", 1), ("$.data[-1]", 1),
        ("$.data[*].title", 2), ("$.data[0:1]", 1), ("$.data[0,1]", 2),
        ("$..id", 3), ("$.data[*].sub.x", 2), ("$.code", 1), ("$.nope", 0),
        ("$['data'][*]", 2), ("$.data[*]['id','title']", 4),
    ]
    for path, exp in cases:
        got = len(json_query(d, path))
        assert got == exp, f"JSONPath {path}: 期望 {exp} 项，实得 {got}"
    assert eval_json(d, "$.data") and len(eval_json(d, "$.data")) == 2, "指向数组时应迭代该数组"
    assert json_query(d, "$..id") == [1, 2, 9]
    assert jsonpath_single(d["data"][0], "id") == "1"
    assert jsonpath_single(d, "nope.deep") == ""      # 不存在 → 空串，不抛
    assert json_query("not json at all", "$.a") == []  # 非法 JSON → 空，不抛
    print(f"[B-26] JSONPath OK：{len(cases)} 种语法（通配/负索引/切片/并集/递归下降/引号键）")


def check_post_source():
    """B-01 回归：POST 搜索源走统一 UrlOption，四大动作共用同一套解析。"""
    src = load_sources(str(FIX / "source_post.json"))[0]
    f = LocalFetcher()
    eng = SourceEngine(src, f)

    books = eng.search("测试", page=1)
    assert len(books) == 2, books
    assert books[0]["name"] == "测试书" and books[0]["author"] == "测试作者", books[0]
    assert books[0]["bookUrl"] == "http://local.test/book/1", books[0]["bookUrl"]

    p = f.last_post
    assert p and p["url"] == "http://local.test/api/search", p
    assert p["data"] == "kw=%E6%B5%8B%E8%AF%95&page=1".encode("utf-8"), p["data"]
    assert p["headers"].get("X-Test") == "1", p["headers"]
    assert p["headers"].get("Content-Type", "").startswith("application/x-www-form"), p["headers"]

    # POST 源同样能顺链走完详情/目录/正文（复用同一 _request）
    info = eng.get_book_info(books[0]["bookUrl"])
    assert info.get("name") == "测试书", info
    toc = eng.get_toc(books[0]["bookUrl"])
    assert len(toc) == 2, toc
    body = eng.get_content(toc[0]["chapterUrl"])
    assert "第一章" in body or "第一段" in body, body[:80]
    print(f"[B-01] POST 源 OK：body/charset/headers/JSONPath/URL模板 全部生效，"
          f"详情+目录({len(toc)}章)+正文 复用同一请求入口")


def main():
    src = load_sources(str(FIX / "source.json"))[0]
    eng = SourceEngine(src, LocalFetcher())

    # Step 1 搜索
    books = eng.search("测试")
    assert len(books) == 2, books
    assert books[0]["name"] == "测试书", books[0]
    assert books[0]["bookUrl"] == "http://local.test/book/1", books[0]["bookUrl"]
    assert books[0]["author"] == "测试作者"
    print(f"[Step1] 搜索 OK：{[b['name'] for b in books]}")

    # Step 2 下载原书 → 参考/
    info = eng.download_book(books[0]["bookUrl"], "测试书")
    chapters = list((REF_DIR / "测试书").glob("*.txt"))
    assert len(chapters) == 2, chapters
    print(f"[Step2] 下载 OK：参考/测试书/ 共 {len(chapters)} 章")

    # Step 3 转 markdown → 预处理/
    out, n = convert("测试书")
    md = Path(out).read_text(encoding="utf-8")
    assert "第一章" in md and "第二章" in md, md[:200]
    assert "（本章完）" not in md, "净化失败：残留（本章完）"
    print(f"[Step3] 转md OK：预处理/测试书.md（{n} 节，已净化）")

    check_jsonpath()
    check_post_source()

    print("\n✅ 三步管道端到端通过（本地 fixtures，确定性）。引擎逻辑正确，可指向任意可达书源。")


if __name__ == "__main__":
    main()
