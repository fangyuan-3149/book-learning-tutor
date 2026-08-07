#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
book_formats.py — 多格式书籍 → 纯文本章节（授业格式层 v2）

把 PDF / EPUB / MOBI / DJVU / TXT / MD 抽成 (title, text) 章节列表，
写入 参考/<书名>/NNNN_title.txt，供现有 convert → course_gen 消费
（convert 契约：参考/<书名>/[0-9]{4}_*.txt 每个文件 = 一节）。

v2 相对 v1 的优化（"把格式转换做好"）：
  - PDF 无大纲时改用「字体大小 + 标题正则」启发式切章，不再退化为逐页"第N页"；
    抓不到章节标题时再退回整本按正则标题切，最后才逐页（保留旧行为）。
  - 抽出的正文统一过 _clean_book_text：全角空格→半角、折叠多余空行、
    丢弃纯页码行、跨页重复的页眉/页脚（出现于 >50% 章节的短行）。
  - 从 PDF/EPUB 元数据取 书名/作者 写入 meta，供 convert 课头与 _meta.json 使用。
  - 扫描版（文本层稀疏）仍只标 needs_ocr，不强制 OCR（重依赖留待用户本机）。

依赖（按需懒加载，缺哪个报哪个，不强制全装）：
  - pymupdf (fitz)   ：PDF / EPUB / FB2 / 图片 文本层抽取（首选，已装）
  - ebooklib         ：EPUB/MOBI 兜底（MOBI 用 ebooklib 读，文本从 HTML 抽）
  - djvulibre(djvutxt CLI) ：DJVU 兜底（PyMuPDF wheel 通常不含 djvu）
  - OCR（扫描版 PDF）：可选。检测到文本层稀疏 → 标记 needs_ocr，不强制
                       MinerU / tesseract；留给用户本机有 OCR 时再补。

用法：
  from book_formats import extract, detect_format
  r = extract("book.pdf")          # r['sections'] = [(title, text), ...]
  # 或命令行自测：
  python book_formats.py --selftest
