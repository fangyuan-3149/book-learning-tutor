#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地化 djvulibre：从 DjVuLibre 的 Windows 安装包(MSI) 抽取 djvutxt.exe 到
项目 vendor/djvulibre/（该目录已在 .gitignore，二进制不入库）。

为什么：book_formats._djvu_sections 在 PyMuPDF 不带 djvu 支持时，会优先找
vendor/djvulibre/djvutxt.exe，再退回系统 PATH。所以把 djvutxt.exe 放项目目录即可，
无需装系统版 DjVuLibre。

用法：
    python get_djvulibre.py "<下载的 DjVuLibre MSI 路径>"

获取 MSI：SourceForge 项目 djvu → DjVuLibre → Windows 安装包（或任何便携版 djvutxt.exe
直接丢进 vendor/djvulibre/ 也行）。脚本用 Windows 自带 msilib/msiexec 抽取，无需提权、不写注册表。

校验：
    python -c "import sys; sys.path.insert(0,'.'); from book_formats import _find_djvutxt; print(_find_djvutxt())"
打印出 vendor/djvulibre/djvutxt.exe 即生效。
"""
import os
import sys
import msilib
import shutil
import subprocess
import tempfile

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "vendor", "djvulibre")


def extract_djvutxt(msi_path, out_dir):
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    db = msilib.OpenDatabase(msi_path, msilib.MSIDBOPEN_READONLY)
    view = db.OpenView("SELECT `Name` FROM `File`")
    view.Execute(None)
    names = [r.GetString(1) for r in iter(view.Fetch, None)]
    target = None
    for n in names:
        nl = n.lower()
        if "djvutxt" in nl and nl.endswith(".exe"):
            target = n
            break
    if not target:
        for n in names:
            if "djvu" in n.lower() and n.lower().endswith(".exe"):
                target = n
                break
    if not target:
        raise SystemExit("MSI 内未找到 djvutxt.exe（该安装包可能不含命令行工具）。")
    adm = tempfile.mkdtemp(prefix="djvu_admin_")
    try:
        r = subprocess.run(
            ["msiexec", "/a", os.path.abspath(msi_path), "/qn", f"TARGETDIR={adm}"],
            capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise SystemExit(f"msiexec /a 失败（{r.returncode}）：{r.stderr[:200]}")
        found = None
        for root, _, files in os.walk(adm):
            for f in files:
                if f.lower() == os.path.basename(target).lower():
                    found = os.path.join(root, f)
                    break
            if found:
                break
        if not found:
            raise SystemExit("管理安装后仍未找到 djvutxt.exe。")
        with open(found, "rb") as s, open(os.path.join(out_dir, os.path.basename(target)), "wb") as d:
            d.write(s.read())
    finally:
        shutil.rmtree(adm, ignore_errors=True)
    dst = os.path.join(out_dir, os.path.basename(target))
    print(f"✅ 已抽取：{dst}（{os.path.getsize(dst)} 字节）")
    print("   现在 book_formats 的 DJVU 抽取会自动使用该文件。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    extract_djvutxt(sys.argv[1], OUT_DIR)
