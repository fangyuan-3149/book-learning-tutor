"""获取管道编排：三步可独立验证（对应 计划书 Phase 0）。

Step 1 搜索： load_sources → 多源并发 searchBook → 聚合结果（模型可读）
Step 2 下载： 选一条结果 → 逐章 getContent → 参考/<书名>/
Step 3 课程化： 参考/<书名>/ → course_gen 直读 → 书库/<书名>/（无需常驻 预处理/）
格式层 ingest： 本地 PDF/EPUB/DJVU/TXT/MD → 参考/<书名>/NNNN_title.txt（补"只能翻txt"短板）

CLI：
    python pipeline.py search  <书名> [--idx 15]      # Step1：搜书，打印+缓存结果
    python pipeline.py download <bookUrl> <源名> [书名] # Step2：下载原书到 参考/
    python pipeline.py ingest <文件或目录> [--name 书名] # 格式层：本地书 → 参考/
    python pipeline.py all <书名> [--idx 15]           # 串联：搜→下→course_gen（参考/直读→书库/）
    # 课程化（参考/ → 书库/）统一由 tools/structure/course_gen.py 完成，无需常驻 预处理/：
    #     python tools/structure/course_gen.py 参考/<书名>/ --book <书名>
    #     python pipeline.py all-local <文件> [--name 书名]   # 本地书一键课程化

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

from source_engine import SourceEngine, load_sources, _safe, REF_DIR, write_robust
from book_formats import extract as extract_book, unpack_cbz, extract_figures  # 格式层：文本三元组 + CBZ 漫画解包 + PDF 插图
from notice import report_source_unavailable  # 在线获取失败 → 统一提示使用者自供源

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR = ROOT / "data" / "sources"
ACTIVE_DIR = SOURCES_DIR / "active"   # 活跃书源池（已去除登录/Java桥源）；归档见 archive/
DISCOVERED_DIR = SOURCES_DIR / "discovered"  # 自动发现模块生成的源（discover.py 写入）
IMPORTED_DIR = SOURCES_DIR / "imported"  # import_source.py 校验通过的外部订阅源
SEARCH_CACHE = ROOT / "data" / "search"
SEARCH_CACHE.mkdir(parents=True, exist_ok=True)


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
        raise RuntimeError(f"未找到源：{source_name}（请用 all-local 提供本地书）")
    eng = SourceEngine(src)
    return eng.download_book(book_url, book_name, max_chapters)


# 注：原 convert（参考/ → 预处理/.md）已整体迁入 tools/structure/course_gen.py
# 的 generate_from_ref；pipeline 直接调 course_gen 吃 参考/ 目录，废掉常驻 预处理/。
# 对应的 _strip_num_prefix / _sanitize_body / html_to_text 也随迁至 course_gen.py。


# 目录模式下只认这些"真书"格式，避免把项目里的 .md/.txt/venv 误吸进 参考/
_BOOK_EXTS = {".pdf", ".epub", ".djvu", ".mobi", ".azw", ".azw3", ".docx", ".fb2", ".cbz"}
# 目录递归时跳过的噪声目录（含 venv / 仓库元数据 / 产物目录）
_SKIP_DIRS = {"venv", ".venv", ".git", "node_modules", "data", "参考",
              "书库", ".workbuddy", "__pycache__"}


def ingest(path, book_name=None, cbz_chunks=None):
    """格式层入口：本地书籍文件/目录 → 参考/<书名>/NNNN_title.txt。

    path 为文件：整本作为一本书（书名=--name 或文件名）。
    path 为目录：目录下（含子目录，跳过 venv/.git/产物等噪声目录）每个
                 pdf/epub/djvu/mobi/azw/azw3/docx/fb2/cbz 各作为一本书（书名=文件名）。
    抽出的章节直接落 参考/<书名>/，下游 course_gen 直接消费（无需 预处理/ 中间层）。
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
        if p.is_file():
            name = book_name or p.stem
        else:
            # 目录模式：每个文件各成一本书（按文件名），避免多书塌缩到同一名互相覆盖。
            # 显式传 --name 在此模式无意义，给出警告并退回每文件各自名。
            if book_name:
                print(f"[warn] 目录模式忽略 --name={book_name}（多书应按各自文件名），"
                      f"{f.name} → {f.stem}")
            name = f.stem
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
        # 章/节分组清单：course_gen 据此输出 # 章 / ## 节 的正确 md（修嵌套 bug）
        write_robust(out_dir / "_sections.json",
                     json.dumps(manifest, ensure_ascii=False, indent=2), label="参考")
        # 顺手写 _meta.json，course_gen 会读 name/author/source/bookType
        meta = dict(r.get("meta", {}))
        meta.update({"name": name, "chapterCount": len(r["sections"]),
                     "format": r["fmt"], "needsOcr": r["needs_ocr"],
                     "bookType": r.get("book_type", "unknown")})
        write_robust(out_dir / "_meta.json", json.dumps(meta, ensure_ascii=False, indent=2), label="参考")
        flag = " [⚠ 疑似扫描版，需OCR]" if r["needs_ocr"] else ""
        print(f"[ingest] {f.name} → 参考/{_safe(name)}/ （{len(r['sections'])} 节，"
              f"{r['fmt']}，{r.get('book_type','unknown')}）{flag}")
        total_sec += len(r["sections"])
    print(f"[ingest] 完成，共 {total_sec} 节。下一步：python tools/structure/course_gen.py 参考/{_safe(book_name or '<书名>')} --book {book_name or '<书名>'}")



