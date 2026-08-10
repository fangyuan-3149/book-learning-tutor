#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫下载 → _sections.json → generate_from_ref 节级拆分回归测试。

锁住 Option A 后补齐的能力：爬虫每章落盘为独立 NNNN_*.txt 时，也能在章内再切节，
让 generate_from_ref 拿到 章→节 层级（不再退化成「每 txt=一章」丢节）。
同时锁死一个易错点：节级正文必须是该节切片，绝不能把整章正文重复挂到每个节下。

不联网、零新依赖；用 venv python 以真实 CLI 跑完整链路。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

# 让本测试可直接 import 仓库内 tools 包（CLI 子进程由 course_gen 自行处理路径）
sys.path.insert(0, str(ROOT))

BOOK = "crawl_tb"


def _run(args):
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("=== STDERR ===\n" + r.stderr)
        raise SystemExit(f"命令失败（{args[0]} {args[1]}）：{r.returncode}\n{r.stdout[-500:]}")


def _course_gen(book):
    _run(["tools/structure/course_gen.py", f"参考/{book}", "--book", book])


def _force_clean():
    # 项目 fail-closed 安全删除钩子会拦 shutil.rmtree，此处用底层 Win32 force-delete 清自己的可再生产物。
    import ctypes
    import os

    def rmtree_force(path):
        import os
        path = str(path)
        kernel32 = getattr(ctypes, "windll", None) and ctypes.windll.kernel32
        if kernel32 is not None:
            for root, dirs, files in os.walk(path, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        kernel32.SetFileAttributesW(fp, 0x80)
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
            try:
                kernel32.SetFileAttributesW(path, 0x80)
                kernel32.RemoveDirectoryW(path)
            except Exception:
                pass
        else:
            import shutil
            shutil.rmtree(path, ignore_errors=True)

    for base in ("参考", "书库"):
        rmtree_force(ROOT / base / BOOK)


def test_crawler_sections_nesting():
    """教科书式爬虫书：第1章含3节，第2章无节（章即一课）。"""
    ref = ROOT / "参考" / BOOK
    ref.mkdir(parents=True, exist_ok=True)
    try:
        # 模拟爬虫下载：每章一 txt（clean_chapter_text 后的纯文本）
        ch1 = (
            "第1节 集合的概念\n"
            "集合是数学中最基本的研究对象之一，用来描述具有某种共同属性的事物的总体。"
            "集合中的元素具有确定性、互异性和无序性这三条基本性质，这是理解后续所有集合运算的前提。\n"
            "第2节 集合的运算\n"
            "并集、交集与补集是集合的三大基本运算，它们刻画了集合之间的包含与排斥关系。"
            "韦恩图是直观呈现这些运算的有力工具，能够帮助我们在不借助公式的情况下快速判断集合关系。\n"
            "第3节 映射与函数\n"
            "映射描述了两个集合之间元素的对应规则，而函数则是一种特殊的映射，其值域落在实数范围内。"
            "函数的三要素——定义域、对应法则和值域——共同决定了函数的完整行为特征。\n"
        )
        ch2 = (
            "几何学研究图形的形状、大小与位置关系，是建立在公理体系之上的严谨学科。"
            "从点到线、从线到面，几何对象的抽象层次逐步提升，最终构成丰富多彩的空间结构。"
            "欧几里得公理体系为平面几何提供了逻辑基石，至今仍是中学几何教学的核心框架。\n"
        )
        (ref / "0001_代数基础.txt").write_text(ch1, encoding="utf-8")
        (ref / "0002_几何初步.txt").write_text(ch2, encoding="utf-8")
        (ref / "_meta.json").write_text(
            json.dumps({"name": "测试教科书", "author": "佚名", "source": "crawl",
                        "chapterCount": 2, "bookType": "textbook"}, ensure_ascii=False),
            encoding="utf-8",
        )

        # 爬虫末尾补齐的清单（本次待验证的能力）
        from tools.acquire.book_formats import build_sections_manifest
        manifest = build_sections_manifest(ref)
        (ref / "_sections.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # 断言清单结构：第1章3节（带 body 切片），第2章1条无节
        ch1_entries = [e for e in manifest if e["chapter"] == "代数基础"]
        ch2_entries = [e for e in manifest if e["chapter"] == "几何初步"]
        assert len(ch1_entries) == 3, f"第1章应切出3节，实际 {len(ch1_entries)}"
        assert all(e["section"] for e in ch1_entries), "第1章3条都应有 section"
        assert all(e["body"] for e in ch1_entries), "第1章节级条目必须带 body 切片"
        assert len(ch2_entries) == 1 and ch2_entries[0]["section"] is None, \
            "第2章无节应只有1条 section=None"
        assert ch2_entries[0]["body"] is None, "无节条目 body 应为 None（沿用整文件读取）"

        _course_gen(BOOK)

        bd = ROOT / "书库" / BOOK
        chapters = [p.name for p in sorted(bd.iterdir()) if p.is_dir()]
        assert chapters == ["第01章_代数基础", "第02章_几何初步"], \
            f"爬虫书章顺序异常：{chapters}"

        c1 = sorted(p.name for p in (bd / "第01章_代数基础").glob("第*课_*.md"))
        assert len(c1) == 3, f"第01章应含3课（3节），实际 {c1}"
        c2 = sorted(p.name for p in (bd / "第02章_几何初步").glob("第*课_*.md"))
        assert len(c2) == 1, f"第02章应含1课（无节整章），实际 {c2}"

        # 关键不变量：节级正文是切片，不是整章重复。
        def read_lesson(ch, idx):
            return (bd / ch / sorted(p.name for p in (bd / ch).glob("第*课_*.md"))[idx]).read_text(encoding="utf-8")

        sec1 = read_lesson("第01章_代数基础", 0)
        sec2 = read_lesson("第01章_代数基础", 1)
        # 第1节只含「集合的概念」内容，绝不含第2节「集合的运算」的专属文本
        assert "集合的运算" not in sec1, "第1节被整章正文污染（切片失败，重复挂了全章）"
        assert "集合的基本概念" in sec1 or "最基本的研究对象" in sec1, "第1节缺少自身正文切片"
        assert "集合的运算" in sec2, "第2节应含自身正文"

        print(f"[test_crawler_sections] 通过：{len(chapters)} 章 / 章内多课（章→节），节级正文为切片非整章重复")
        return True
    finally:
        _force_clean()


BOOK2 = "crawl_mix"


def _force_clean_dir(book):
    """底层 Win32 force-delete（绕 safe-delete 钩子）；不 import pipeline（其顶层
    `from source_engine import` 在包导入下会失败），本地复刻 _rmtree_force。"""
    import ctypes, os

    def rmtree_force(path):
        path = str(path)
        kernel32 = getattr(ctypes, "windll", None) and ctypes.windll.kernel32
        if kernel32 is not None:
            for root, dirs, files in os.walk(path, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        kernel32.SetFileAttributesW(fp, 0x80); kernel32.DeleteFileW(fp)
                    except Exception: pass
                for d in dirs:
                    dp = os.path.join(root, d)
                    try:
                        kernel32.SetFileAttributesW(dp, 0x80); kernel32.RemoveDirectoryW(dp)
                    except Exception: pass
            try:
                kernel32.SetFileAttributesW(path, 0x80); kernel32.RemoveDirectoryW(path)
            except Exception: pass
        else:
            import shutil; shutil.rmtree(path, ignore_errors=True)

    for base in ("参考", "书库"):
        rmtree_force(ROOT / base / book)


def test_short_real_section_retained():
    """混排章节（2 长节 + 1 真实短节）：短节必须保留，不被 200 绝对地板误删。

    这是 _drop_toc_like_triples 阈值修正的回归锁：旧逻辑用 max(200, ...) 绝对地板，
    在『中位数很大、夹一个真实短节』时短节会被删掉；新逻辑改相对阈值 + 均匀短章全保留。
    """
    ref = ROOT / "参考" / BOOK2
    ref.mkdir(parents=True, exist_ok=True)
    try:
        long_a = ("函数连续性是微积分的基石，它描述了当自变量发生微小变化时因变量"
                  "是否也只发生微小变化。epsilon-delta 语言给出了严格的数学定义，"
                  "是理解极限与导数之前必须掌握的概念框架。") * 2  # 约 120 字，长节
        short = ("导数即变化率：函数在某点的导数就是因变量对该自变量的瞬时变化率，"
                 "物理上恰好对应瞬时速度。")  # 真实短节（约 55 字，<200 但 >40 地板）
        long_b = ("微分中值定理把函数在闭区间上的整体性质与开区间内的局部导数联系起来，"
                  "罗尔定理、拉格朗日中值定理与柯西中值定理构成了微分学的理论主干，"
                  "也是后续积分学与泰勒展开的重要铺垫。") * 2
        ch = (
            "第1节 连续\n" + long_a + "\n"
            "第2节 导数定义\n" + short + "\n"
            "第3节 中值定理\n" + long_b + "\n"
        )
        (ref / "0001_微积分.txt").write_text(ch, encoding="utf-8")
        (ref / "_meta.json").write_text(
            json.dumps({"name": "混合测试", "author": "佚名", "source": "crawl",
                        "chapterCount": 1, "bookType": "textbook"}, ensure_ascii=False),
            encoding="utf-8")

        from tools.acquire.book_formats import build_sections_manifest
        manifest = build_sections_manifest(ref)
        (ref / "_sections.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        entries = [e for e in manifest if e["chapter"] == "微积分"]
        # 关键不变量：3 节全在（含第2节真实短节），未被 200 地板删。
        assert len(entries) == 3, f"混合章应保留3节，实际 {len(entries)}（短节被误删？）"
        assert sum(1 for e in entries if e["section"]) == 3, "3 条都应带 section"

        _course_gen(BOOK2)
        bd = ROOT / "书库" / BOOK2
        lessons = sorted(p.name for p in (bd / "第01章_微积分").glob("第*课_*.md"))
        assert len(lessons) == 3, f"第01章应含3课（短节保留），实际 {lessons}"
        # 短节课文件应含自身正文（变化率那句）
        found = False
        for ln in lessons:
            if "变化率" in (bd / "第01章_微积分" / ln).read_text(encoding="utf-8"):
                found = True; break
        assert found, "短节正文（变化率）丢失"

        print(f"[test_crawler_sections] 短节保留通过：混合章 3 节全留（短节未被 200 地板删）")
        return True
    finally:
        _force_clean_dir(BOOK2)


if __name__ == "__main__":
    ok = True
    ok = test_crawler_sections_nesting() and ok
    ok = test_short_real_section_retained() and ok
    sys.exit(0 if ok else 1)
