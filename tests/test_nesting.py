#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""嵌套回归测试（v4 修复防回归）：ingest → course_gen 端到端（参考/直读，已废 预处理/ 中间层）。

锁住两个核心不变量，避免将来动 pipeline/course_gen 时悄悄回归：
  1) 小说（章为最小单位，无子节）：每「章」独立成文件夹、各含 1 课，
     绝不允许「一个章文件夹下塞好几章」。
  2) 课文（章→节）：每「章」文件夹内含若干「节」课（章含导言+节）。

不联网、零新依赖；用 venv python 以真实 CLI 跑完整链路。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)


def _run(args):
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("=== STDERR ===\n" + r.stderr)
        raise SystemExit(f"命令失败（{args[0]} {args[1]}）：{r.returncode}\n{r.stdout[-500:]}")


def _pipeline(cmd, *a):
    _run(["tools/acquire/pipeline.py", cmd, *a])


def _course_gen(book):
    _run(["tools/structure/course_gen.py", f"参考/{book}", "--book", book])


def test_novel_nesting():
    """小说：3 章 → 3 个独立章文件夹，每章 1 课。"""
    d = Path(tempfile.mkdtemp(prefix="nest_novel_"))
    try:
        src = d / "novel.txt"
        src.write_text(
            "第一章 启程\n"
            "萧炎站在院中，抬头望着天空。这是故事的开始。\n\n"
            "夜色渐深，乌坦城的灯火次第亮起。\n\n"
            "第二章 遭遇\n"
            "从今往后，那个被称为废物的少年不复存在。\n\n"
            "他在山林中遇见了神秘的来客。\n\n"
            "第三章 归来\n"
            "他终于回到了这座熟悉又陌生的城市。\n\n"
            "一切都已不同。\n",
            encoding="utf-8",
        )
        _pipeline("ingest", str(src), "--name", "nest_novel")
        _course_gen("nest_novel")

        bd = ROOT / "书库" / "nest_novel"
        chapters = [p.name for p in sorted(bd.iterdir()) if p.is_dir()]
        # 关键不变量1：章文件夹数 == 实际章数（3），无塌缩
        assert chapters == ["第01章_启程", "第02章_遭遇", "第03章_归来"], \
            f"小说章文件夹塌缩/错序：{chapters}"
        # 每章恰好 1 课
        for ch in chapters:
            lessons = list((bd / ch).glob("第*课_*.md"))
            assert len(lessons) == 1, f"{ch} 应含 1 课，实际 {[l.name for l in lessons]}"
            # 课名应为章标题（启程/遭遇/归来），不再是"全文"
            assert lessons[0].name.endswith("启程.md") or \
                   "全文" not in lessons[0].name, \
                f"小说课名不应为'全文'：{lessons[0].name}"
        print(f"[test_nesting] 小说通过：{len(chapters)} 章 / 每章 1 课（独立文件夹）")
    finally:
        import shutil
        for base in ("参考", "书库"):
            shutil.rmtree(ROOT / base / "nest_novel", ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)


def test_textbook_nesting():
    """课文：章→节，第1章含导言+2节，第2章含1节。"""
    d = Path(tempfile.mkdtemp(prefix="nest_tb_"))
    try:
        src = d / "textbook.md"
        src.write_text(
            "# 第一章 整数\n\n"
            "本章介绍自然数与四则运算。\n\n"
            "## 第一节 自然数\n\n"
            "自然数是从 0 开始的整数序列。\n\n"
            "## 第二节 四则运算\n\n"
            "乘法是加法的简便形式。\n\n"
            "# 第二章 代数\n\n"
            "## 第一节 方程\n\n"
            "含有未知数的等式叫做方程。\n",
            encoding="utf-8",
        )
        _pipeline("ingest", str(src), "--name", "nest_textbook")
        _course_gen("nest_textbook")

        bd = ROOT / "书库" / "nest_textbook"
        chapters = [p.name for p in sorted(bd.iterdir()) if p.is_dir()]
        assert chapters == ["第01章_整数", "第02章_代数"], f"课文章顺序异常：{chapters}"
        # 关键不变量2：章文件夹内含多课（章→节嵌套）
        c1 = sorted(p.name for p in (bd / "第01章_整数").glob("第*课_*.md"))
        assert len(c1) >= 3, f"第01章应含导言+2节 >=3 课，实际 {c1}"
        c2 = sorted(p.name for p in (bd / "第02章_代数").glob("第*课_*.md"))
        assert len(c2) >= 1, f"第02章应含 >=1 课，实际 {c2}"
        print(f"[test_nesting] 课文通过：{len(chapters)} 章 / 章内含多课（章→节嵌套）")
    finally:
        import shutil
        for base in ("参考", "书库"):
            shutil.rmtree(ROOT / base / "nest_textbook", ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    ok = True
    ok = test_novel_nesting() and ok
    ok = test_textbook_nesting() and ok
    sys.exit(0 if ok else 1)
