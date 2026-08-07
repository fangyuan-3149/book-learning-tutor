#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
book_formats.py — 多格式书籍 → 纯文本章节（授业格式层 v1）

把 PDF / EPUB / MOBI / DJVU / TXT / MD 抽成 (title, text) 章节列表，
写入 参考/<书名>/NNNN_title.txt，供现有 convert → course_gen 消费
（convert 契约：参考/<书名>/[0-9]{4}_*.txt 每个文件 = 一节）。

为什么需要它：
  原管道只能吃「纯文本章节 txt」。但真实书籍（尤其公版/图书馆扫描/
  Z-Library 之类）主体是 PDF / EPUB / DJVU。没有这层，只有 txt 能翻，
  与"项目要积累各类网站"的目标直接冲突。本层补上格式缺口。

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

# 文本层稀疏判定阈值：平均每内容页字符数低于此值 → 疑似扫描版（需OCR）
SCAN_THRESHOLD = 25


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


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_sections(path):
    import pymupdf as fitz  # 懒加载
    doc = fitz.open(path)
    n = doc.page_count
    toc = doc.get_toc()  # [[level, title, page(1-based)], ...]
    sections = []
    if toc:
        for i, (lvl, title, page) in enumerate(toc):
            start = max(0, page - 1)
            end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n
            end = max(end, start)
            txt = "".join(doc[p].get_text("text") for p in range(start, end))
            sections.append((title, txt))
    else:
        # 无大纲 → 逐页（避免把整本塞一节，让 course_gen 有分节可吃）
        for p in range(n):
            sections.append((f"第{p + 1}页", doc[p].get_text("text")))
    doc.close()
    return sections, n


# ---------------------------------------------------------------------------
# EPUB（pymupdf 优先；失败回退 ebooklib）
# ---------------------------------------------------------------------------
def _epub_sections(path):
    try:
        import pymupdf as fitz
        doc = fitz.open(path)
        n = doc.page_count
        toc = doc.get_toc()
        sections = []
        if toc:
            for i, (lvl, title, page) in enumerate(toc):
                start = max(0, page - 1)
                end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n
                end = max(end, start)
                txt = "".join(doc[p].get_text("text") for p in range(start, end))
                sections.append((title, txt))
        else:
            for p in range(n):
                sections.append((f"第{p + 1}节", doc[p].get_text("text")))
        doc.close()
        return sections, n
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
    sections = []
    idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        idx += 1
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        txt = soup.get_text("\n")
        txt = "\n".join(ln.strip() for ln in txt.splitlines() if ln.strip())
        sections.append((f"第{idx}节", txt))
    return sections, idx


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
            toc = doc.get_toc()
            sections = []
            if toc:
                for i, (lvl, title, page) in enumerate(toc):
                    start = max(0, page - 1)
                    end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n
                    end = max(end, start)
                    txt = "".join(doc[p].get_text("text") for p in range(start, end))
                    sections.append((title, txt))
            else:
                for p in range(n):
                    sections.append((f"第{p + 1}页", doc[p].get_text("text")))
            doc.close()
            return sections, n
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
        return [(os.path.splitext(os.path.basename(path))[0] or "全文", txt)], 1
    raise RuntimeError(
        "DJVU 抽取失败：当前环境 PyMuPDF 未带 djvu 支持，且未装 djvulibre(djvutxt)。"
        "安装 djvulibre 后重试，或改用 PDF/EPUB。")


