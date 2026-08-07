"""获取管道编排：三步可独立验证（对应 计划书 Phase 0）。

Step 1 搜索： load_sources → 多源并发 searchBook → 聚合结果（模型可读）
Step 2 下载： 选一条结果 → 逐章 getContent → 参考/<书名>/
Step 3 转md： 参考/<书名>/ → 正文净化 → 预处理/<书名>.md

CLI：
    python pipeline.py search  <书名> [--idx 15]      # Step1：搜书，打印+缓存结果
    python pipeline.py download <bookUrl> <源名> [书名] # Step2：下载原书到 参考/
    python pipeline.py convert <书名>                 # Step3：参考/ → 预处理/<书名>.md
    python pipeline.py all <书名> [--idx 15]           # 串联：搜→下→md（M4 验证）

说明：默认只跑纯解析源（计划书已定）；java.*/webView 源在 search 阶段捕获异常跳过。
"""
import os
import re
import sys
import json
import argparse
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from bs4 import BeautifulSoup
from source_engine import SourceEngine, load_sources, _safe, REF_DIR

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = ROOT / "data" / "sources"
ACTIVE_DIR = SOURCES_DIR / "active"   # 活跃书源池（已去除登录/Java桥源）；归档见 archive/
DISCOVERED_DIR = SOURCES_DIR / "discovered"  # 自动发现模块生成的源（discover.py 写入）
IMPORTED_DIR = SOURCES_DIR / "imported"  # import_source.py 校验通过的外部订阅源
SEARCH_CACHE = ROOT / "data" / "search"
PREP_DIR = ROOT / "预处理"
SEARCH_CACHE.mkdir(parents=True, exist_ok=True)
PREP_DIR.mkdir(parents=True, exist_ok=True)


def _all_sources():
    """聚合 active/ + discovered/ 下所有书源（支持 .json 数组/单对象/多文件）。
    归档池(archive/)不参与搜索。discovered/ 来自 discover.py 自动发现的源。
    """
    out = []
    for d in (ACTIVE_DIR, DISCOVERED_DIR, IMPORTED_DIR):
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                out += load_sources(str(p))
            except Exception as e:
                print(f"[warn] 载入 {p.name} 失败：{e}")
    return out


def search_all(keyword, indices=None, max_workers=6):
    """Step1：对所有（或指定）书源并发搜索，聚合结果。"""
    sources = _all_sources()
    if indices:
        sources = [sources[i] for i in indices if 0 <= i < len(sources)]
    results = []

    def _one(src):
        try:
            # 全源池并发搜索属批量场景：不落盘原始响应，否则每搜一次就堆几百个 HTML
            eng = SourceEngine(src, debug=False)
            return eng.search(keyword)
        except Exception as e:
            return [{"_error": str(e), "_source": src.get("bookSourceName", "?")}]

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one, s): s for s in sources}
        for f in as_completed(futs):
            res = f.result()
            results.extend(res)
    # 缓存
    cache = SEARCH_CACHE / f"{_safe(keyword)}.json"
    cache.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results, str(cache)


def download(source_name, book_url, book_name=None, max_chapters=None):
    """Step2：按源名找到引擎，下载整本到 参考/<书名>/。max_chapters 可限章数（测试/大书用）。"""
    sources = _all_sources()
    src = next((s for s in sources if source_name in s.get("bookSourceName", "")), None)
    if not src:
        raise SystemExit(f"未找到源：{source_name}")
    eng = SourceEngine(src)
    return eng.download_book(book_url, book_name, max_chapters)


def convert(book_name):
    """Step3：参考/<书名>/*.txt → 预处理/<书名>.md。"""
    src_dir = REF_DIR / _safe(book_name)
    if not src_dir.exists():
        raise SystemExit(f"未找到原书目录：{src_dir}")
    files = sorted(src_dir.glob("[0-9][0-9][0-9][0-9]_*.txt"))
    parts = []
    for fp in files:
        num = fp.name[:4]
        title = fp.name[5:-4]
        body = html_to_text(fp.read_text(encoding="utf-8"))
        parts.append(f"## 第{int(num)}节 {title}\n\n{body}\n")
    meta_p = src_dir / "_meta.json"
    header = ""
    if meta_p.exists():
        m = json.loads(meta_p.read_text(encoding="utf-8"))
        header = f"# {m.get('name','')}\n\n> 作者：{m.get('author','')} ｜ 来源：{m.get('source','')} ｜ 章节数：{m.get('chapterCount','')}\n\n"
    md = header + "\n".join(parts)
    out = PREP_DIR / f"{_safe(book_name)}.md"
    out.write_text(md, encoding="utf-8")
    return str(out), len(parts)


def html_to_text(html):
    """极简 HTML→纯文本（保留段落）。v1 够用；后续可换 html2text。"""
    if not html or "<" not in html:
        return (html or "").strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return re.sub(r"\n{3,}", "\n\n", text)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    ps = sub.add_parser("search"); ps.add_argument("kw"); ps.add_argument("--idx", type=int, nargs="*")
    pd = sub.add_parser("download"); pd.add_argument("url"); pd.add_argument("source"); pd.add_argument("name", nargs="?"); pd.add_argument("--max", type=int, default=None)
    pc = sub.add_parser("convert"); pc.add_argument("name")
    pa = sub.add_parser("all"); pa.add_argument("kw"); pa.add_argument("--idx", type=int, nargs="*"); pa.add_argument("--max", type=int, default=None)
    args = ap.parse_args()

    if args.cmd == "search":
        res, cache = search_all(args.kw, args.idx)
        _print_search(res)
        print(f"\n[缓存] {cache}")
    elif args.cmd == "download":
        info = download(args.source, args.url, args.name, args.max)
        print(f"[下载] {info['name']} → {info['dir']}（{info['chapters']} 章）")
    elif args.cmd == "convert":
        out, n = convert(args.name)
        print(f"[转md] {out}（{n} 节）")
    elif args.cmd == "all":
        res, cache = search_all(args.kw, args.idx)
        ok = [r for r in res if r.get("bookUrl") and not r.get("_error")]
        if not ok:
            print("[all] 无可用结果，先单独跑 search 看哪一步出问题。")
            return
        b = ok[0]
        print(f"[all] 选用：{b.get('name')} / {b.get('_source')} / {b.get('bookUrl')}")
        info = download(b.get("_source"), b["bookUrl"], b.get("name"), args.max)
        out, n = convert(info["name"])
        print(f"[all] 完成 → {out}（{n} 节）")
    else:
        ap.print_help()


def _print_search(res):
    n = len([r for r in res if r.get("bookUrl") and not r.get("_error")])
    print(f"[搜索] 共 {len(res)} 条，其中有效 {n} 条：")
    for i, r in enumerate(res):
        if r.get("_error"):
            print(f"  ✗ {r.get('_source')}: {r['_error'][:60]}")
        else:
            print(f"  {i:2d}. {r.get('name','?')} — {r.get('author','?')}  [{r.get('_source')}]")
            print(f"       {r.get('bookUrl','')[:80]}")


if __name__ == "__main__":
    main()
