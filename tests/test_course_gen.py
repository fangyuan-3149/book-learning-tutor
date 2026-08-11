#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""course_gen 回归测试：markdown → 书库/<书名>/ 嵌套课程，不联网、零新依赖。"""
import json
import sys
import tempfile
from pathlib import Path

# 允许以脚本或模块方式运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'structure'))

from course_gen import generate, _SAMPLE  # noqa: E402


def test_generate_structure():
    tmp = Path(tempfile.mkdtemp(prefix='test_course_gen_'))
    try:
        md = tmp / '数学入门.md'
        md.write_text(_SAMPLE, encoding='utf-8')
        out = tmp / '书库'
        res = generate(md, out_root=out)

        # 章/课数（导言+2 + 2 = 5）
        assert res['chapters'] == 2, res
        assert res['lessons'] == 5, res

        bd = Path(res['book_dir'])
        assert (bd / '00_目录导读.md').exists()
        assert (bd / 'progress.json').exists()

        prog = json.loads((bd / 'progress.json').read_text(encoding='utf-8'))
        assert prog['total_lessons'] == 5
        assert prog['current'] == '第01章_数与运算/第00课_本章导言.md'
        assert all(v['status'] == 'unstarted' for v in prog['lessons'].values())

        # 保真：嵌套标题不丢
        les = bd / '第01章_数与运算' / '第01课_自然数.md'
        txt = les.read_text(encoding='utf-8')
        assert 'a + b = b + a' in txt
        assert '### 进位数制' in txt

        # 目录导读计数 + 去重编号
        toc = (bd / '00_目录导读.md').read_text(encoding='utf-8')
        assert '0 / 5 课' in toc
        assert '第01章 数与运算' in toc          # 显示标题已剥「第一章」
        assert '第01章 第一章' not in toc         # 无重复编号
        print(f"[test_course_gen] 通过：{res['chapters']} 章 / {res['lessons']} 课")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(0 if test_generate_structure() else 1)
