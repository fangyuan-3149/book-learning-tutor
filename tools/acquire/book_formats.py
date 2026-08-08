#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
book_formats.py — 多格式书籍 → 纯文本「章/节」层级（授业格式层 v4）

把 PDF / EPUB / MOBI / AZW / AZW3 / DJVU / DOCX / TXT / MD 抽成
「章 → 节」两层结构的章节，写入 参考/<书名>/NNNN_title.txt（每节一个文件）
+ 参考/<书名>/_sections.json（章/节分组清单），供 convert → course_gen 消费。

v4（"小说章没区分 / 嵌套错误"修复）核心变化：
  - extract 不再产出扁平 (title, text)，而是 (chapter, section, text) 三层信息：
      * 小说：每「章」就是最小单位 → section=None，每章 = 一课（不往里塞节）。
      * 课文：每「节」是最小单位，挂在所属的「章」下 → chapter=章名, section=节名。
  - 新增 _split_hierarchical：整本文本按「章正则 + 节正则」两层切，章内再切节；
    章起点 = 第X章/回/卷/篇 + Chapter N + 数字编号 + 序/前言/附录；
    节起点 = 第X节/课 + Section N + X.Y 编号。
  - PDF/EPUB/MOBI/DOCX/TXT 全部改为返回 (chapter, section, text)，并加「防御性
    re-split」：任一段正文里若还嵌着章起点，就地再切，杜绝"一个章文件夹下塞好几章"。
  - 扫描版仍标 needs_ocr；新增可插拔 OCR 钩子（ocr.py）：有 tesseract / MinerU /
    Nougat 后端时自动识别，否则保留标记 + 清晰提示（不捆绑重型模型）。

下游契约（convert 消费）：
  - 参考/<书名>/NNNN_title.txt：每「节」一个文件（小说每章一个）。
  - 参考/<书名>/_sections.json：[{"chapter","section","title","file"}, ...] 顺序清单；
    缺该清单时 convert 退化为「每 txt=一章」（兼容下载/旧目录）。

依赖（按需懒加载，缺哪个报哪个，不强制全装）：
  - pymupdf (fitz)   ：PDF / EPUB / DJVU / 图片 文本层抽取（首选，已装）
  - ebooklib         ：EPUB 兜底解析
  - python-docx      ：DOCX 读取（标题/表格/元数据），已装
  - mobi (0.4.1)     ：MOBI/AZW/AZW3 解包为 HTML，已装
  - beautifulsoup4   ：EPUB/MOBI 的 HTML 清洗，已装
  - djvulibre(djvutxt CLI) ：DJVU 兜底（PyMuPDF wheel 通常不含 djvu）；
                        _djvu_sections 优先找 项目/vendor/djvulibre/，再 PATH
  - OCR（扫描版 PDF）：可选。ocr.py 提供 tesseract（本地轻量）/ MinerU / Nougat
                        （输出 md 直接，理想）后端；均无则标 needs_ocr 不强制。

用法：
  from book_formats import extract, detect_format
  r = extract("book.pdf")          # r['sections'] = [{'chapter','section','title','text'}, ...]
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

# 章起点正则（中文/英文/数字编号；命中即视作新章起点）
_HEAD_RE = re.compile(
    r"^\s*(第\s*[一二三四五六七八九十百千零0-9]+\s*[章回节部卷篇集]|"
    r"chapter\s+[0-9ivxIVX]+|"
    r"[0-9]{1,3}[\.\、]\s+\S|"
    r"序[言章]|前[言]|引[言]|附[录]|后[记]|结语)\b",
    re.IGNORECASE,
)
# 节起点正则（章之下的细分；课文用得多，小说一般没有）
_SECTION_RE = re.compile(
    r"^\s*(第\s*[一二三四五六七八九十百千零0-9]+\s*[节课部分段篇]|"
    r"section\s+[0-9ivxIVX]+|"
    r"[0-9]{1,3}\.[0-9]+\s+\S)\b",
    re.IGNORECASE,
)
# 纯页码行（可能带连字符/破折号包围）：- 12 - / 13 / —14—
_PAGENUM_RE = re.compile(r"^[\-–—]?\s*\d{1,4}\s*[\-–—]?$")
# 非章起点（目录/Contents 这类占位标题，不应单独成章）
_NONCHAPTER_RE = re.compile(r"^(目\s*录|contents?|index)$", re.IGNORECASE)


def detect_format(path):
    """返回 'pdf' / 'epub' / 'mobi' / 'azw' / 'azw3' / 'djvu' / 'docx' /
    'txt' / 'md' / 'unknown'。"""
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if ext in ("pdf", "epub", "mobi", "azw", "azw3", "djvu", "docx", "txt", "md"):
        return ext
    try:
        head = p.read_bytes()[:8]
    except Exception:
        return "unknown"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):  # epub/mobi/azw 都是 zip 容器，靠扩展名区分
        return "unknown"
    if head.startswith(b"FORM\x00\x00\x00\x0cDJVU"):
        return "djvu"
    return "unknown"