# ---------------------------------------------------------------------------
# TXT / MD（直达，无需解析）
# ---------------------------------------------------------------------------
def _text_sections(path, is_md=False):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    if is_md:
        # md 直接整本一节（保留原结构交给 convert）；或按 '#' 切分
        # v1：若含 '# ' 一级标题则按章切，否则整本
        heads = re.findall(r"(?m)^#\s+(.+)$", raw)
        if len(heads) >= 2:
            parts = re.split(r"(?m)^#\s+", raw)
            sections = []
            for i, seg in enumerate(parts[1:], 1):
                title = seg.splitlines()[0].strip() if seg.strip() else f"第{i}章"
                sections.append((title, seg))
            return sections, len(sections)
    title = os.path.splitext(os.path.basename(path))[0]
    return [(title, raw)], 1


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def extract(path, fmt=None):
    """抽取一本书为章节列表。

    返回 dict：
      {
        'fmt': str, 'page_count': int, 'needs_ocr': bool,
        'sections': [(title, text), ...],   # text 已去多余空白
        'meta': {...}
      }
    异常：格式不支持 / 依赖缺失 → RuntimeError（带可操作提示）。
    """
    path = str(path)
    if not os.path.exists(path):
        raise RuntimeError(f"文件不存在：{path}")
    fmt = fmt or detect_format(path)
    if fmt == "pdf":
        sections, n = _pdf_sections(path)
    elif fmt == "epub":
        sections, n = _epub_sections(path)
    elif fmt == "djvu":
        sections, n = _djvu_sections(path)
    elif fmt == "txt":
        sections, n = _text_sections(path, is_md=False)
    elif fmt == "md":
        sections, n = _text_sections(path, is_md=True)
    elif fmt == "mobi":
        raise RuntimeError(
            "MOBI 暂不直接支持。请用 calibre 转成 EPUB 后再 ingest：\n"
            "  ebook-convert book.mobi book.epub")
    else:
        raise RuntimeError(
            f"不支持的格式：{fmt}（{path}）。支持 pdf/epub/djvu/txt/md；MOBI 请先转 EPUB。")

    # 清洗：去折叠空白
    clean = []
    for title, txt in sections:
        txt = re.sub(r"\n{3,}", "\n\n", (txt or "").strip())
        clean.append((title, txt))
    needs_ocr = _needs_ocr(clean, n) if fmt in ("pdf", "djvu", "epub") else False
    return {
        "fmt": fmt,
        "page_count": n,
        "needs_ocr": needs_ocr,
        "sections": clean,
        "meta": {"name": os.path.splitext(os.path.basename(path))[0], "source": "local-file"},
    }


# ---------------------------------------------------------------------------
# 自测：用 pymupdf 造一个带大纲的 2 章 PDF，验证抽取
# ---------------------------------------------------------------------------
def selftest():
    print("[book_formats selftest]")
    try:
        import pymupdf as fitz
    except Exception as e:
        print("   skipped: pymupdf 缺失（%s）" % e)
        return
    import tempfile
    # 造 PDF：3 页，含大纲 第1章(页1) / 第2章(页2-3)
    d = fitz.open()
    for i in range(3):
        pg = d.new_page()
        pg.insert_text((72, 72), f"这是第 {i+1} 页的示例正文。")
    d.set_toc([(1, "第一章 示例", 1), (1, "第二章 示例", 2)])
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")  # Windows 需先关 fd 再 save
    os.close(fd)
    d.save(pdf_path)
    d.close()
    r = extract(pdf_path)
    print(f"  fmt={r['fmt']} pages={r['page_count']} sections={len(r['sections'])} needs_ocr={r['needs_ocr']}")
    assert r["fmt"] == "pdf"
    assert r["page_count"] == 3
    assert len(r["sections"]) == 2, "大纲应拆成 2 章"
    assert "第一章" in r["sections"][0][0]
    assert "第二章" in r["sections"][1][0]
    os.unlink(pdf_path)
    print("  selftest passed.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        # 简易 CLI：python book_formats.py <file> → 打印章节数 + 前 200 字
        if len(sys.argv) < 2:
            print("usage: python book_formats.py <file> [--selftest]")
            sys.exit(1)
        r = extract(sys.argv[1])
        print(f"fmt={r['fmt']} pages={r['page_count']} sections={len(r['sections'])} needs_ocr={r['needs_ocr']}")
        for i, (t, x) in enumerate(r["sections"][:3], 1):
            print(f"--- [{i}] {t} ({len(x)} chars) ---\n{x[:200]}")