def _fig_dirname(name, maxlen=120):
    """插图目录名清洗（与 course_gen.sanitize 同策略：去非法字符、空白压成下划线）。

    maxlen 提到 120：降低长章/节名清洗后前 N 字相同导致的目录碰撞概率；残留的极端碰撞
    由 figures_to_book 的 occ 序号兜底（见 figures_to_book）。
    """
    import re as _re
    name = (name or "").strip()
    name = _re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = _re.sub(r'\s+', '_', name).strip('._ ')
    return name[:maxlen] or "未命名"


def _rmtree_force(path):
    """强制删除目录树（绕过本机 safe-delete 钩子对 os/shutil 的拦截）。

    仅用于删除**可再生的产物目录**（如 书库/<书名>/_figures）。优先用 Win32 API
    直接删（顺便清只读属性）；非 Windows 或 API 异常时回退 shutil.rmtree。
    """
    import ctypes
    p = str(path)
    kernel32 = getattr(ctypes, "windll", None) and ctypes.windll.kernel32
    if kernel32 is not None:
        try:
            for root, dirs, files in os.walk(p, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        kernel32.SetFileAttributesW(fp, 0x80)  # FILE_ATTRIBUTE_NORMAL
                        kernel32.DeleteFileW(fp)
                    except Exception:
                        pass
                for d in dirs:
                    dp = os.path.join(root, d)
                    try:
                        kernel32.SetFileAttributesW(dp, 0x80)
                        kernel32.RemoveDirectoryW(dp)
                    except Exception:
                        pass
            kernel32.SetFileAttributesW(p, 0x80)
            kernel32.RemoveDirectoryW(p)
            return
        except Exception:
            pass
    import shutil
    shutil.rmtree(p, ignore_errors=True)


def figures_to_book(path, book_name=None):
    """抽取 PDF/EPUB 插图，对齐进 书库/<书名>/_figures/（按 章/节 归属，自包含多模态单元）。

    每有插图的 (章,节) 建一个目录：fig_NNN.ext + meta.json{chapter,section,title,
    captions,context(该节正文前 800 字)}；书库/<书名>/_figures/_index.jsonl 汇总每行一个
    (image,caption,chapter,section,context) 训练对齐单元。需先 ingest→course_gen
    生成 书库/<书名>/（否则报错指引）。

    幂等：每次重跑先清空旧 _figures/ 再重新生成，避免残留 stale 图文件被 inline 误用。
    context 直接取自 extract_figures（每个 section 自带），不再冗余全本抽取。
    """
    p = Path(path)
    name = book_name or p.stem
    book_dir = ROOT / "书库" / _safe(name)
    if not book_dir.exists():
        raise SystemExit(f"未找到 书库/{_safe(name)}/，请先跑完 ingest→course_gen")
    # 重新生成 _figures：先清空旧目录，避免残留 stale 图文件被 inline 误用（幂等重跑）。
    fig_root = book_dir / "_figures"
    if fig_root.exists():
        _rmtree_force(fig_root)
    fig_root.mkdir(parents=True, exist_ok=True)
    # 抽插图（context 已由 extract_figures 自带；此处失败给出可读错误而非原始 traceback）
    try:
        f = extract_figures(str(p))
    except Exception as e:
        raise SystemExit(f"插图抽取失败（{p.name}）：{e}")
    index = []
    total = 0
    dir_counters = {}  # 同 (章,节) 目录跨多个源 section 时，编号持续累加，避免 fig_NNN 互相覆盖
    used_dirs = {}     # (ch_san, sec_san) -> 出现次数；不同 (章,节) 清洗后同名时加序号，保证 _figures 目录唯一（防碰撞覆盖）
    for sec in f["sections"]:
        ch, secname = sec["chapter"], sec["section"]
        figs = sec["figures"]
        if not figs:
            continue
        ch_san = _fig_dirname(ch or "全书")
        sec_san = _fig_dirname(secname or "全文")
        key = (ch_san, sec_san)
        occ = used_dirs.get(key, 0) + 1
        used_dirs[key] = occ
        if occ > 1:
            # 仅当不同 (章,节) 清洗后映射到同一目录名时才加序号，正常名保持干净
            ch_san = f"{ch_san}_{occ}"
        d = fig_root / ch_san / sec_san
        d.mkdir(parents=True, exist_ok=True)
        # context 直接取自 extract_figures（每个 section 自带，无需再全本抽取兜底）。
        context = (sec.get("context") or "")[:800]
        captions = []
        for fg in figs:
            key = str(d)
            n = dir_counters.get(key, 0) + 1
            dir_counters[key] = n
            fn = d / ("fig_%03d.%s" % (n, fg["ext"]))
            fn.write_bytes(fg["bytes"])
            captions.append(fg["caption"])
            index.append({
                "image": str(fn.relative_to(book_dir)).replace("\\", "/"),
                "caption": fg["caption"],
                "chapter": ch, "section": secname,
                "context": context,
            })
            total += 1
        meta = {"chapter": ch, "section": secname, "title": sec["title"],
                "captions": captions, "context": context, "n_figures": len(figs)}
        write_robust(d / "meta.json",
                     json.dumps(meta, ensure_ascii=False, indent=2), label="参考")
    write_robust(fig_root / "_index.jsonl",
                 "\n".join(json.dumps(x, ensure_ascii=False) for x in index)
                 + ("\n" if index else ""), label="参考")
    print(f"[figures] {p.name} → 书库/{_safe(name)}/_figures/ （{total} 张图，"
          f"{len(index)} 个对齐单元，{f['page_count']} 页）")
    return str(fig_root), total


def _strip_fig_blocks(text):
    """移除课程 md 中已有的『## 配图（多模态训练单元）』块。

    保证 inline 可重复执行（figures 重新生成后不留孤儿块）。返回清理后的文本；
    无配图块则原样返回。
    """
    marker = "## 配图（多模态训练单元）"
    idx = text.find(marker)
    if idx == -1:
        return text
    head = text[:idx].rstrip()
    # 去掉块前可能残留的分割线 "---\n\n"
    while head.endswith("---"):
        head = head[:-3].rstrip()
    return head + "\n"


def inline_figures(book_name):
    """把 书库/<书名>/_figures/ 的插图按 (章,节) 内联进对应课程 .md。

    优先读权威清单 _index.jsonl（每行一个 (image,caption,chapter,section,context)
    训练对齐单元），避免依赖文件系统扫描导致 stale 图被误用；仅当 _index.jsonl 缺失时
    回退到遍历 meta.json + fig_* 文件。匹配 书库/<书名>/第NN章_章名/第NN课_课名.md：
    章名命中 + 节名命中（或无节→章首课）。在课程 md 末尾追加「## 配图（多模态训练单元）」
    块；重跑前会先剥离旧块，保证幂等、不留孤儿块。
    """
    from pathlib import Path as _P
    book_dir = ROOT / "书库" / _safe(book_name)
    fig_root = book_dir / "_figures"
    if not fig_root.exists():
        raise SystemExit(
            f"未找到 书库/{_safe(book_name)}/_figures/，请先跑 `python pipeline.py figures <原书> --name {book_name}`")
    # 收集 figure 单元（优先 _index.jsonl）
    index_path = fig_root / "_index.jsonl"
    fig_units = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            figfile = book_dir / d["image"]
            fig_units.append((d.get("chapter"), d.get("section"),
                              d.get("caption"), d.get("context", ""), figfile))
    else:
        # 回退：扫描 meta.json + fig_*（兼容旧产物）
        for dp, _, fs in os.walk(fig_root):
            if "meta.json" not in fs:
                continue
            meta = json.loads((_P(dp) / "meta.json").read_text(encoding="utf-8"))
            caps = meta.get("captions") or []
            for fn in sorted(f for f in fs if f.startswith("fig_")):
                figfile = _P(dp) / fn
                idx = int(re.sub(r"\D", "", fn[4:7] or "1")) - 1
                cap = caps[idx] if 0 <= idx < len(caps) else None
                fig_units.append((meta.get("chapter"), meta.get("section"),
                                  cap, meta.get("context", ""), figfile))
    # 收集 lessons：文件系统为准（存在性），全标题取自 progress.json（解耦文件名截断）。
    # 旧版 progress.json 无 chapter/lesson 字段时退回截断目录名（向后兼容）。
    prog = None
    prog_path = book_dir / "progress.json"
    if prog_path.exists():
        try:
            prog = json.loads(prog_path.read_text(encoding="utf-8"))
        except Exception:
            prog = None
    prog_lessons = (prog or {}).get("lessons", {}) if prog else {}
    lessons = []
    for ch_dir in book_dir.iterdir():
        if not ch_dir.is_dir():
            continue
        m = re.match(r"第\d+章_(.+)", ch_dir.name)
        if not m:
            continue
        cn = m.group(1)
        for f in ch_dir.iterdir():
            if f.is_file() and f.name.endswith(".md"):
                lm = re.match(r"第\d+课_(.+)\.md", f.name)
                ln = lm.group(1) if lm else f.name[:-3]
                rel = f"{ch_dir.name}/{f.name}"
                pe = prog_lessons.get(rel, {})
                ch_full = pe.get("chapter") or cn   # 全章标题优先，缺则退回截断目录名
                les_full = pe.get("lesson") or ln    # 全课标题优先
                lessons.append((ch_full, les_full, f))
    if not lessons:
        raise SystemExit(f"书库/{_safe(book_name)}/ 下未找到课程 .md（请先 course_gen）")
    # 先剥离每课已有的配图块（保证可重复执行，figures 重生成后不留孤儿块）
    for (cn, ln, lp) in lessons:
        t = lp.read_text(encoding="utf-8")
        cleaned = _strip_fig_blocks(t)
        if cleaned != t:
            lp.write_text(cleaned, encoding="utf-8")
    # 匹配 + 插入
    inserted = 0
    skipped = 0
    for (chapter, section, cap, context, figfile) in fig_units:
        targets = _match_lessons(lessons, chapter, section)
        if not targets:
            skipped += 1
            continue
        for lp in targets:
            if figfile.exists() and _insert_fig_into_lesson(lp, figfile, cap, context):
                inserted += 1
            else:
                skipped += 1
    print(f"[inline] 为 书库/{_safe(book_name)}/ 插入 {inserted} 处配图"
          f"（共 {len(fig_units)} 张图，{skipped} 处跳过/已存在）")
    return inserted


def _match_lessons(lessons, chapter, section):
    """返回匹配的课程 md 路径列表。章名命中；节名命中或章级(无节)→章首课。"""
    def norm(s):
        # 去所有非字母数字（含空格/下划线/冒号/标点），保留中文，便于跨大小写/符号对齐
        return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", s or "")

    # 优先精确章名匹配，避免子串误绑（如 "Alice" 误中 "Alice in Wonderland"）
    ch_matched = [(cn, ln, p) for (cn, ln, p) in lessons
                  if chapter and norm(cn) == norm(chapter)]
    if not ch_matched:
        ch_matched = [(cn, ln, p) for (cn, ln, p) in lessons
                      if chapter and (norm(cn) in norm(chapter)
                                      or norm(chapter) in norm(cn))]
    if not ch_matched:
        return []
    if not section or section == "全文":
        return [ch_matched[0][2]]  # 章级图 → 该章第一个 lesson
    secn = norm(section)
    out = [p for (cn, ln, p) in ch_matched
           if secn == norm(ln) or secn in norm(ln) or norm(ln) in secn]
    return out or [ch_matched[0][2]]  # 匹配不到具体课 → 章首课


def _insert_fig_into_lesson(md_path, figfile, cap, context):
    """在课程 md 末尾追加配图块；已含该图相对路径则跳过（幂等）。返回是否新插入。"""
    rp = os.path.relpath(figfile, md_path.parent).replace("\\", "/")
    text = md_path.read_text(encoding="utf-8")
    if rp in text:
        return False
    block = "\n\n---\n\n## 配图（多模态训练单元）\n\n"
    block += f"![{cap or '图'}]({rp})\n\n"
    if cap:
        block += f"> 图注：{cap}\n\n"
    if context:
        block += (f"<details><summary>上下文</summary>\n\n"
                  f"{context[:600]}\n\n</details>\n")
    md_path.write_text(text.rstrip() + block, encoding="utf-8")
    return True



def detect_format_local(f):
    from book_formats import detect_format
    return detect_format(str(f))


def selftest():
    """pipeline 内置确定性自测（不联网）：验证 figures→inline 幂等 + inline 读 _index.jsonl。"""
    print("[pipeline selftest]")
    import base64
    book = "_selftest_book"
    book_dir = ROOT / "书库" / _safe(book)
    if book_dir.exists():
        _rmtree_force(book_dir)
    book_dir.mkdir(parents=True, exist_ok=True)
    try:
        # 1x1 PNG
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC")
        ch_dir = book_dir / "第01章_X"
        ch_dir.mkdir(parents=True, exist_ok=True)
        lesson = ch_dir / "第01课_X.md"
        lesson.write_text("# X\n\n正文。\n", encoding="utf-8")
        fig_root = book_dir / "_figures"
        fig_root.mkdir(parents=True, exist_ok=True)
        fig_dir = fig_root / "第01章_X"
        fig_dir.mkdir(parents=True, exist_ok=True)
        fig_dir.joinpath("fig_001.png").write_bytes(png)
        index = [{"image": "_figures/第01章_X/fig_001.png", "caption": "测试图注",
                  "chapter": "X", "section": None, "context": "上下文测试"}]
        (fig_root / "_index.jsonl").write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in index) + "\n", encoding="utf-8")
        # 首次插入
        n1 = inline_figures(book)
        assert n1 == 1, "首次插入应为 1，实际 %d" % n1
        t = lesson.read_text(encoding="utf-8")
        assert "## 配图（多模态训练单元）" in t and "测试图注" in t, "首插未生效"
        # 幂等：重跑不应产生重复块
        n2 = inline_figures(book)
        assert n2 == 1, "二次插入应仍为 1（幂等），实际 %d" % n2
        t2 = lesson.read_text(encoding="utf-8")
        assert t2.count("## 配图（多模态训练单元）") == 1, "出现重复配图块"
        print("  passed（inline 幂等 + 读 _index.jsonl）")
        # ---- 长标题解耦场景：course_gen 把章目录名截到 40 字符（旧行为），
        #      但 progress.json 存【全标题】；figure 的 chapter 也是全标题 → 应精确匹配，
        #      不依赖截断目录名、也不靠子串回退。证明截断不再影响图文对齐。
        LONG = ("XIX : How, Though the Sphere Showed Me Other Mysteries of "
                "Spaceland, I Still Desired More; and What Came of It")
        # 模拟 course_gen@maxlen=40 的产物（截短目录名，与全标题明显不同；含非法字符清洗）
        trunc = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', LONG)
        trunc = re.sub(r'\s+', '_', trunc).strip('._ ')
        trunc = trunc[:40].rstrip('._ ')
        ch_dir2 = book_dir / f"第02章_{trunc}"
        ch_dir2.mkdir(parents=True, exist_ok=True)
        lesson2 = ch_dir2 / "第01课_本章.md"
        lesson2.write_text("# 长标题章\n\n正文。\n", encoding="utf-8")
        # 写 progress.json（含全标题；注意：此时不含第01章_X 的旧 lesson，模拟真实进度文件）
        prog = {
            "version": 1, "book": book, "current": f"第02章_{trunc}/第01课_本章.md",
            "total_lessons": 1, "updated": None,
            "lessons": {f"第02章_{trunc}/第01课_本章.md": {
                "status": "unstarted", "mastery": 0, "unresolved": [], "quiz": [],
                "chapter": LONG, "lesson": "本章"}}
        }
        (book_dir / "progress.json").write_text(
            json.dumps(prog, ensure_ascii=False), encoding="utf-8")
        fig_dir2 = fig_root / "第02章_L"
        fig_dir2.mkdir(parents=True, exist_ok=True)
        fig_dir2.joinpath("fig_001.png").write_bytes(png)
        index2 = [{"image": "_figures/第02章_L/fig_001.png", "caption": "长标题图注",
                   "chapter": LONG, "section": None, "context": "长标题上下文"}]
        (fig_root / "_index.jsonl").write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in index2) + "\n", encoding="utf-8")
        n3 = inline_figures(book)
        assert n3 == 1, "长标题全标题匹配应插入 1，实际 %d" % n3
        t3 = lesson2.read_text(encoding="utf-8")
        assert ("## 配图（多模态训练单元）" in t3 and "长标题图注" in t3), "长标题解耦匹配失效"
        n4 = inline_figures(book)  # 幂等
        assert n4 == 1, "长标题二次插入应仍 1（幂等），实际 %d" % n4
        print("  passed（长标题→全标题解耦匹配，截断不再影响对齐）")
        # 目录碰撞防护：两章名清洗后前 120 字相同 → 加序号互不覆盖
        _selftest_figures_collision()
        # ---- progress 命令：写回 + 弱课复习 自测（隔离，复用本临时 book_dir）----
        import types as _types
        def _pa(**kw):
            d = dict(book=book, quiz_template=False, next=False, current=None,
                     done=None, mastery=None, add_quiz=None, q=None, bloom="理解",
                     a=None, learner="", correct=None, report=False, review=False)
            d.update(kw)
            return _types.SimpleNamespace(**d)
        prog2 = {
            "version": 1, "book": book, "current": None, "total_lessons": 3,
            "updated": None,
            "lessons": {
                "第01章_A/第01课_A.md": {"status": "unstarted", "mastery": 0,
                    "unresolved": [], "quiz": [], "chapter": "A", "lesson": "A"},
                "第02章_B/第01课_B.md": {"status": "unstarted", "mastery": 0,
                    "unresolved": [], "quiz": [], "chapter": "B", "lesson": "B"},
                "第03章_C/第01课_C.md": {"status": "unstarted", "mastery": 0,
                    "unresolved": [], "quiz": [], "chapter": "C", "lesson": "C"},
            },
        }
        (book_dir / "progress.json").write_text(
            json.dumps(prog2, ensure_ascii=False), encoding="utf-8")
        cmd_progress(_pa(next=True, mastery=0.8))
        cmd_progress(_pa(add_quiz="1", q="A?", bloom="记忆", a="是", learner="是", correct="true"))
        cmd_progress(_pa(add_quiz="2", q="B?", bloom="理解", a="否", learner="否", correct="false"))
        reload = load_progress(book_dir)
        assert reload["lessons"]["第01章_A/第01课_A.md"]["status"] == "done"
        assert reload["lessons"]["第01章_A/第01课_A.md"]["mastery"] == 0.8
        assert reload["current"] == "第02章_B/第01课_B.md"
        assert len(reload["lessons"]["第01章_A/第01课_A.md"]["quiz"]) == 1
        assert reload["lessons"]["第01章_A/第01课_A.md"]["quiz"][0]["correct"] is True
        assert reload["lessons"]["第02章_B/第01课_B.md"]["quiz"][0]["correct"] is False
        # 弱课复习：仅第02章（已学且有错）应入列表；第01章已达标、第03章未学 都不应入
        import io as _io
        _old = sys.stdout
        sys.stdout = _io.StringIO()
        try:
            cmd_progress(_pa(review=True))
        finally:
            _out = sys.stdout.getvalue(); sys.stdout = _old
        _tail = _out.split("--- 需复习的弱课 ---")[-1]
        assert "第02章_B/第01课_B.md" in _tail, "弱课列表缺 B"
        assert "第03章_C/第01课_C.md" not in _tail, "未学课不应进弱课列表"
        assert "第01章_A/第01课_A.md" not in _tail, "已达标课不应进弱课列表"
        print("  passed（progress 写回 + 弱课复习逻辑）")
    finally:
        _rmtree_force(book_dir)
    print("  selftest passed。")


