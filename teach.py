#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teach.py — 授业（Book Learning Tutor）· 一键把本地书变成逐课课程，并告诉你怎么开始学。

用法：
    python teach.py "路径/到/书.pdf" [--name 书名]

它做的事（全部在本地，不联网、不爬取，只处理你提供的文件）：
    1. 抽取章节        → 参考/<书名>/
    2. 课程化（参考/直读）→ 书库/<书名>/（含 progress.json）
    3. 校验课程生成成功
    4. 打印「下一步：对助手说『教我这本书 <书名>』」

路径自适应：脚本根据自身位置推导仓库根，不依赖任何固定的盘符/绝对路径，
克隆到任意目录都能跑。
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPELINE = ROOT / "tools" / "acquire" / "pipeline.py"

# 共享：文件名清洗（全仓唯一实现，见 tools/common/sanitize.py）
sys.path.insert(0, str(ROOT / "tools" / "common"))
from sanitize import safe_name


def _venv_python() -> Path:
    """仓库自带精简 venv：Windows 在 Scripts/，POSIX 在 bin/。"""
    if os.name == "nt":
        return ROOT / "venv_slim" / "Scripts" / "python.exe"
    return ROOT / "venv_slim" / "bin" / "python"


VENV_PY = _venv_python()


def pick_python() -> str:
    """优先用仓库自带的精简 venv；没有就退回到运行 teach.py 的解释器。"""
    if VENV_PY.exists():
        return str(VENV_PY)
    return sys.executable


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="teach.py",
        description="把一本本地书变成逐课课程（抽取→转md→课程化），然后开始教学。",
    )
    ap.add_argument("path", help="本地书文件：pdf/epub/djvu/mobi/azw/azw3/docx/txt/md/cbz")
    ap.add_argument("--name", default=None, help="可选显式书名；缺省用文件名")
    args = ap.parse_args()

    book = Path(args.path)
    if not book.exists():
        print(f"✗ 路径不存在：{args.path}")
        return 1

    py = pick_python()
    name = args.name or book.stem

    print(f"▶ 正在把《{book.name}》课程化……（本地处理，不联网、不爬取）\n")
    cmd = [py, str(PIPELINE), "all-local", str(book)]
    if args.name:
        cmd += ["--name", args.name]
    rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
    if rc != 0:
        print("\n✗ 课程化失败，详见上方报错。")
        return rc

    # 定位生成的课程目录（目录名已清洗）
    book_dir = ROOT / "书库" / safe_name(name)
    progress = book_dir / "progress.json"
    if not progress.exists():
        # 容错：若 --name 与目录名不一致，取书库下最新生成的目录
        candidates = [d for d in (ROOT / "书库").glob("*") if d.is_dir()]
        if candidates:
            book_dir = max(candidates, key=lambda d: d.stat().st_mtime)
            progress = book_dir / "progress.json"
    if not progress.exists():
        print(f"\n✗ 未检测到课程目录下的 progress.json，课程可能未完整生成。")
        return 1

    chapters = list(book_dir.glob("第*章*"))
    print("\n" + "=" * 58)
    print(f"✅ 课程已就绪 → 书库/{book_dir.name}/")
    print(f"   共 {len(chapters)} 章，可直接逐课学习。")
    print("-" * 58)
    print(f"👉 现在对助手说：『教我这本书 {book_dir.name}』")
    print("   助手会从第 1 课开始，按「备课 → 教学 → 作业 → 背诵」带你看完。")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
