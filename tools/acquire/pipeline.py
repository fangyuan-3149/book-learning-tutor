"""获取管道编排：三步可独立验证（对应 计划书 Phase 0）。

Step 1 搜索： load_sources → 多源并发 searchBook → 聚合结果（模型可读）
Step 2 下载： 选一条结果 → 逐章 getContent → 参考/<书名>/
Step 3 转md： 参考/<书名>/ → 正文净化 → 预处理/<书名>.md
格式层 ingest： 本地 PDF/EPUB/DJVU/TXT/MD → 参考/<书名>/NNNN_title.txt（补"只能翻txt"短板）

CLI：
    python pipeline.py search  <书名> [--idx 15]      # Step1：搜书，打印+缓存结果
    python pipeline.py download <bookUrl> <源名> [书名] # Step2：下载原书到 参考/
    python pipeline.py ingest <文件或目录> [--name 书名] # 格式层：本地书 → 参考/
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
from source_engine import SourceEngine, load_sources, _safe, REF_DIR, write_robust
from book_formats import extract as extract_book, unpack_cbz  # 格式层：文本三元组 + CBZ 漫画解包

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
    # 先精确匹配源名，避免子串误选（如 "笔" 同时命中多个含 "笔" 的源）；
    # 精确未命中再退回子串（保留用户只打关键字部分的便利）。
    src = next((s for s in sources if source_name == s.get("bookSourceName", "")), None) \
        or next((s for s in sources if source_name in s.get("bookSourceName", "")), None)
    if not src:
        raise SystemExit(f"未找到源：{source_name}")
    eng = SourceEngine(src)
    return eng.download_book(book_url, book_name, max_chapters)


def convert(book_name):
    """Step3：参考/<书名>/*.txt → 预处理/<书名>.md（正确章/节层级）。

    读 _sections.json 分组；无清单时退化为「每 txt=一章」（兼容下载/旧目录）。
    输出：书名/作者作普通文本头（不被 course_gen 当成章），每「章」一个
    '# 章名'，章内每「节」一个 '## 节名'；小说章无节则正文直接挂在 '# 章' 下
    （→ course_gen 每章一课，不嵌套）。
    """
    src_dir = REF_DIR / _safe(book_name)
    if not src_dir.exists():
        raise SystemExit(f"未找到原书目录：{src_dir}")
    meta_p = src_dir / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}

    man_p = src_dir / "_sections.json"
    if man_p.exists():
        manifest = json.loads(man_p.read_text(encoding="utf-8"))
    else:
        # 兼容下载/旧目录：每个 NNNN_*.txt = 一章（小说源每章一文件），section=None
        files = sorted(src_dir.glob("[0-9][0-9][0-9][0-9]_*.txt"))
        manifest = [{"chapter": fp.name[5:-4], "section": None,
                     "title": fp.name[5:-4], "file": fp.name} for fp in files]

    # 按章分组（保持首次出现顺序）
    order = []
    groups = {}
    for e in manifest:
        ch = e.get("chapter") or e.get("title") or "正文"
        if ch not in groups:
            groups[ch] = []
            order.append(ch)
        groups[ch].append(e)

    parts = []
    for ch in order:
        parts.append(f"# {_strip_num_prefix(ch)}\n")  # 章：一级标题
        for e in groups[ch]:
            body = ""
            fpath = src_dir / e["file"]
            if fpath.exists():
                body = _sanitize_body(html_to_text(fpath.read_text(encoding="utf-8")))
            if e.get("section"):
                parts.append(f"## {_strip_num_prefix(e['section'])}\n\n{body}\n")  # 节：二级
            else:
                parts.append(f"{body}\n")  # 小说章：正文直接挂章下（→每章一课）
    header = (f"{meta.get('name','')}\n\n"
              f"> 作者：{meta.get('author','')} ｜ 来源：{meta.get('source','')} ｜ "
              f"章节数：{meta.get('chapterCount','')} ｜ 类型：{meta.get('bookType','')}\n\n")
    md = header + "\n".join(parts)
    out = PREP_DIR / f"{_safe(book_name)}.md"
    if not write_robust(out, md, label="预处理"):
        print(f"[warn] 预处理文件写入被拦截：{out.name}（前次产物仍在，未覆盖）")
    return str(out), len(manifest)


def _strip_num_prefix(title):
    """去掉标题首部『第N章/节/课』编号词（避免与 course_gen 自动加的 第XX章 重复）。"""
    return re.sub(r"^第[0-9零一二三四五六七八九十百千]+\s*[章章节节节课部分段篇]\s*",
                  "", (title or "")).strip()


def _sanitize_body(text):
    """正文内若以 '#' 起头（如 Python 代码清单注释 '# File: chaos.py'、被 pymupdf
    抽进正文的页眉），会被下游 course_gen 误判为 markdown 标题→垃圾章。转义行首 '#'
    为 '\\#'（渲染为字面 '#'，不触发标题），既保真又消除垃圾章。"""
    if not text:
        return ""
    return re.sub(r"(?m)^#", r"\\#", text)


# 目录模式下只认这些"真书"格式，避免把项目里的 .md/.txt/venv 误吸进 参考/
_BOOK_EXTS = {".pdf", ".epub", ".djvu", ".mobi", ".azw", ".azw3", ".docx", ".fb2", ".cbz"}
# 目录递归时跳过的噪声目录（含 venv / 仓库元数据 / 产物目录）
_SKIP_DIRS = {"venv", ".venv", ".git", "node_modules", "data", "参考", "预处理",
              "书库", ".workbuddy", "__pycache__"}


def ingest(path, book_name=None, cbz_chunks=None):
    """格式层入口：本地书籍文件/目录 → 参考/<书名>/NNNN_title.txt。

    path 为文件：整本作为一本书（书名=--name 或文件名）。
    path 为目录：目录下（含子目录，跳过 venv/.git/产物等噪声目录）每个
                 pdf/epub/djvu/mobi/azw/azw3/docx/fb2/cbz 各作为一本书（书名=文件名）。
    抽出的章节直接落 参考/<书名>/，下游 convert → course_gen 零改动消费。
    cbz_chunks：仅对扁平整包 CBZ 生效——把无分目录的整包按图片序切成 N 话
                （用于人为恢复章结构）；CBZ 已含多顶层子目录时忽略（子目录即分章）。
    """
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"路径不存在：{path}")
    if p.is_file():
        files = [p]
    else:
        files = sorted(
            f for f in p.rglob("*")
            if f.is_file() and f.suffix.lower() in _BOOK_EXTS
            and not any(part in _SKIP_DIRS for part in f.parts))
    if not files:
        raise SystemExit(f"未找到可抽取的书文件（pdf/epub/djvu/mobi/azw/azw3/docx/fb2/cbz）：{path}")
    total_sec = 0
    for f in files:
        name = book_name or (p.stem if p.is_file() else f.stem)
        fmt = detect_format_local(f)

        # —— CBZ（漫画）：不走文本三元组，直接解包到 参考/<书名>/ 漫画布局 ——
        if fmt == "cbz":
            out_dir = REF_DIR / _safe(name)
            try:
                n_ch, n_pg = unpack_cbz(str(f), out_dir, chapters=cbz_chunks)
            except Exception as e:
                print(f"[warn] 跳过 {f.name}：{e}")
                continue
            meta = {"name": name, "format": "cbz", "bookType": "comic",
                    "chapterCount": n_ch, "pageCount": n_pg,
                    "source": "local-file"}
            write_robust(out_dir / "_meta.json",
                         json.dumps(meta, ensure_ascii=False, indent=2), label="参考")
            print(f"[ingest] {f.name} → 参考/{_safe(name)}/ （漫画 {n_ch} 话 / {n_pg} 页，cbz）"
                  f"下一步：python course_gen.py 参考/{_safe(name)}/")
            total_sec += n_ch
            continue

        # —— 文本类格式：extract → 三元组 → 参考/<书名>/NNNN_title.txt ——
        try:
            r = extract_book(str(f))
        except Exception as e:
            print(f"[warn] 跳过 {f.name}：{e}")
            continue
        out_dir = REF_DIR / _safe(name)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = []
        for i, sec in enumerate(r["sections"], 1):
            fn = out_dir / f"{i:04d}_{_safe(sec['title'])[:40]}.txt"
            write_robust(fn, sec["text"], label="参考")
            manifest.append({"chapter": sec["chapter"], "section": sec["section"],
                             "title": sec["title"], "file": fn.name})
        # 章/节分组清单：convert 据此输出 # 章 / ## 节 的正确 md（修嵌套 bug）
        write_robust(out_dir / "_sections.json",
                     json.dumps(manifest, ensure_ascii=False, indent=2), label="参考")
        # 顺手写 _meta.json，convert 会读 name/author/source/bookType
        meta = dict(r.get("meta", {}))
        meta.update({"name": name, "chapterCount": len(r["sections"]),
                     "format": r["fmt"], "needsOcr": r["needs_ocr"],
                     "bookType": r.get("book_type", "unknown")})
        write_robust(out_dir / "_meta.json", json.dumps(meta, ensure_ascii=False, indent=2), label="参考")
        flag = " [⚠ 疑似扫描版，需OCR]" if r["needs_ocr"] else ""
        print(f"[ingest] {f.name} → 参考/{_safe(name)}/ （{len(r['sections'])} 节，"
              f"{r['fmt']}，{r.get('book_type','unknown')}）{flag}")
        total_sec += len(r["sections"])
    print(f"[ingest] 完成，共 {total_sec} 节。下一步：python pipeline.py convert {book_name or '<书名>'}")



def detect_format_local(f):
    from book_formats import detect_format
    return detect_format(str(f))


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
    pi = sub.add_parser("ingest"); pi.add_argument("path"); pi.add_argument("--name", default=None)
    pi.add_argument("--chunks", type=int, default=None, help="扁平整包 CBZ 按图片序切成 N 话（仅漫画、且整包无分目录时生效）")
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
    elif args.cmd == "ingest":
        ingest(args.path, args.name, cbz_chunks=args.chunks)
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
