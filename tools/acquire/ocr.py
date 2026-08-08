#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr.py — 扫描版 PDF/DJVU 的可插拔 OCR 钩子（授业格式层）

book_formats.extract 检测到文本层稀疏（needs_ocr）时调用本模块。
设计原则：不捆绑任何重型模型 / 不强制安装；本机有哪个后端就用哪个。

后端（按优先级）：
  1. tesseract  （轻量，本地，推荐）        —— PDF/DJVU 渲染成像素图后用 tesseract 识别；
                                              中文需系统装 chi_sim 语言包。
  2. MinerU     （重，但输出结构化 md 直接） —— 一行命令把整 PDF 转成 markdown（含标题/表格/公式），
                                              最契合我们的「规范层 = md」目标。
  3. Nougat     （Meta，重，学术 PDF→md）    —— 同理，输出 .mmd markdown。

三者皆无 → 返回 (None, reason)，extract 保留 needs_ocr 标记 + 清晰提示，不崩溃。

用法（供 book_formats 调用）：
    from ocr import ocr_document, available_backends
    text, backend = ocr_document("scan.pdf", "pdf")
"""
import os
import sys
import shutil
import subprocess
import tempfile

# tesseract 语言包：中文+英文（中文需本机装 chi_sim；没有就退英文）
TESS_LANGS = "chi_sim+eng"

# 项目内 vendor 目录下的本地二进制（无需系统安装 / 不污染 PATH）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENDOR_TESSERACT = os.path.join(_PROJECT_ROOT, "vendor", "tesseract", "tesseract.exe")
_VENDOR_TESSDATA = os.path.join(_PROJECT_ROOT, "vendor", "tesseract", "tessdata")


def _resolve_tesseract():
    """返回 tesseract 可执行文件路径：优先系统 PATH，其次项目 vendor/tesseract/。"""
    for cand in (shutil.which("tesseract"), shutil.which("tesseract.exe"), _VENDOR_TESSERACT):
        if cand and os.path.isfile(cand):
            return cand
    return None


def _has(cmd):
    return bool(shutil.which(cmd) or shutil.which(cmd + ".exe"))


def available_backends():
    """返回本机可用的 OCR 后端列表（按优先级排序）。"""
    out = []
    if _resolve_tesseract():
        out.append("tesseract")
    if _has("mineru"):
        out.append("mineru")
    if _has("nougat"):
        out.append("nougat")
    return out


def _ocr_with_tesseract(path, fmt):
    """渲染 PDF/DJVU 页面为图 → tesseract 逐页识别 → 拼接文本。"""
    try:
        import pymupdf as fitz
    except Exception:
        return None, "pymupdf 缺失（渲染所需）"
    try:
        doc = fitz.open(path)
    except Exception as e:
        return None, f"PyMuPDF 无法打开（{e}）；DJVU 需 PyMuPDF 带 djvu 支持"
    n = doc.page_count
    if n <= 0:
        doc.close()
        return None, "空文档"
    tess = _resolve_tesseract()
    if not tess:
        doc.close()
        return None, "tesseract 未安装（把 Tesseract-OCR 装到项目 vendor/tesseract/ 或系统 PATH）"
    # 用项目内 vendor 的 tesseract 时，显式指定 tessdata 目录（中文包已预置）
    tess_env = None
    if os.path.abspath(tess) == os.path.abspath(_VENDOR_TESSERACT) and os.path.isdir(_VENDOR_TESSDATA):
        tess_env = dict(os.environ, TESSDATA_PREFIX=_VENDOR_TESSDATA)
    pages_text = []
    tmpdir = tempfile.mkdtemp(prefix="ocr_tess_")
    try:
        for p in range(n):
            pix = doc[p].get_pixmap(dpi=300)
            img = os.path.join(tmpdir, f"p{p:04d}.png")
            pix.save(img)
            try:
                r = subprocess.run([tess, img, "stdout", "-l", TESS_LANGS],
                                   capture_output=True, text=True, timeout=120, env=tess_env)
                pages_text.append(r.stdout or "")
            except Exception as e:
                pages_text.append("")
        doc.close()
        return "\n".join(pages_text).strip(), "tesseract"
    finally:
        import shutil as _sh
        _sh.rmtree(tmpdir, ignore_errors=True)


def _ocr_with_mineru(path):
    """MinerU：整 PDF → markdown（含结构）。读其产物文本。"""
    mineru = shutil.which("mineru") or shutil.which("mineru.exe")
    if not mineru:
        return None, "mineru 未安装（pip install magic-pdf[full] 后可用 mineru 命令）"
    out = tempfile.mkdtemp(prefix="ocr_mineru_")
    try:
        r = subprocess.run([mineru, "-p", path, "-o", out],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None, f"mineru 失败：{r.stderr[:160]}"
        # 产物：output/<原名>/<原名>.markdown 或 .txt
        texts = []
        for root, _, files in os.walk(out):
            for f in files:
                if f.lower().endswith((".markdown", ".md", ".txt")):
                    texts.append(open(os.path.join(root, f), encoding="utf-8",
                                       errors="ignore").read())
        if not texts:
            return None, "mineru 未产出文本"
        return "\n".join(texts).strip(), "mineru"
    finally:
        import shutil as _sh
        _sh.rmtree(out, ignore_errors=True)


def _ocr_with_nougat(path):
    """Nougat：PDF → markdown (.mmd)。"""
    nougat = shutil.which("nougat") or shutil.which("nougat.exe")
    if not nougat:
        return None, "nougat 未安装（pip install nougat-ocr 后可用）"
    out = tempfile.mkdtemp(prefix="ocr_nougat_")
    try:
        r = subprocess.run([nougat, path, "-o", out],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None, f"nougat 失败：{r.stderr[:160]}"
        texts = []
        for root, _, files in os.walk(out):
            for f in files:
                if f.lower().endswith((".mmd", ".md", ".txt")):
                    texts.append(open(os.path.join(root, f), encoding="utf-8",
                                       errors="ignore").read())
        if not texts:
            return None, "nougat 未产出文本"
        return "\n".join(texts).strip(), "nougat"
    finally:
        import shutil as _sh
        _sh.rmtree(out, ignore_errors=True)


def ocr_document(path, fmt):
    """对扫描版文档做 OCR。返回 (text_or_None, backend_or_reason)。

    text 非空 → extract 会用它重新切章（替换 needs_ocr 标记）；
    None      → 调用方保留 needs_ocr 标记。
    """
    backends = available_backends()
    if not backends:
        return None, ("无 OCR 后端：装 tesseract（轻量，需 chi_sim 中文包）或 "
                      "MinerU/Nougat（重模型、输出 md 直接）后自动启用")
    # tesseract 能处理 pdf/djvu 渲染；MinerU/Nougat 主要吃 pdf
    if "tesseract" in backends and fmt in ("pdf", "djvu"):
        t, b = _ocr_with_tesseract(path, fmt)
        if t:
            return t, b
    if "mineru" in backends and fmt == "pdf":
        t, b = _ocr_with_mineru(path)
        if t:
            return t, b
    if "nougat" in backends and fmt == "pdf":
        t, b = _ocr_with_nougat(path)
        if t:
            return t, b
    return None, f"已装后端 {backends} 但本次未产出文本（格式={fmt}）"


if __name__ == "__main__":
    print("可用 OCR 后端：", available_backends() or "（无）")
    if len(sys.argv) > 1:
        t, b = ocr_document(sys.argv[1],
                            "pdf" if sys.argv[1].lower().endswith(".pdf") else "djvu")
        print(f"backend={b}, 文本长度={len(t) if t else 0}")