def _safe_title(title, limit=40):
    """章节标题洗成文件名安全片段（保留中文，去掉路径危险字符）。"""
    t = re.sub(r"[\\/:*?\"<>|]", "_", str(title)).strip() or "未命名"
    t = t.replace("\n", " ").strip()
    return t[:limit]


def _strip_num_prefix(title):
    """去掉标题首部『第N章/节/课』编号词（convert 输出 md 用，避免与 course_gen
    自动加的 第XX章 前缀重复）。"""
    return re.sub(r"^第[0-9零一二三四五六七八九十百千]+\s*[章章节节节课部分段篇]\s*",
                  "", (title or "")).strip()


_CJK_RE = re.compile(r"[㐀-鿿一-鿿豈-﫿]")


def _is_cjk(ch):
    return bool(_CJK_RE.match(ch)) if ch else False


def _collapse_cjk_spacing(title):
    """折叠 PDF 大纲书签里常见的『字距』空格（如 '数 字 计 算'→'数字计算'、
    '版 权 声 明'→'版权声明'、'前    言'→'前言'）。

    判定：删除两个 CJK 字符之间的空格，当且仅当该空格两侧的字符中**至少一个**的
    另一侧也是空格/边界（即处于"逐字隔开"的字距串中）。这样只吃字距，保留合法的
    单空格（如 '第一节 自然数' 中 节↔自 之间的空格，其两侧字符的另一侧都是正常
    汉字，不会被吃）。不改变语义、不破坏 '第N章' 与正文的间隔。
    """
    if not title:
        return title
    # 先把 2+ 连续空白折叠成单个空格（'前    言'→'前 言'，'定  义  类'→'定 义 类'），
    # 否则双空格会让下方字距判定漏掉中间的空格。
    title = re.sub(r"\s{2,}", " ", title)
    chars = list(title)
    n = len(chars)
    out = []
    for i, ch in enumerate(chars):
        if ch.isspace() and 0 < i < n - 1:
            prev, nxt = chars[i - 1], chars[i + 1]
            if _is_cjk(prev) and _is_cjk(nxt):
                left_ok = (i - 2 < 0) or chars[i - 2].isspace()
                right_ok = (i + 2 >= n) or chars[i + 2].isspace()
                if left_ok or right_ok:
                    continue  # 删掉这个字距空格
        out.append(ch)
    return "".join(out)


def _loose_sig(s):
    """章名/页眉的宽松签名：仅留 CJK 与字母，去空格/标点/数字（章号、页码），
    并折叠连续重复汉字（该教材 PDF 页眉有双倍渲染伪影 '第第章章…'）。用于判定
    一页最顶端的块是否为『章名页眉』（其签名应等于当前章名签名）。"""
    if not s:
        return ""
    s = re.sub(r"[^㐀-鿿A-Za-z]", "", s)
    s = re.sub(r"([㐀-鿿])\1+", r"\1", s)
    return s


def _page_text_clean(doc, p, norms=None, exclude=None):
    """单页文本抽取（dict 模式，按位置重建段落），并剔除最顶/最底端的章级页眉/页脚块。

    该教材 PDF 的章名页眉/页脚固定在每页顶/底端，且渲染异常（text 模式会被逐字拆行/
    双倍化成 '第/章/计/算…' 或 '第第章章…'），故改用 dict 按位置取块；其签名若落在
    norms（仅 level-1 章/前言/目录等章级标题签名，不含 '学习目标' 等小节）且不在
    exclude（当前小节自身标题，避免误删课的正文起始）即判定为页眉/页脚并丢弃。
    无大纲路径传 norms=None 则不剔除。返回与 get_text('text') 近似的段落文本。

    注：双倍渲染伪影（如附录A 页眉 '录AA PPyytthhoonn 快' 被拆成 附/附录/…/考 多个
    超短碎块）中，'附录/快速/…' 等可被精确签名命中；孤立单字 '附'/'考' 经 _is_runner
    的单字子集兜底消除。仅 '录AA PPyytthhoonn 快' 整块（字母噪音叠加）仍可能残留，属无害极端伪影。
    """
    norms = norms or set()
    exclude = exclude or set()
    d = doc[p].get_text("dict")
    blocks = []
    for b in d.get("blocks", []):
        if "lines" not in b:
            continue
        lines = []
        for ln in b.get("lines", []):
            line = "".join(sp.get("text", "") for sp in ln.get("spans", []))
            lines.append(line)
        text = "\n".join(lines).strip()
        if not text:
            continue
        blocks.append((b["bbox"][1], b["bbox"][0], text))
    blocks.sort(key=lambda x: (x[0], x[1]))

    def _is_runner(sig):
        """边缘块是否为章级运行页眉/页脚（精确签名匹配；不含章节标题/正文，避免误删）。

        注：章节起始页的大标题（含双倍渲染伪影，如附录A 的 '附录A Python快速参考' 被
        拆成 附/附录/录AA…/考 多行）位于内容区（top≈14%）而非页面边缘，且 convert 已以
        '# 章名' 形式提供干净标题，故作为无害冗余保留，不作页眉剥离——强行剥离需识别
        '双倍渲染标题'，易误删正常章节标题。
        """
        if not sig or sig in exclude:
            return False
        if sig in norms:
            return True
        if re.match(r"^\s*\d+\s*$", sig):
            return True
        return False

    # 连续剥离顶端/底端运行页眉/页脚（首个非 runner 即停，避免跨正文误删）
    while blocks and _is_runner(_loose_sig(blocks[0][2])):
        blocks.pop(0)
    while blocks and _is_runner(_loose_sig(blocks[-1][2])):
        blocks.pop(-1)
    return "\n\n".join(t for _, _, t in blocks)


