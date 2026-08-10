"""书源分步调试器：跑一次动作，打印规则执行追踪树，直接指出断链点。

对应 Legado_Max 风格的追踪树 + 分步调试思路（择优合并）。
修源时的标准姿势：先跑这个，看 ⚠断链点 在哪一段，只改那一段。

用法：
    # 真实书源，搜索动作
    python debug_source.py data/sources/active/xxx.json --keyword 斗破苍穹

    # 指定源在数组中的下标；跑到详情/目录/正文
    python debug_source.py src.json -i 3 -k 斗破苍穹 --stage toc

    # 用本地 fixtures 离线跑（不发网络请求）
    python debug_source.py tests/fixtures/source.json -k 测试 --local

参数 --stage: search(默认) / info / toc / content
    info/toc/content 会先搜索取第一本书，再顺链往下走。
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from source_engine import SourceEngine, load_sources
from rule_trace import RuleTrace, set_tracer
from selftest import LocalFetcher  # 复用同一份 fixture 抓取替身，避免两处定义漂移

FIX = ROOT / "tests" / "fixtures"


def run(source_path, index=0, keyword="", stage="search", local=False, show_input=False):
    src = load_sources(source_path)[index]
    eng = SourceEngine(src, LocalFetcher() if local else None)

    tracer = RuleTrace(f"{src.get('bookSourceName', '?')} / {stage}")
    set_tracer(tracer)

    result = None
    try:
        books = eng.search(keyword)
        result = books
        if stage != "search":
            if not books:
                print("搜索为空，后续环节无法继续。先修搜索规则。")
            else:
                info = eng.get_book_info(books[0]["bookUrl"])
                result = info
                if stage != "info":
                    toc = eng.get_toc(info.get("tocUrl") or books[0]["bookUrl"])
                    result = toc
                    if stage != "toc":
                        if not toc:
                            print("目录为空，无法取正文。先修目录规则。")
                        else:
                            result = eng.get_content(toc[0]["chapterUrl"])
    except Exception as e:
        print(f"[异常] {type(e).__name__}: {e}")
    finally:
        set_tracer(None)

    print(tracer.render(show_input=show_input))
    print()
    brk = tracer.first_break()
    if brk is None:
        print("✅ 全链路无断点。")
    else:
        print(f"⚠ 先修这一段：{brk.rule_type} {brk.rule}")
    print()
    _preview(result)
    return result, tracer


def _preview(result):
    if result is None:
        print("结果：无")
        return
    if isinstance(result, str):
        s = result.strip().replace("\n", " ⏎ ")
        print(f"结果（正文 {len(result)} 字）：{s[:200]}")
        return
    if isinstance(result, list):
        print(f"结果：{len(result)} 条")
        for r in result[:3]:
            print("  ", {k: v for k, v in r.items() if not k.startswith("_")})
        return
    print("结果：", result)


def main():
    ap = argparse.ArgumentParser(description="书源分步调试器（打印规则执行追踪树）")
    ap.add_argument("source", help="书源 JSON 路径或 URL")
    ap.add_argument("-i", "--index", type=int, default=0, help="源在数组中的下标")
    ap.add_argument("-k", "--keyword", default="", help="搜索关键词")
    ap.add_argument("--stage", default="search", choices=["search", "info", "toc", "content"])
    ap.add_argument("--local", action="store_true", help="用本地 fixtures，不联网")
    ap.add_argument("--show-input", action="store_true", help="同时打印每段的输入片段")
    a = ap.parse_args()
    run(a.source, a.index, a.keyword, a.stage, a.local, a.show_input)


if __name__ == "__main__":
    main()