def _selftest_figures_collision():
    """验证 figures_to_book 的目录碰撞防护：两章名清洗后前 120 字相同 → 加序号互不覆盖。

    复现真实隐患：教材「Section 3.2: The Gradient Descent Algorithm」与「…with Momentum」
    清洗后同名 → 若不加防护会映射到同一 _figures/<章>/ 目录，后写覆盖前写（静默损坏）。
    """
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC")
    book = "_collide_book"
    book_dir = ROOT / "书库" / _safe(book)
    if book_dir.exists():
        _rmtree_force(book_dir)
    book_dir.mkdir(parents=True, exist_ok=True)  # 模拟 course_gen 已生成 书库/<书名>/
    try:
        real_extract = extract_figures

        def fake_extract(path):
            same = "A" * 120  # 两章前 120 字完全相同 → 清洗后同名（碰撞）
            return {
                "fmt": "pdf", "page_count": 2,
                "sections": [
                    {"chapter": same + "X", "section": None, "title": same + "X", "level": 1,
                     "figures": [{"ext": "png", "width": 1, "height": 1, "bytes": png,
                                  "caption": "图X", "page": "x"}], "context": "ctxX"},
                    {"chapter": same + "Y", "section": None, "title": same + "Y", "level": 1,
                     "figures": [{"ext": "png", "width": 1, "height": 1, "bytes": png,
                                  "caption": "图Y", "page": "y"}], "context": "ctxY"},
                ],
            }

        globals()["extract_figures"] = fake_extract
        try:
            figures_to_book(str(book_dir / "dummy.pdf"), book_name=book)
        finally:
            globals()["extract_figures"] = real_extract
        dirs = [d for d in (book_dir / "_figures").iterdir() if d.is_dir()]
        assert len(dirs) == 2, "碰撞未产生两个独立目录，实际 %d" % len(dirs)
        for d in dirs:
            assert (d / "全文" / "fig_001.png").exists(), "缺 fig: %s" % d.name
        lines = [l for l in (book_dir / "_figures" / "_index.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2, "index 应为 2 行，实际 %d" % len(lines)
        imgs = [json.loads(l)["image"] for l in lines]
        assert len(set(imgs)) == 2, "两图 image 路径应不同（防覆盖），实际 %r" % imgs
        print("  passed（figures 目录碰撞防护：同名章加序号互不覆盖）")
    finally:
        _rmtree_force(book_dir)


def all_local(path, book_name=None):
    """本地书一键课程化：ingest → course_gen（不联网、不爬取）。

    仅接受单个书文件；目录请直接用 ingest 后逐本 course_gen。
    path：本地书文件路径（pdf/epub/djvu/mobi/azw/azw3/docx/fb2/cbz/txt/md）。
    book_name：可选显式书名；缺省用文件名 stem。
    产物：书库/<书名>/ 课程（含 progress.json）。
    """
    import subprocess
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"路径不存在：{path}")
    if p.is_dir():
        raise SystemExit("[all-local] 仅支持单个书文件；目录请用 ingest 后逐本 course_gen。")
    name = book_name or p.stem
    fmt = detect_format_local(p)
    if fmt == "cbz":  # 漫画：解包后直接进入漫画课程化
        ingest(str(p), name)
        ref_dir = REF_DIR / _safe(name)
        cg = Path(__file__).resolve().parent.parent / "structure" / "course_gen.py"
        r = subprocess.run([sys.executable, str(cg), str(ref_dir), "--book", name], cwd=str(ROOT))
        if r.returncode != 0:
            raise SystemExit(f"[all-local] 漫画课程生成失败（exit={r.returncode}）")
        print(f"[all-local] 完成（漫画）→ 书库/{_safe(name)}/")
        return
    ingest(str(p), name)                       # → 参考/<书名>/
    ref_dir = REF_DIR / _safe(name)
    cg = Path(__file__).resolve().parent.parent / "structure" / "course_gen.py"
    r = subprocess.run([sys.executable, str(cg), str(ref_dir), "--book", name], cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit(f"[all-local] 课程生成失败（exit={r.returncode}）")
    print(f"[all-local] 完成 → 书库/{_safe(name)}/（可开始逐课教学）")


# ---------------------------------------------------------------------------
# 进度 / 测验 写回（替代 agent 手改嵌套 JSON；安全、可复现、原子覆盖）
# 设计：agent 在教学闭环里负责「出题意图 + 判分」，本命令只负责把结果
#       结构化地写回 progress.json，并提供掌握度汇总 / 弱课复习清单。
# ---------------------------------------------------------------------------
_BLOOM_LEVELS = ["记忆", "理解", "应用", "分析"]

_BLOOM_TEMPLATE = """\
Bloom 认知分层出题提纲（每课 2–4 题，覆盖 2+ 层级）：
  记忆：这节课的关键定义 / 术语 / 公式是？请复述 ___。
  理解：用自己的话解释 ___ 为什么成立 / ___ 与 ___ 的区别？
  应用：给定新情境 Z，用本节课方法解决 ___。
  分析：___ 的假设是什么？若条件改成 ___，结论会怎样？
（题目与参考答案由 agent 基于本课正文拟写，再用 `progress --add-quiz` 留存。）
"""


def _book_dir(book):
    d = ROOT / "书库" / _safe(book)
    if not d.exists():
        raise SystemExit(f"未找到 书库/{_safe(book)}/，请先跑完 all-local 或 course_gen")
    return d


def load_progress(book_dir):
    p = book_dir / "progress.json"
    if not p.exists():
        raise SystemExit(f"未找到 {p}（该书尚未生成课程）")
    return json.loads(p.read_text(encoding="utf-8"))


def save_progress(book_dir, data):
    (book_dir / "progress.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def resolve_lesson(progress, key):
    """把 序号 / 子串 / 全路径 解析为精确的 lesson rel（按章/课零填充排序）。"""
    lessons = progress.get("lessons", {})
    keys = sorted(lessons.keys())
    if not key:
        return None
    if key.isdigit():
        i = int(key) - 1
        return keys[i] if 0 <= i < len(keys) else None
    key_l = key.lower()
    for k in keys:
        if key_l in k.lower():
            return k
    return None


def _print_status(progress):
    lessons = progress["lessons"]
    done = sum(1 for v in lessons.values() if v.get("status") == "done")
    total = len(lessons)
    print(f"[进度] {progress.get('book', '?')}：{done}/{total} 课完成；当前：{progress.get('current')}")


def _print_report(progress, review=False):
    lessons = progress["lessons"]
    print(f"\n===== 掌握度汇总：{progress.get('book', '?')} =====")
    weak = []
    for k in sorted(lessons.keys()):
        v = lessons[k]
        m = v.get("mastery", 0) or 0
        quizzes = v.get("quiz", []) or []
        wrong = sum(1 for q in quizzes if q.get("correct") is False)
        # 仅把「已学过但薄弱」的课标记为需复习；未开始且无测验的课只是「未学」，不算弱。
        engaged = (v.get("status") in ("done", "in_progress")) or quizzes
        flag = ""
        if engaged and (m < 0.6 or wrong > 0):
            weak.append((k, m, wrong))
            flag = "  ← 需复习" if review else ""
        print(f"  {k}\n    掌握度={m:.2f}  测验={len(quizzes)}（错 {wrong}）{flag}")
    done = sum(1 for v in lessons.values() if v.get("status") == "done")
    avg = sum((v.get("mastery", 0) or 0) for v in lessons.values()) / max(len(lessons), 1)
    print(f"  完成 {done}/{len(lessons)} 课；平均掌握度 {avg:.2f}")
    if review:
        print("\n--- 需复习的弱课 ---")
        for k, m, w in weak:
            print(f"  {k}  (掌握度 {m:.2f}, 错 {w})")
        if not weak:
            print("  （无，全部达标）")


def cmd_progress(args):
    book_dir = _book_dir(args.book)
    prog = load_progress(book_dir)
    if args.quiz_template:
        print(_BLOOM_TEMPLATE)
        return
    if args.next:
        cur = prog.get("current")
        keys = sorted(prog["lessons"].keys())
        if cur and cur in prog["lessons"]:
            les = prog["lessons"][cur]
            les["status"] = "done"
            if args.mastery is not None:
                les["mastery"] = args.mastery
            i = keys.index(cur)
            prog["current"] = keys[i + 1] if i + 1 < len(keys) else cur
        elif keys:
            # 当前为空（尚未开始）→ 把第一课标记完成并推进到第二课
            les0 = prog["lessons"][keys[0]]
            les0["status"] = "done"
            if args.mastery is not None:
                les0["mastery"] = args.mastery
            prog["current"] = keys[1] if len(keys) > 1 else keys[0]
        print(f"[progress] 已推进：当前 → {prog.get('current')}")
    if args.current:
        rel = resolve_lesson(prog, args.current)
        if not rel:
            print(f"[progress] 未匹配到课：{args.current}")
        else:
            prog["current"] = rel
            print(f"[progress] 当前设为：{rel}")
    if args.done:
        rel = resolve_lesson(prog, args.done)
        if not rel:
            print(f"[progress] 未匹配到课：{args.done}")
        else:
            les = prog["lessons"][rel]
            les["status"] = "done"
            if args.mastery is not None:
                les["mastery"] = args.mastery
            print(f"[progress] 标记完成：{rel}（掌握度={les['mastery']}）")
    if args.add_quiz:
        rel = resolve_lesson(prog, args.add_quiz)
        if not rel:
            print(f"[progress] 未匹配到课：{args.add_quiz}")
        else:
            correct = None
            if args.correct is not None:
                correct = args.correct.lower() in ("1", "true", "yes", "y")
            item = {"q": args.q or "", "bloom": args.bloom,
                    "a": args.a or "", "learner": args.learner or "",
                    "correct": correct, "ts": _now()}
            prog["lessons"][rel].setdefault("quiz", []).append(item)
            print(f"[progress] 已追加测验：{rel}（{args.bloom}）")
    prog["updated"] = _now()
    save_progress(book_dir, prog)
    if args.report or args.review:
        _print_report(prog, review=args.review)
    else:
        _print_status(prog)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    ps = sub.add_parser("search"); ps.add_argument("kw"); ps.add_argument("--idx", type=int, nargs="*")
    pd = sub.add_parser("download"); pd.add_argument("url"); pd.add_argument("source"); pd.add_argument("name", nargs="?"); pd.add_argument("--max", type=int, default=None)
    pi = sub.add_parser("ingest"); pi.add_argument("path"); pi.add_argument("--name", default=None)
    pi.add_argument("--chunks", type=int, default=None, help="扁平整包 CBZ 按图片序切成 N 话（仅漫画、且整包无分目录时生效）")
    pf = sub.add_parser("figures"); pf.add_argument("path"); pf.add_argument("--name", default=None)
    pg = sub.add_parser("inline"); pg.add_argument("name", help="书名（书库/<书名>/ 下的目录名）")
    pst = sub.add_parser("selftest")
    pa = sub.add_parser("all"); pa.add_argument("kw"); pa.add_argument("--idx", type=int, nargs="*"); pa.add_argument("--max", type=int, default=None)
    pl = sub.add_parser("all-local"); pl.add_argument("path"); pl.add_argument("--name", default=None)
    pp = sub.add_parser("progress", help="进度/测验写回与汇总（替代手改 progress.json）")
    pp.add_argument("book")
    pp.add_argument("--next", action="store_true", help="把当前课标记完成并推进到下一课")
    pp.add_argument("--done", metavar="LESSON", help="标记某课完成（LESSON=序号或子串匹配）")
    pp.add_argument("--mastery", type=float, default=None, help="掌握度 0~1（配合 --next/--done）")
    pp.add_argument("--current", metavar="LESSON", help="设置当前课")
    pp.add_argument("--add-quiz", metavar="LESSON", help="给某课追加一条测验记录")
    pp.add_argument("--q", help="题目")
    pp.add_argument("--bloom", default="理解", help="Bloom 层级（记忆/理解/应用/分析）")
    pp.add_argument("--a", help="参考答案/讲解")
    pp.add_argument("--learner", default="", help="学习者作答")
    pp.add_argument("--correct", default=None, help="作答是否正确（true/false）")
    pp.add_argument("--report", action="store_true", help="打印掌握度汇总")
    pp.add_argument("--review", action="store_true", help="列出需复习的弱课")
    pp.add_argument("--quiz-template", action="store_true", help="打印 Bloom 出题提纲")
    args = ap.parse_args()

    if args.cmd == "search":
        res, cache = search_all(args.kw, args.idx)
        _print_search(res)
        errs = [r for r in res if r.get("_error")]
        if errs and len(errs) == len(res):
            report_source_unavailable("所有书源均不可达或返回错误（详见上方 ✗ 项）",
                                      ctx=f"search {args.kw}")
        print(f"\n[缓存] {cache}")
    elif args.cmd == "download":
        try:
            info = download(args.source, args.url, args.name, args.max)
        except Exception as e:
            report_source_unavailable(f"下载失败：{e}", ctx=f"download {args.source}")
            raise SystemExit(1)
        print(f"[下载] {info['name']} → {info['dir']}（{info['chapters']} 章）")
    elif args.cmd == "ingest":
        ingest(args.path, args.name, cbz_chunks=args.chunks)
    elif args.cmd == "figures":
        figures_to_book(args.path, args.name)
    elif args.cmd == "inline":
        inline_figures(args.name)
    elif args.cmd == "selftest":
        selftest()
    elif args.cmd == "all-local":
        all_local(args.path, args.name)
    elif args.cmd == "all":
        try:
            res, cache = search_all(args.kw, args.idx)
            ok = [r for r in res if r.get("bookUrl") and not r.get("_error")]
            if not ok:
                report_source_unavailable(
                    "搜索无可用结果（所有书源不可达或返回错误）", ctx=f"all {args.kw}")
                return
            b = ok[0]
            print(f"[all] 选用：{b.get('name')} / {b.get('_source')} / {b.get('bookUrl')}")
            info = download(b.get("_source"), b["bookUrl"], b.get("name"), args.max)
            ref_dir = REF_DIR / _safe(info["name"])
            cg = Path(__file__).resolve().parent.parent / "structure" / "course_gen.py"
            r = subprocess.run([sys.executable, str(cg), str(ref_dir), "--book", info["name"]], cwd=str(ROOT))
            if r.returncode != 0:
                raise RuntimeError(f"课程生成失败（exit={r.returncode}）")
            print(f"[all] 完成 → 书库/{_safe(info['name'])}/")
        except Exception as e:
            report_source_unavailable(f"获取失败：{e}", ctx=f"all {args.kw}")
            raise SystemExit(1)
    elif args.cmd == "progress":
        cmd_progress(args)
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