def _needs_ocr(sections, page_count):
    if page_count <= 0:
        return False
    total = sum(len(t) for s in sections for t in [s["text"]])
    return (total / page_count) < SCAN_THRESHOLD


def _looks_like_heading(txt, maxsz, body_size):
    """综合判断一段文本是否章节标题。"""
    if not txt or len(txt) > 60:
        return False
    if _HEAD_RE.match(txt):
        return True
    if body_size and maxsz >= body_size * 1.2 and len(txt) <= 40:
        return True
    return False


# ---------------------------------------------------------------------------
# 两层切分：章 → 节
# ---------------------------------------------------------------------------
def _split_hierarchical(text):
    """整本纯文本按「章 → 节」两层切分。

    返回 [(chapter, section, text), ...]；无章起点返回 None。
    - 章起点 = _HEAD_RE；节起点 = _SECTION_RE。
    - 一个章内若无节起点 → (chapter, None, body)（小说：章即最小单位）。
    - 有节起点 → 每个 (chapter, section, body)（课文：节是最小单位）。
    - 目录/Contents 之类的占位标题不当章；正文过短的疑似 TOC 项丢弃。
    """
    lines = text.split("\n")
    chap_idxs = [i for i, l in enumerate(lines) if _HEAD_RE.match(l.strip())
                 and not _NONCHAPTER_RE.match(l.strip())]
    if not chap_idxs:
        return None
    triples = []
    for j, cstart in enumerate(chap_idxs):
        cend = chap_idxs[j + 1] if j + 1 < len(chap_idxs) else len(lines)
        chapter_title = lines[cstart].strip()
        cbody_lines = lines[cstart + 1:cend]
        sec_idxs = [k for k, l in enumerate(cbody_lines) if _SECTION_RE.match(l.strip())]
        if not sec_idxs:
            body = "\n".join(cbody_lines).strip()
            triples.append((chapter_title, None, body))
        else:
            for si in range(len(sec_idxs)):
                sstart = sec_idxs[si]
                send = sec_idxs[si + 1] if si + 1 < len(sec_idxs) else len(cbody_lines)
                sec_title = cbody_lines[sstart].strip()
                sec_body = "\n".join(cbody_lines[sstart + 1:send]).strip()
                triples.append((chapter_title, sec_title, sec_body))
    return _clean_triples(triples)


def _clean_triples(triples):
    out = [(c, s, t) for (c, s, t) in triples if t.strip()]
    return _drop_toc_like_triples(out) if out else triples


def _drop_toc_like_triples(triples):
    """丢弃『正文过短』的疑似目录(TOC)/许可证样板项（同 _drop_toc_like_sections）。"""
    import statistics
    if len(triples) < 3:
        return triples
    bodies = [len(t) for _, _, t in triples]
    med = statistics.median(bodies) if bodies else 0
    thr = max(200, int(0.02 * med)) if med > 0 else 200
    out = [(c, s, t) for (c, s, t) in triples if len(t) >= thr]
    return out if out else triples


def _drop_empty_sections(sections):
    """丢弃空正文章节（多为 EPUB/MOBI 的目录 TOC 占位项），保留 >=1 个。"""
    out = [(t, x) for t, x in sections if x.strip()]
    return out if out else sections


def _drop_toc_like_sections(sections):
    """丢弃"正文过短"的疑似目录(TOC)/许可证样板项（兼容旧调用）。"""
    import statistics
    if len(sections) < 3:
        return sections
    bodies = [len(x) for _, x in sections]
    med = statistics.median(bodies) if bodies else 0
    thr = max(200, int(0.02 * med)) if med > 0 else 200
    out = [(t, x) for t, x in sections if len(x) >= thr]
    return out if out else sections


