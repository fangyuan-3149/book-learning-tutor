#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_env.py — 授业（Book Learning Tutor）一键环境就绪。

下载 / 克隆本项目后，先跑这一条：
    python setup_env.py
它会：
    1. 在仓库根建一个精简虚拟环境  venv_slim/
    2. 升级 pip
    3. 安装 requirements.txt（核心：格式转换 + 课程化 全流程依赖）
    4. 提示下一步：python teach.py <本地书>

设计要点：
    - 跨平台（Windows / macOS / Linux），不依赖任何固定盘符 / 绝对路径
    - 幂等：venv_slim 已存在则复用，不会重复建；依赖仍会补足（便于升级）
    - 只装「核心」依赖；在线书源 / OCR 等可选能力见 README 与 requirements-extra.txt
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv_slim"
REQ = ROOT / "requirements.txt"

IS_WIN = sys.platform.startswith("win")


def venv_python() -> Path:
    return VENV / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


def run(cmd, **kw):
    print("▶ " + " ".join(str(c) for c in cmd))
    rc = subprocess.run(cmd, **kw).returncode
    if rc != 0:
        sys.exit(rc)
    return rc


def main() -> int:
    if not REQ.exists():
        print(f"✗ 找不到 {REQ.name}（请确认在仓库根目录运行）")
        return 1

    py = str(venv_python())
    if VENV.exists():
        print(f"· 复用已有虚拟环境：{VENV}")
    else:
        print(f"· 创建虚拟环境：{VENV}")
        run([sys.executable, "-m", "venv", str(VENV)])

    # 升级 pip（新 venv 自带 pip，但可能偏旧）
    run([py, "-m", "pip", "install", "--upgrade", "pip"],
        cwd=str(ROOT))

    # 装核心依赖
    print(f"· 安装核心依赖（{REQ.name}）……")
    run([py, "-m", "pip", "install", "-r", str(REQ)],
        cwd=str(ROOT))

    print("\n" + "=" * 58)
    print("✅ 环境就绪 → venv_slim/")
    print("-" * 58)
    print("下一步，把一本本地书变成课程：")
    print(f"    {py} teach.py \"路径/到/书.pdf\"")
    print("然后对助手说：『教我这本书 <书名>』")
    print("-" * 58)
    print("可选：要「从网站取书」（search/download）再加装：")
    print(f"    {py} -m pip install -r requirements-extra.txt")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