"""
import os
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path
from collections import Counter

# 文本层稀疏判定阈值：平均每内容页字符数低于此值 → 疑似扫描版（需OCR）
SCAN_THRESHOLD = 25

# 章节标题正则（中文/英文/数字编号；命中即视作新章起点）
_HEAD_RE = re.compile(
    r"^\s*(第\s*[一二三四五六七八九十百千零0-9]+\s*[章回节部卷篇集]|"
    r"chapter\s+[0-9ivxIVX]+|"
    r"[0-9]{1,3}[\.\、]\s+\S|"
    r"序[言章]|前[言]|引[言]|附[录]|后[记]|结语|目录)\b",
    re.IGNORECASE,
)
# 纯页码行（可能带连字符/破折号包围）：- 12 - / 13 / —14—
_PAGENUM_RE = re.compile(r"^[\-–—]?\s*\d{1,4}\s*[\-–—]?$")


def detect_format(path):
    """返回 'pdf' / 'epub' / 'mobi' / 'djvu' / 'txt' / 'md' / 'unknown'。"""
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if ext in ("pdf", "epub", "mobi", "djvu", "txt", "md"):
        return ext
    # 无扩展名 / 未知 → 用 magic 兜底
    try:
        head = p.read_bytes()[:8]
    except Exception:
        return "unknown"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):  # epub/mobi 都是 zip 容器，靠扩展名区分不了
        return "unknown"
    if head.startswith(b"FORM\x00\x00\x00\x0cDJVU"):
        return "djvu"
    return "unknown"


def _safe_title(title, limit=40):
    """章节标题洗成文件名安全片段（保留中文，去掉路径危险字符）。"""
    t = re.sub(r"[\\/:*?\"<>|]", "_", str(title)).strip() or "未命名"
    t = t.replace("\n", " ").strip()
    return t[:limit]


def _needs_ocr(sections, page_count):
    """按平均每页字符数判断是否扫描版（文本层空）。"""
    if page_count <= 0:
        return False
    total = sum(len(t) for _, t in sections)
    return (total / page_count) < SCAN_THRESHOLD


def _looks_like_heading(txt, maxsz, body_size):
    """综合判断一段文本是否章节标题。"""
    if not txt or len(txt) > 60:
        return False
    if _HEAD_RE.match(txt):
        return True
    # 字体显著大于正文且较短 → 疑似标题（封面/章节大字）
    if body_size and maxsz >= body_size * 1.2 and len(txt) <= 40:
        return True
    return False


def _split_text_by_headings(text):
    """整本纯文本按标题正则切章；不足 2 个标题返回 None（交给调用方降级）。"""
    lines = text.split("\n")
    idxs = [i for i, l in enumerate(lines) if _HEAD_RE.match(l.strip())]
    if len(idxs) < 2:
        return None
    sections = []
    for j, start in enumerate(idxs):
        end = idxs[j + 1] if j + 1 < len(idxs) else len(lines)
        title = lines[start].strip()
        body = "\n".join(lines[start + 1:end]).strip()
        sections.append((title, body))
    return sections


# ---------------------------------------------------------------------------
# 文本清洗（通用，零依赖）—— 与小说章节清洗(clean.py)不同：不删"广告/版权"等
# 站点噪声词，避免误伤真实出版书的正文/版权页。
# ---------------------------------------------------------------------------
def _clean_book_text(text):
    if not text:
        return ""
    out = []
    blank = 0
    for raw in text.replace("\r\n", "\n").replace("\u3000", " ").split("\n"):
        line = " ".join(raw.split())  # 折叠行内多空格 + strip
        if not line:
            blank += 1
            if blank <= 1:  # 段落间至多留一个空行
                out.append("")
            continue
        blank = 0
        if _PAGENUM_RE.match(line):
            continue  # 丢弃纯页码行
        out.append(line)
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def _drop_running_headers(sections):
    """删跨页重复的页眉/页脚：出现于 >50% 章节、且长度<=40 的短行。"""
    if len(sections) < 3:
        return sections
    # 先收集所有"短行"
    shorts = set()
    for _, txt in sections:
        for ln in txt.split("\n"):
            s = ln.strip()
            if s and len(s) <= 40:
                shorts.add(s)
    # 统计每个短行出现在多少章节
    appear = Counter()
    for _, txt in sections:
        present = set()
        for ln in txt.split("\n"):
            s = ln.strip()
            if s in shorts:
                present.add(s)
        for s in present:
            appear[s] += 1
    threshold = max(3, int(0.5 * len(sections)))
    drop = {s for s, c in appear.items() if c >= threshold}
    if not drop:
        return sections
    out = []
    for title, txt in sections:
        kept = [ln for ln in txt.split("\n") if ln.strip() not in drop]
        out.append((title, "\n".join(kept)))
    return out


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_meta(doc):
    m = getattr(doc, "metadata", None) or {}
    return {
        "title": (m.get("title") or "").strip(),
        "author": (m.get("author") or "").strip(),
    }


def _pdf_sections(path):
    import pymupdf as fitz
    import statistics
    doc = fitz.open(path)
    n = doc.page_count
    meta = _pdf_meta(doc)
    toc = doc.get_toc()  # [[level, title, page(1-based)], ...]
    if toc:
        sections = []
        for i, (lvl, title, page) in enumerate(toc):
            start = max(0, page - 1)
            end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n - 1
            end = max(end, start)
            txt = "".join(doc[p].get_text("text") for p in range(start, end + 1))
            sections.append((title, txt))
        doc.close()
        return sections, n, meta

    # 无大纲 → 字体大小 + 标题正则 启发式
    body_sizes = []
    for p in range(n):
        d = doc[p].get_text("dict")
        for b in d.get("blocks", []):
            for ln in b.get("lines", []):
                for sp in ln.get("spans", []):
                    if sp.get("text", "").strip():
                        body_sizes.append(sp.get("size", 0))
    body_size = statistics.median(body_sizes) if body_sizes else 0

    headings = []  # (page_index_0based, title)
    for p in range(n):
        d = doc[p].get_text("dict")
        for b in d.get("blocks", []):
            txt = " ".join(
                sp.get("text", "") for ln in b.get("lines", [])
                for sp in ln.get("spans", [])
            ).strip()
            if not txt:
                continue
            sizes = [
                sp.get("size", 0) for ln in b.get("lines", [])
                for sp in ln.get("spans", []) if sp.get("text", "").strip()
            ]
            maxsz = max(sizes) if sizes else 0
            if _looks_like_heading(txt, maxsz, body_size):
                # 仅去重「同页同标题」（目录页重复）；跨页同标题的不同章保留
                if not headings or not (headings[-1][0] == p and headings[-1][1] == txt):
                    headings.append((p, txt))
    if headings:
        sections = []
        for i, (pg, title) in enumerate(headings):
            end = headings[i + 1][0] if i + 1 < len(headings) else n - 1
            txt = "\n".join(doc[p].get_text("text") for p in range(pg, end + 1))
            sections.append((title, txt))
        doc.close()
        return sections, n, meta

    # 字体检测无果 → 整本拼接按标题正则切
    full = "\n".join(doc[p].get_text("text") for p in range(n))
    sub = _split_text_by_headings(full)
    if sub:
        doc.close()
        return sub, n, meta

    # 完全无结构 → 逐页（保留旧行为）
    sections = [(f"第{p + 1}页", doc[p].get_text("text")) for p in range(n)]
    doc.close()
    return sections, n, meta


# ---------------------------------------------------------------------------
# EPUB（pymupdf 优先；失败回退 ebooklib）
# ---------------------------------------------------------------------------
def _epub_sections(path):
    try:
        import pymupdf as fitz
        doc = fitz.open(path)
        n = doc.page_count
        meta = _pdf_meta(doc)
        toc = doc.get_toc()
        if toc:
            sections = []
            for i, (lvl, title, page) in enumerate(toc):
                start = max(0, page - 1)
                end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n - 1
                end = max(end, start)
                txt = "".join(doc[p].get_text("text") for p in range(start, end + 1))
                sections.append((title, txt))
            doc.close()
            return sections, n, meta
        # 无大纲 → 逐文档，再按标题正则切
        full = "\n".join(doc[p].get_text("text") for p in range(n))
        doc.close()
        sub = _split_text_by_headings(full)
        if sub:
            return sub, n, meta
        # 退化：整本一段
        return [("全文", full)], n, meta
    except Exception:
        pass
    # 回退：ebooklib
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except Exception as e:
        raise RuntimeError("EPUB 抽取需 pymupdf 或 ebooklib+bs4，均缺失：%s" % e)
    book = epub.read_epub(path)
    meta = {}
    try:
        t = book.get_metadata("DC", "title")
        a = book.get_metadata("DC", "creator")
        if t:
            meta["title"] = t[0][0].strip()
        if a:
            meta["author"] = a[0][0].strip()
    except Exception:
        pass
    sections = []
    idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        idx += 1
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        txt = soup.get_text("\n")
        txt = "\n".join(ln.strip() for ln in txt.splitlines() if ln.strip())
        # 单文档内若含多章，按标题正则再切
        sub = _split_text_by_headings(txt)
        if sub:
            sections.extend(sub)
        else:
            sections.append((f"第{idx}节", txt))
    return sections, idx, meta


# ---------------------------------------------------------------------------
# DJVU（pymupdf 优先；否则 djvutxt CLI；再否则报错）
# ---------------------------------------------------------------------------
def _djvu_sections(path):
    # 1) 试试 pymupdf（部分构建带 djvu）
    try:
        import pymupdf as fitz
        doc = fitz.open(path)
        if doc.page_count > 0:
            n = doc.page_count
            meta = _pdf_meta(doc)
            toc = doc.get_toc()
            if toc:
                sections = []
                for i, (lvl, title, page) in enumerate(toc):
                    start = max(0, page - 1)
                    end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n - 1
                    end = max(end, start)
                    txt = "".join(doc[p].get_text("text") for p in range(start, end + 1))
                    sections.append((title, txt))
                doc.close()
                return sections, n, meta
            sections = [(f"第{p + 1}页", doc[p].get_text("text")) for p in range(n)]
            doc.close()
            return sections, n, meta
    except Exception:
        pass
    # 2) djvulibre 的 djvutxt CLI
    djvutxt = shutil.which("djvutxt") or shutil.which("djvutxt.exe")
    if djvutxt:
        try:
            out = subprocess.run([djvutxt, path], capture_output=True, text=True, timeout=120)
            txt = out.stdout or ""
        except Exception as e:
            raise RuntimeError("djvutxt 执行失败：%s" % e)
        # 全本一段（djvu 分页文本难拆，v1 整本一节；后续可按页 djvutxt --page 细化）
        return [(os.path.splitext(os.path.basename(path))[0] or "全文", txt)], 1, {}
    raise RuntimeError(
        "DJVU 抽取失败：当前环境 PyMuPDF 未带 djvu 支持，且未装 djvulibre(djvutxt)。"
        "安装 djvulibre 后重试，或改用 PDF/EPUB。")


# ---------------------------------------------------------------------------
# TXT / MD（直达，无需解析）
# ---------------------------------------------------------------------------
def _text_sections(path, is_md=False):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    if is_md:
        # md 含多个 '# ' 一级标题则按章切，否则整本
        heads = re.findall(r"(?m)^#\s+(.+)$", raw)
        if len(heads) >= 2:
            parts = re.split(r"(?m)^#\s+", raw)
            sections = []
            for i, seg in enumerate(parts[1:], 1):
                title = seg.splitlines()[0].strip() if seg.strip() else f"第{i}章"
                sections.append((title, seg))
            return sections, len(sections), {}
    title = os.path.splitext(os.path.basename(path))[0]
    return [(title, raw)], 1, {}


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def extract(path, fmt=None):
    """抽取一本书为章节列表。

    返回 dict：
      {
        'fmt': str, 'page_count': int, 'needs_ocr': bool,
        'sections': [(title, text), ...],   # text 已清洗
        'meta': {'name','source','title','author', ...}
      }
    异常：格式不支持 / 依赖缺失 → RuntimeError（带可操作提示）。
    """
    path = str(path)
    if not os.path.exists(path):
        raise RuntimeError(f"文件不存在：{path}")
    fmt = fmt or detect_format(path)
    meta0 = {}
    if fmt == "pdf":
        sections, n, meta0 = _pdf_sections(path)
    elif fmt == "epub":
        sections, n, meta0 = _epub_sections(path)
    elif fmt == "djvu":
        sections, n, meta0 = _djvu_sections(path)
    elif fmt == "txt":
        sections, n, meta0 = _text_sections(path, is_md=False)
    elif fmt == "md":
        sections, n, meta0 = _text_sections(path, is_md=True)
    elif fmt == "mobi":
        raise RuntimeError(
            "MOBI 暂不直接支持。请用 calibre 转成 EPUB 后再 ingest：\n"
            "  ebook-convert book.mobi book.epub")
    else:
        raise RuntimeError(
            f"不支持的格式：{fmt}（{path}）。支持 pdf/epub/djvu/txt/md；MOBI 请先转 EPUB。")

    # 清洗：通用书本清洗 + 去跨页页眉页脚
    clean = [(t, _clean_book_text(x)) for t, x in sections]
    clean = _drop_running_headers(clean)
    needs_ocr = _needs_ocr(clean, n) if fmt in ("pdf", "djvu", "epub") else False
    meta = {"name": os.path.splitext(os.path.basename(path))[0], "source": "local-file"}
    meta.update({k: v for k, v in meta0.items() if v})
    return {
        "fmt": fmt,
        "page_count": n,
        "needs_ocr": needs_ocr,
        "sections": clean,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def selftest():
    print("[book_formats selftest]")
    try:
        import pymupdf as fitz
    except Exception as e:
        print("   skipped: pymupdf 缺失（%s）" % e)
        return
    import tempfile
    import statistics

    # --- 用例1：带大纲的 PDF → 按大纲拆 2 章 ---
    d = fitz.open()
    for i in range(3):
        pg = d.new_page()
        pg.insert_text((72, 72), f"这是第 {i + 1} 页的示例正文。")
    d.set_toc([(1, "第一章 示例", 1), (1, "第二章 示例", 2)])
    fd, pdf1 = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    d.save(pdf1)
    d.close()
    r = extract(pdf1)
    assert r["fmt"] == "pdf" and r["page_count"] == 3
    assert len(r["sections"]) == 2, "大纲应拆成 2 章"
    assert "第一章" in r["sections"][0][0] and "第二章" in r["sections"][1][0]
    os.unlink(pdf1)

    # --- 用例2：无大纲，但含大字"Chapter N"标题 → 启发式切 2 章 ---
    # （用拉丁文本：base14 字体可真实抽取，避免 CJK tofu 导致标题相同被误并）
    d = fitz.open()
    p1 = d.new_page()
    p1.insert_text((72, 60), "Chapter 1 The Beginning", fontsize=18)
    p1.insert_text((72, 90), "The boy stood in the courtyard, looking up at the sky.", fontsize=11)
    p2 = d.new_page()
    p2.insert_text((72, 60), "Chapter 2 The Encounter", fontsize=18)
    p2.insert_text((72, 90), "From now on, the youth called a waste would cease to be.", fontsize=11)
    p3 = d.new_page()
    p3.insert_text((72, 90), "Night deepened, and the city lights came on one by one.", fontsize=11)
    fd, pdf2 = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    d.save(pdf2)
    d.close()
    r = extract(pdf2)
    assert r["fmt"] == "pdf"
    assert len(r["sections"]) >= 2, "无大纲应靠标题启发式切出 >=2 章，实际 %d" % len(r["sections"])
    titles = " ".join(t for t, _ in r["sections"])
    assert "Chapter 1" in titles and "Chapter 2" in titles, "章节标题未被识别：%s" % titles
    # 正文清洗：不应含纯页码行/多余空行
    for _, x in r["sections"]:
        assert "\n\n\n" not in x, "清洗未折叠空行"
    os.unlink(pdf2)

    # --- 用例3：扫描版（文本层空）→ needs_ocr=True ---
    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((72, 72), " ")  # 几乎无文本
    fd, pdf3 = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    d.save(pdf3)
    d.close()
    r = extract(pdf3)
    assert r["needs_ocr"] is True, "文本层空应标 needs_ocr"
    os.unlink(pdf3)

    print("  selftest passed（大纲切分 / 标题启发式切分 / 扫描版标记 / 清洗）。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        # 简易 CLI：python book_formats.py <file> → 打印章节数 + 前 200 字
        if len(sys.argv) < 2:
            print("usage: python book_formats.py <file> [--selftest]")
            sys.exit(1)
        r = extract(sys.argv[1])
        print(f"fmt={r['fmt']} pages={r['page_count']} sections={len(r['sections'])} needs_ocr={r['needs_ocr']} meta={r['meta']}")
        for i, (t, x) in enumerate(r["sections"][:3], 1):
            print(f"--- [{i}] {t} ({len(x)} chars) ---\n{x[:200]}")