def _resplit_embedded(triples):
    """防御性 re-split：任一段正文里若还嵌着章起点，就地再切，
    杜绝「一个章文件夹下塞好几章」（PDF 大纲过粗 / 启发式漏切时兜底）。"""
    out = []
    changed = False
    for (chapter, section, text) in triples:
        sub = _split_hierarchical(text)
        if sub and len(sub) > 1:
            changed = True
            # 用 sub 的章替换（保留外层章作为优先；sub 章若是 None 退回外层章）
            for (c2, s2, t2) in sub:
                out.append((c2 or chapter, s2, t2))
        else:
            out.append((chapter, section, text))
    return out if changed else triples


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
    shorts = set()
    for sec in sections:
        for ln in sec["text"].split("\n"):
            s = ln.strip()
            if s and len(s) <= 40:
                shorts.add(s)
    appear = Counter()
    for sec in sections:
        present = set()
        for ln in sec["text"].split("\n"):
            s = ln.strip()
            if s in shorts:
                present.add(s)
        for s in present:
            appear[s] += 1
    threshold = max(3, int(0.5 * len(sections)))
    drop = {s for s, c in appear.items() if c >= threshold}
    if not drop:
        return sections
    for sec in sections:
        kept = [ln for ln in sec["text"].split("\n") if ln.strip() not in drop]
        sec["text"] = "\n".join(kept)
    return sections


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_meta(doc):
    m = getattr(doc, "metadata", None) or {}
    return {
        "title": (m.get("title") or "").strip(),
        "author": (m.get("author") or "").strip(),
    }


def _outline_to_triples(toc, doc, n):
    """PDF 大纲 → (chapter, section, text)。lvl<=1 视为章，>=2 视为节（挂当前章）。

    设计铁律：**完全信任大纲**，绝不对 TOC 派生出的正文再跑 _split_hierarchical /
    _resplit_embedded 二次切分。否则 PDF 每页页眉（"第5章 ……81" 带引导点页码、字距
    拉开的 "判 断 结 构"）、代码清单标题（"# File: chaos.py"）会被当成"章/节"切出，
    污染章名并产生大量垃圾章——实测某教材 21 个真实章被炸成 753 章、章名还混进页眉
    字距版与引导点页码。

    每个 TOC 条目独占一段正文（start→下一条目页之前），章=level<=1，节=level>=2
    （统一挂到最近一个 level<=1 章名下）。章自身正文即"章首到第一节之前"的引子，
    不重复子节内容。无大纲的兜底路径（_pdf_sections 下方）仍保留 _split_hierarchical。
    """
    # 收集所有 level-1 章级标题签名（运行页眉/页脚都是章级标签，不含『学习目标』等小节）
    chapter_norms = set()
    for (lvl, title, _) in toc:
        if lvl <= 1:
            s = _loose_sig(_collapse_cjk_spacing((title or "").strip()))
            if s:
                chapter_norms.add(s)

    triples = []
    cur_chapter = "正文"
    for i, (lvl, title, page) in enumerate(toc):
        start = max(0, page - 1)
        end = (toc[i + 1][2] - 1) if i + 1 < len(toc) else n - 1
        end = max(end, start)
        title = _collapse_cjk_spacing((title or "").strip())
        if lvl <= 1:
            cur_chapter = title
        # exclude 仅保护『当前小节标题』（防止正文起始的小节标题被误当页眉删）；
        # 绝不可加入当前章签名——否则当前章的页眉块（签名==章签名）将被保护而不被剔除，
        # 残留成 '第/序/前/言…' 逐字碎片。
        exclude = set()
        if lvl > 1:
            s_sig = _loose_sig(title)
            if s_sig:
                exclude.add(s_sig)
        txt = "".join(_page_text_clean(doc, p, chapter_norms, exclude)
                      for p in range(start, end + 1))
        if lvl <= 1:
            triples.append((cur_chapter, None, txt))
        else:
            triples.append((cur_chapter, title, txt))
    return _clean_triples(triples)


def _pdf_sections(path):
    import pymupdf as fitz
    import statistics
    doc = fitz.open(path)
    n = doc.page_count
    meta = _pdf_meta(doc)
    toc = doc.get_toc()  # [[level, title, page(1-based)], ...]
    if toc:
        # TOC 已是完整层级（章/节/小节）。直接信任大纲，不再对正文跑
        # _resplit_embedded —— 否则 PDF 每页页眉（"第5章 ……81" 带引导点页码）、
        # 代码清单标题会被 _HEAD_RE 当成"章"切出，产生大量垃圾章
        # （实测某教材 21 真实章被炸成 58 章/766 课）。无 TOC 的 fallback 路径
        # 仍保留 _resplit_embedded 作兜底。
        triples = _outline_to_triples(toc, doc, n)
        doc.close()
        return triples, n, meta

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
                if not headings or not (headings[-1][0] == p and headings[-1][1] == txt):
                    headings.append((p, txt))
    if headings:
        triples = []
        for i, (pg, title) in enumerate(headings):
            # 下一章起点页（exclusive）：正文只取到下一章所在页之前，避免把
            # 下一章标题行并进本章（否则"一章文件夹下塞好几章"）。
            end_excl = headings[i + 1][0] if i + 1 < len(headings) else n
            txt = "\n".join(doc[p].get_text("text") for p in range(pg, end_excl))
            sub = _split_hierarchical(txt)
            if sub:
                for (c2, s2, t2) in sub:
                    triples.append((c2 or title, s2, t2))
            else:
                triples.append((title, None, txt))
        doc.close()
        return _resplit_embedded(_clean_triples(triples)), n, meta

    # 字体检测无果 → 整本拼接按标题正则切
    full = "\n".join(doc[p].get_text("text") for p in range(n))
    sub = _split_hierarchical(full)
    if sub:
        doc.close()
        return _resplit_embedded(sub), n, meta

    # 完全无结构 → 逐页（保留旧行为，标为单章）
    sections = [(f"第{p + 1}页", doc[p].get_text("text")) for p in range(n)]
    doc.close()
    triples = [(t, None, x) for t, x in sections]
    return triples, n, meta


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
            triples = _outline_to_triples(toc, doc, n)
            doc.close()
            return _resplit_embedded(triples), n, meta
        full = "\n".join(doc[p].get_text("text") for p in range(n))
        doc.close()
        sub = _split_hierarchical(full)
        if sub:
            return _resplit_embedded(sub), n, meta
        return [(meta.get("title") or "全文", None, full)], n, meta
    except Exception:
        pass
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
    triples = []
    cur_chapter = None
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        txt = soup.get_text("\n")
        txt = "\n".join(ln.strip() for ln in txt.splitlines() if ln.strip())
        sub = _split_hierarchical(txt)
        if sub:
            for (c, s, t) in sub:
                # EPUB 单文档可能跨多章；用 sub 的章（若 None 退回当前章）
                cur_chapter = c or cur_chapter
                triples.append((cur_chapter or c or "正文", s, t))
        else:
            cur_chapter = cur_chapter or meta.get("title") or "正文"
            triples.append((cur_chapter, None, txt))
    return _resplit_embedded(_clean_triples(triples)), len(triples), meta


