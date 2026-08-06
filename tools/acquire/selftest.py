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

    print("\n✅ 三步管道端到端通过（本地 fixtures，确定性）。引擎逻辑正确，可指向任意可达书源。")


if __name__ == "__main__":
    main()