# ---------------------------------------------------------------------------
# DJVU（pymupdf 优先；否则 项目/vendor/djvulibre/ 的 djvutxt；再否则 PATH）
# ---------------------------------------------------------------------------
def _find_djvutxt():
    """优先项目本地 vendor/djvulibre/，再系统 PATH。"""
    local = Path(__file__).resolve().parent.parent.parent / "vendor" / "djvulibre"
    for name in ("djvutxt.exe", "djvutxt"):
        cand = local / name
        if cand.exists():
            return str(cand)
    return shutil.which("djvutxt") or shutil.which("djvutxt.exe")


def _djvu_sections(path):
    try:
        import pymupdf as fitz
        doc = fitz.open(path)
        if doc.page_count > 0:
            n = doc.page_count
            meta = _pdf_meta(doc)
            toc = doc.get_toc()
            if toc:
                triples = _outline_to_triples(toc, doc, n)
                doc.close()
                return _resplit_embedded(triples), n, meta
            full = "\n".join(doc[p].get_text("text") for p in range(n))
            sub = _split_hierarchical(full)
            if sub:
                doc.close()
                return _resplit_embedded(sub), n, meta
            triples = [(f"第{p + 1}页", None, doc[p].get_text("text")) for p in range(n)]
            doc.close()
            return triples, n, meta
    except Exception:
        pass
    djvutxt = _find_djvutxt()
    if djvutxt:
        try:
            out = subprocess.run([djvutxt, path], capture_output=True, text=True, timeout=120)
            txt = out.stdout or ""
        except Exception as e:
            raise RuntimeError("djvutxt 执行失败：%s" % e)
        sub = _split_hierarchical(txt)
        if sub:
            return _resplit_embedded(sub), len(sub), {}
        return [("全文", None, txt)], 1, {}
    raise RuntimeError(
        "DJVU 抽取失败：当前环境 PyMuPDF 未带 djvu 支持，且未装 djvulibre(djvutxt)。\n"
        "  已支持本地化：把 djvutxt.exe 放到 项目/vendor/djvulibre/ 即可（无需装系统版）。\n"
        "  或从 https://sourceforge.net/projects/djvu/ 下载 DjVuLibre 后放入该目录。")


# ---------------------------------------------------------------------------
# TXT / MD（直达，无需解析）
# ---------------------------------------------------------------------------
def _text_sections(path, is_md=False):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    if is_md:
        # md：# 章，##/### 节（层级切分）
        lines = raw.split("\n")
        heads = [(i, l) for i, l in enumerate(lines)
                 if re.match(r"^(#{1,6})\s+", l)]
        if len(heads) >= 1:
            triples = []
            cur_chapter = None
            for j, (idx, line) in enumerate(heads):
                m = re.match(r"^(#{1,6})\s+(.*)$", line)
                level = len(m.group(1)); title = m.group(2).strip()
                nxt = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
                body = "\n".join(lines[idx + 1:nxt]).strip()
                if level <= 1:
                    cur_chapter = title
                    triples.append((title, None, body))
                else:
                    triples.append((cur_chapter or "正文", title, body))
            return _clean_triples(triples), len(triples), {}
    # 纯 txt 或无标题 md → 整本按章正则切
    sub = _split_hierarchical(raw)
    if sub:
        return _resplit_embedded(sub), len(sub), {}
    title = os.path.splitext(os.path.basename(path))[0]
    return [(title, None, raw)], 1, {}


# ---------------------------------------------------------------------------
# DOCX（python-docx：标题样式层级→章/节；表格→md；按文档顺序保留段落/表格）
# ---------------------------------------------------------------------------
def _iter_block_items(parent):
    from docx.document import Document as _Doc
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    if isinstance(parent, _Doc):
        elem = parent.element.body
    elif isinstance(parent, Table):
        elem = parent._tbl
    else:
        elem = parent._tc
    for child in elem.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _docx_table_to_md(table):
    rows = []
    for r in table.rows:
        cells = [c.text.strip().replace("\n", " ").replace("|", "/") for c in r.cells]
        rows.append(cells)
    if not rows:
        return ""
    ncol = len(rows[0])
    out = ["| " + " | ".join(rows[0]) + " |"]
    if len(rows) >= 2:
        out.append("| " + " | ".join(["---"] * ncol) + " |")
        for r in rows[1:]:
            out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _docx_heading_level(para):
    name = (para.style.name or "") if para.style else ""
    m = re.match(r"(?:Heading|标题)\s*(\d+)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if name.lower().startswith("heading") or name.startswith("标题"):
        return 1
    return None


def _docx_sections(path):
    import docx
    from docx.text.paragraph import Paragraph as _P
    from docx.table import Table as _T
    doc = docx.Document(path)
    meta = {}
    cp = doc.core_properties
    if getattr(cp, "title", None):
        meta["title"] = cp.title.strip()
    if getattr(cp, "author", None):
        meta["author"] = cp.author.strip()
    fallback = meta.get("title") or os.path.splitext(os.path.basename(path))[0]
    triples = []
    cur_chapter = None
    cur_section = None
    buf = []

    def flush():
        nonlocal cur_section, buf
        if buf:
            triples.append((cur_chapter or fallback, cur_section, "\n".join(buf)))
        cur_section = None
        buf = []

    for blk in _iter_block_items(doc):
        if isinstance(blk, _P):
            txt = blk.text.strip()
            lvl = _docx_heading_level(blk)
            if lvl is not None and txt:
                flush()
                if lvl <= 1:
                    cur_chapter = txt
                    cur_section = None
                else:
                    cur_section = txt
            elif txt:
                buf.append(txt)
        elif isinstance(blk, _T):
            md = _docx_table_to_md(blk)
            if md:
                buf.append(md)
    flush()
    if not triples:
        triples = [(fallback, None, "")]
    return _resplit_embedded(_clean_triples(triples)), len(triples), meta


# ---------------------------------------------------------------------------
# MOBI / AZW / AZW3（mobi 库解包为 HTML，零膨胀；兜底 calibre 转 EPUB）
# ---------------------------------------------------------------------------
def _mobi_html_to_triples(html_path, fallback_title="全文"):
    from bs4 import BeautifulSoup
    try:
        html = open(html_path, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        raise RuntimeError("MOBI 解包后 HTML 读取失败：%s" % e)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    meta = {}
    if soup.title and soup.title.string:
        meta["title"] = soup.title.string.strip()
    full0 = soup.get_text("\n")
    m = re.search(r"Project Gutenberg eBook of .*? by (.+?)[\r\n]", full0)
    if m:
        meta["author"] = m.group(1).strip()

    heads = [h for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)]
    if len(heads) >= 2:
        triples = []
        cur_chapter = None
        cur_section = None
        buf = []

        def flush():
            nonlocal cur_section, buf
            if buf:
                triples.append((cur_chapter or fallback_title, cur_section, "\n".join(buf)))
            cur_section = None
            buf = []

        blocks = soup.find_all(["h1", "h2", "h3", "p", "table"])
        for el in blocks:
            if el.name in ("h1", "h2", "h3"):
                flush()
                t = el.get_text(strip=True)
                if el.name == "h1":
                    cur_chapter = t
                    cur_section = None
                else:
                    cur_section = t
            else:
                t = el.get_text(strip=True)
                if t:
                    buf.append(t)
        flush()
        secs = _resplit_embedded(_clean_triples(triples))
        return secs, len(secs), meta

    # 无 HTML 标题标签 → 整本文本按章→节切（覆盖 Alice 这类 "CHAPTER I." 起步）
    full = soup.get_text("\n")
    sub = _split_hierarchical(full)
    if sub:
        return _resplit_embedded(sub), len(sub), meta
    return [(meta.get("title") or fallback_title, None, full.strip())], 1, meta


def _mobi_sections(path):
    try:
        import mobi
        _td, html_path = mobi.extract(path)
        return _mobi_html_to_triples(
            html_path, fallback_title=os.path.splitext(os.path.basename(path))[0])
    except ImportError:
        pass
    ec = shutil.which("ebook-convert") or shutil.which("ebook-convert.exe")
    if ec:
        import tempfile as _tf
        fd, epub = _tf.mkstemp(suffix=".epub")
        os.close(fd)
        try:
            subprocess.run([ec, path, epub], capture_output=True, text=True,
                           timeout=180, check=True)
        except Exception as e:
            raise RuntimeError("calibre ebook-convert 转换失败：%s" % e)
        try:
            return _epub_sections(epub)
        finally:
            try:
                os.unlink(epub)
            except Exception:
                pass
    raise RuntimeError(
        "MOBI/AZW 抽取失败：需要 `mobi` 库或 calibre。\n"
        "  推荐：pip install mobi   （纯 Python 零膨胀）\n"
        "  或安装 calibre，ebook-convert 会自动把 MOBI 转 EPUB 再抽取。")


# ---------------------------------------------------------------------------
# OCR 钩子（可选）—— 扫描版 PDF/DJVU 文本层空时调用
# ---------------------------------------------------------------------------
def _try_ocr(path, fmt):
    """若本机有 OCR 后端（tesseract / MinerU / Nougat），对扫描版做识别。
    返回 (text_or_None, backend_name_or_None)。无后端 → (None, None)。"""
    try:
        from ocr import ocr_document
        return ocr_document(path, fmt)
    except Exception as e:
        return None, f"OCR 钩子异常：{e}"


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def extract(path, fmt=None):
    """抽取一本书为「章/节」层级章节。

    返回 dict：
      {
        'fmt': str, 'page_count': int, 'needs_ocr': bool,
        'book_type': 'novel'|'textbook'|'unknown',
        'sections': [{'chapter','section','title','text'}, ...],  # text 已清洗
        'meta': {'name','source','title','author', ...}
      }
    """
    path = str(path)
    if not os.path.exists(path):
        raise RuntimeError(f"文件不存在：{path}")
    fmt = fmt or detect_format(path)
    meta0 = {}
    if fmt == "pdf":
        triples, n, meta0 = _pdf_sections(path)
    elif fmt == "epub":
        triples, n, meta0 = _epub_sections(path)
    elif fmt == "djvu":
        triples, n, meta0 = _djvu_sections(path)
    elif fmt == "txt":
        triples, n, meta0 = _text_sections(path, is_md=False)
    elif fmt == "md":
        triples, n, meta0 = _text_sections(path, is_md=True)
    elif fmt == "docx":
        triples, n, meta0 = _docx_sections(path)
    elif fmt in ("mobi", "azw", "azw3"):
        triples, n, meta0 = _mobi_sections(path)
    else:
        raise RuntimeError(
            f"不支持的格式：{fmt}（{path}）。"
            "支持 pdf/epub/mobi/azw/azw3/djvu/docx/txt/md。")

    # 清洗 + 去跨页页眉页脚
    sections = [{"chapter": c, "section": s, "title": (s or c),
                 "text": _clean_book_text(t)} for (c, s, t) in triples]
    sections = _drop_running_headers(sections)

    # 扫描版判定 + 可选 OCR
    # EPUB/MOBI/TXT/MD 是重排文本，没有"页"概念，OCR 无意义；
    # 仅扫描型位图容器 PDF/DJVU 才可能文本层过薄需 OCR。
    needs_ocr = _needs_ocr(sections, n) if fmt in ("pdf", "djvu") else False
    if needs_ocr and fmt in ("pdf", "djvu"):
        ocr_text, backend = _try_ocr(path, fmt)
        if ocr_text and ocr_text.strip():
            sub = _split_hierarchical(ocr_text)
            if sub:
                sections = [{"chapter": c, "section": s, "title": (s or c),
                             "text": _clean_book_text(t)}
                            for (c, s, t) in _resplit_embedded(sub)]
                needs_ocr = False
                meta0["ocr_backend"] = backend or "unknown"

    # 书籍类型：任一带 section → 课文（章含节）；否则小说（章即最小单位）
    book_type = "textbook" if any(s["section"] for s in sections) else "novel"

    meta = {"name": os.path.splitext(os.path.basename(path))[0], "source": "local-file"}
    meta.update({k: v for k, v in meta0.items() if v})
    return {
        "fmt": fmt,
        "page_count": n,
        "needs_ocr": needs_ocr,
        "book_type": book_type,
        "sections": sections,
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

    # --- 用例1：带大纲的 PDF（课文：章含节）→ 按大纲拆 2 章，含节 ---
    d = fitz.open()
    for i in range(4):
        pg = d.new_page()
        pg.insert_text((72, 72), f"这是第 {i + 1} 页的示例正文。")
    d.set_toc([
        (1, "第一章 整数", 1),
        (2, "第一节 自然数", 1),
        (2, "第二节 四则运算", 2),
        (1, "第二章 代数", 3),
        (2, "第一节 方程", 3),
    ])
    fd, pdf1 = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    d.save(pdf1)
    d.close()
    r = extract(pdf1)
    assert r["fmt"] == "pdf" and r["page_count"] == 4
    assert r["book_type"] == "textbook", "大纲含节 → 应为 textbook，实际 %s" % r["book_type"]
    chs = [s["chapter"] for s in r["sections"]]
    secs = [s["section"] for s in r["sections"] if s["section"]]
    assert "第一章 整数" in chs and "第二章 代数" in chs, chs
    assert "第一节 自然数" in secs and "第二节 四则运算" in secs, secs
    os.unlink(pdf1)

    # --- 用例2：无大纲小说 PDF（多章，无节）→ 启发式切多章，book_type=novel ---
    d = fitz.open()
    p1 = d.new_page()
    p1.insert_text((72, 60), "Chapter 1 The Beginning", fontsize=18)
    p1.insert_text((72, 90), "The boy stood in the courtyard, looking up at the sky.", fontsize=11)
    p2 = d.new_page()
    p2.insert_text((72, 60), "Chapter 2 The Encounter", fontsize=18)
    p2.insert_text((72, 90), "From now on, the youth called a waste would cease to be.", fontsize=11)
    p3 = d.new_page()
    p3.insert_text((72, 60), "Chapter 3 The Return", fontsize=18)
    p3.insert_text((72, 90), "He came back to the city where it all began.", fontsize=11)
    fd, pdf2 = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    d.save(pdf2)
    d.close()
    r = extract(pdf2)
    assert r["fmt"] == "pdf"
    assert r["book_type"] == "novel", "无节多章 → 应为 novel，实际 %s" % r["book_type"]
    assert len(r["sections"]) >= 3, "应切出 >=3 章，实际 %d" % len(r["sections"])
    titles = " ".join(s["title"] for s in r["sections"])
    assert "Chapter 1" in titles and "Chapter 2" in titles and "Chapter 3" in titles, titles
    # 断言：没有任何一节的正文里还嵌着别的章起点（杜绝"一章文件夹下好几章"）
    for s in r["sections"]:
        assert not any(_HEAD_RE.match(ln.strip()) and not _NONCHAPTER_RE.match(ln.strip())
                        for ln in s["text"].split("\n")), \
            "正文内仍嵌章起点：%s" % s["title"]
    os.unlink(pdf2)

    # --- 用例3：扫描版（文本层空）→ needs_ocr=True（无 OCR 后端时）---
    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((72, 72), " ")
    fd, pdf3 = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    d.save(pdf3)
    d.close()
    r = extract(pdf3)
    assert r["needs_ocr"] is True, "文本层空应标 needs_ocr"
    os.unlink(pdf3)

    # --- 用例4：DOCX → 标题层级切章/节 + 表格 + 元数据 ---
    try:
        import docx as _dx
        dd = _dx.Document()
        dd.core_properties.title = "Docx Test Book"
        dd.core_properties.author = "John Smith"
        dd.add_heading("第一章 引言", level=1)
        dd.add_paragraph("这是第一章的示例正文。")
        t = dd.add_table(rows=2, cols=2)
        t.cell(0, 0).text = "项目"
        t.cell(0, 1).text = "说明"
        t.cell(1, 0).text = "A"
        t.cell(1, 1).text = "示例"
        dd.add_heading("第一节 背景", level=2)
        dd.add_paragraph("这是第一节的示例正文。")
        dd.add_heading("第二章 方法", level=1)
        dd.add_paragraph("这是第二章的示例正文。")
        fd, docx1 = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        dd.save(docx1)
        r = extract(docx1)
        assert r["fmt"] == "docx", r
        assert r["book_type"] == "textbook", r["book_type"]
        assert len(r["sections"]) >= 3, "DOCX 应切出 >=3 节，实际 %d" % len(r["sections"])
        body = "\n".join(s["text"] for s in r["sections"])
        assert "|" in body, "DOCX 表格应转成 md 表格"
        assert r["meta"].get("author") == "John Smith", r["meta"]
        os.unlink(docx1)
    except ImportError:
        print("  (skipped DOCX 用例：python-docx 未装)")

    # --- 用例5：MOBI（用预下载样本；无样本则跳过）---
    _mobi_sample = os.path.join(tempfile.gettempdir(), "alice.mobi")
    if os.path.exists(_mobi_sample):
        r = extract(_mobi_sample)
        assert r["fmt"] == "mobi", r
        assert len(r["sections"]) >= 12, "MOBI 应切出多章，实际 %d" % len(r["sections"])
        titles = " ".join(s["title"] for s in r["sections"])
        assert "CHAPTER I" in titles, "MOBI 章节标题未被识别：%s" % titles[:200]
        assert r["needs_ocr"] is False
        print("  mobi 样本切出 %d 章" % len(r["sections"]))
    else:
        print("  (skipped MOBI 用例：无样本 alice.mobi)")

    print("  selftest passed（大纲章含节 / 无大纲多章小说 / 扫描版标记 / DOCX / MOBI / "
          "防御 re-split）。")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        if len(sys.argv) < 2:
            print("usage: python book_formats.py <file> [--selftest]")
            sys.exit(1)
        r = extract(sys.argv[1])
        print(f"fmt={r['fmt']} pages={r['page_count']} book_type={r['book_type']} "
              f"sections={len(r['sections'])} needs_ocr={r['needs_ocr']} meta={r['meta']}")
        for i, s in enumerate(r["sections"][:3], 1):
            print(f"--- [{i}] 章={s['chapter']} 节={s['section']} ({len(s['text'])} chars) ---\n"
                  f"{s['text'][:200]}")
