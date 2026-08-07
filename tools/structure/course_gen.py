#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
course_gen.py —— 授业 管道四阶段·阶段③ 结构生成器

把一本书的 markdown（预处理/<书名>.md，来自获取管道 Step3）按标题层级
切成「章 / 课」，生成可逐课精学的课程文件夹：

    书库/<书名>/
    ├── 00_目录导读.md          章→课索引 + 每课一句话摘要
    ├── progress.json           进度（全部 未学，current=第一课）
    └── 第01章_章名/
        ├── 第01课_课名.md       原文保真（含嵌套标题，不丢原文）
        └── 第02课_课名.md
    └── 第02章_章名/ ...

设计铁律（见 计划书 / 工作记忆）：
- 生成器只「搬运原文」，精华提炼交给教学闭环（agent 自驱），故每课 .md = 原文保真。
- 零新依赖（仅标准库）；可 fixture 自测，不依赖外部站。
- 标题→章/课 映射可配置；无合适层级时自动降级（H2→章 / H3→课 / 全文单课）。

用法：
    python course_gen.py 预处理/天降.md
    python course_gen.py 预处理/天降.md --book 天降 --out 书库
    python course_gen.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')

PROGRESS_VERSION = 1

# 标题前缀「第X章 / 第X节 / 第X课」——文件名叫我们自己的 第XX章 前缀，故剥离避免重复
_NUM_PREFIX = re.compile(r'^第[0-9零一二三四五六七八九十百千]+[章章节节节课部分段]\s*')


def strip_number_prefix(title: str) -> str:
    """去掉标题首部的『第N章/节/课』编号词（仅用于文件名，目录导读保留原文）。"""
    return _NUM_PREFIX.sub('', title or '').strip()


def file_title(title: str) -> str:
    """文件名用的章/课标题：先剥编号前缀，清洗；剥空了则退回原文清洗。"""
    s = sanitize(strip_number_prefix(title))
    if s == '未命名':
        s = sanitize(title)
    return s


# ---------------------------------------------------------------------------
# 标题解析（构建标题树，保证嵌套标题「原文保真」）
# ---------------------------------------------------------------------------
def _build_tree(text: str) -> dict:
    """把 markdown 解析成标题树。

    节点 = {level, title, children:[...], text:[行...]}。
    - text 是该节点下、其第一个子标题之前的原始行（不含标题行本身）。
    - 子标题按层级入树；更深层标题成为更浅层的后代。
    这样：章的 intro = 章节点自身 text（第一个课之前的内容）；
          课的 body = 课节点 text + 全部后代子树（含嵌套 ### 等，保真）。
    """
    lines = text.split('\n')
    heads = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            heads.append((len(m.group(1)), m.group(2).strip(), i))
    root = {'level': 0, 'title': None, 'children': [], 'text': []}
    stack = [root]
    prev = 0
    for (level, title, idx) in heads:
        stack[-1]['text'].extend(lines[prev:idx])  # 上一个节点到本标题之间的正文
        while len(stack) > 1 and stack[-1]['level'] >= level:
            stack.pop()
        node = {'level': level, 'title': title, 'children': [], 'text': []}
        stack[-1]['children'].append(node)
        stack.append(node)
        prev = idx + 1
    stack[-1]['text'].extend(lines[prev:])  # 末尾正文
    return root


def _all_levels(root: dict) -> list[int]:
    levels = set()
    def walk(n):
        for c in n['children']:
            levels.add(c['level'])
            walk(c)
    walk(root)
    return sorted(levels)


def _render_children(node: dict) -> list[str]:
    """递归渲染某节点的全部后代子树为原始 markdown 行（含后代标题行，保真）。"""
    out = []
    for child in node['children']:
        out.append('#' * child['level'] + ' ' + child['title'])
        out.extend(child['text'])
        out.extend(_render_children(child))
    return out


def _resolve_levels(root: dict, chapter_level: int, lesson_level: int):
    """当文档缺少期望层级时，自动降级到实际存在的层级。"""
    present = _all_levels(root)
    if not present:
        return None, None  # 全文档无标题
    chap = chapter_level if chapter_level in present else present[0]
    if lesson_level in present:
        less = lesson_level
    elif len(present) > 1:
        deeper = [l for l in present if l > chap]
        less = deeper[0] if deeper else None
    else:
        less = None
    return chap, less


def _body_text(body: list[str]) -> str:
    return '\n'.join(body).strip()


def _first_line_summary(body: list[str], maxlen: int = 60) -> str:
    for line in body:
        t = line.strip()
        if t and not HEADING_RE.match(t):
            t = re.sub(r'\s+', ' ', t)
            return t if len(t) <= maxlen else t[: maxlen - 1].rstrip() + '…'
    return '（详见课文）'


# ---------------------------------------------------------------------------
# 组织成 章/课 树
# ---------------------------------------------------------------------------
def organize(root: dict, chapter_level: int, lesson_level: int) -> list[dict]:
    """返回 chapters=[{title, intro, lessons:[{title, body}]}]。"""
    chap, less = _resolve_levels(root, chapter_level, lesson_level)
    if chap is None:
        # 无标题：整本作为一个章、一课
        return [{'title': '全书', 'intro': [], 'lessons': [{'title': '全文', 'body': list(root['text'])}]}]

    chapters: list[dict] = []
    for ch_node in [c for c in root['children'] if c['level'] == chap]:
        intro = list(ch_node['text'])
        lessons = []
        if less is not None:
            for les_node in [c for c in ch_node['children'] if c['level'] == less]:
                # 课 body = 课自身正文 + 全部嵌套后代（保真）
                body = list(les_node['text']) + _render_children(les_node)
                lessons.append({'title': les_node['title'], 'body': body})
        chapters.append({'title': ch_node['title'], 'intro': intro, 'lessons': lessons})
    return chapters


# ---------------------------------------------------------------------------
# 文件名清洗
# ---------------------------------------------------------------------------
def sanitize(name: str, maxlen: int = 40) -> str:
    name = (name or '').strip()
    name = ILLEGAL_RE.sub('_', name)
    name = re.sub(r'\s+', '_', name)  # 空白压成单下划线，路径稳定
    name = name.strip('._ ')
    if not name:
        name = '未命名'
    if len(name) > maxlen:
        name = name[:maxlen].rstrip('._ ')
    return name


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def generate(input_md: str | Path,
             book_name: str | None = None,
             out_root: str | Path = '书库',
             chapter_level: int = 1,
             lesson_level: int = 2,
             dry_run: bool = False) -> dict:
    """执行结构生成。返回汇总 dict（章节数、课数、输出目录）。"""
    src = Path(input_md)
    if not src.exists():
        raise FileNotFoundError(f'找不到预处理 markdown：{src}')
    text = src.read_text(encoding='utf-8')
    if book_name is None:
        book_name = src.stem
    book = sanitize(book_name)

    root = _build_tree(text)
    chapters = organize(root, chapter_level, lesson_level)

    out_root = Path(out_root)
    book_dir = out_root / book

    # 收集课（相对路径 + 摘要）
    lesson_entries = []  # (rel_path, chapter_title, lesson_title, summary, body_text)
    toc_lines = [f'# {book_name} · 目录导读', '', '> 进度：0 / ? 课（未开始）', '',
                 '## 章节索引', '']

    cnum = 0
    for ch in chapters:
        cnum += 1
        ch_title = file_title(ch['title']) or f'第{cnum:02d}章'
        ch_disp = strip_number_prefix(ch['title']) or ch['title']
        ch_dirname = f'第{cnum:02d}章_{ch_title}'
        toc_lines.append(f'### 第{cnum:02d}章 {ch_disp}')

        lessons = list(ch['lessons'])
        # 章导言：有 intro 时，作为「导言」课（编号 00）；否则正常从 01 起
        intro_text = _body_text(ch['intro'])
        has_intro = False
        if intro_text and not lessons:
            lessons = [{'title': '全文', 'body': ch['intro']}]
        elif intro_text and lessons:
            lessons = [{'title': '本章导言', 'body': ch['intro']}] + lessons
            has_intro = True

        if not lessons:
            # 空章：给一个占位课，避免章节索引断档
            lessons = [{'title': '（本章暂无内容）', 'body': []}]

        start = 0 if has_intro else 1
        for i, les in enumerate(lessons):
            lnum = start + i
            les_title = file_title(les['title']) or f'第{lnum:02d}课'
            les_disp = strip_number_prefix(les['title']) or les['title']
            les_filename = f'第{lnum:02d}课_{les_title}.md'
            rel = f'{ch_dirname}/{les_filename}'
            body = _body_text(les['body'])
            summary = _first_line_summary(les['body'])
            lesson_entries.append({
                'rel': rel,
                'chapter': ch['title'],
                'lesson': les['title'],
                'summary': summary,
                'body': body,
            })
            toc_lines.append(f'- [第{lnum:02d}课 {les_disp}]({rel})  —  {summary}')

        toc_lines.append('')  # 章间空行

    total = len(lesson_entries)
    # 回填进度计数
    toc_lines[2] = f'> 进度：0 / {total} 课（未开始）'
    toc_text = '\n'.join(toc_lines).rstrip() + '\n'

    # progress.json
    lessons_map = {}
    for e in lesson_entries:
        lessons_map[e['rel']] = {
            'status': 'unstarted',
            'mastery': 0,
            'unresolved': [],
            'quiz': [],
        }
    progress = {
        'version': PROGRESS_VERSION,
        'book': book_name,
        'current': lesson_entries[0]['rel'] if lesson_entries else None,
        'total_lessons': total,
        'updated': None,
        'lessons': lessons_map,
    }

    if dry_run:
        return {
            'book': book,
            'book_dir': str(book_dir),
            'chapters': len(chapters),
            'lessons': total,
            'toc': toc_text,
            'first_lesson': lesson_entries[0]['rel'] if lesson_entries else None,
            'dry_run': True,
        }

    # 落盘
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / '00_目录导读.md').write_text(toc_text, encoding='utf-8')
    (book_dir / 'progress.json').write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    for e in lesson_entries:
        f = book_dir / e['rel']
        f.parent.mkdir(parents=True, exist_ok=True)
        # 原文保真：课文件 = 课标题 + 原文正文
        content = f'# {e["lesson"]}\n\n{e["body"]}\n' if e['body'] else f'# {e["lesson"]}\n'
        f.write_text(content, encoding='utf-8')

    return {
        'book': book,
        'book_dir': str(book_dir),
        'chapters': len(chapters),
        'lessons': total,
        'first_lesson': lesson_entries[0]['rel'] if lesson_entries else None,
        'dry_run': False,
    }


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
_SAMPLE = """# 第一章 数与运算

本章介绍自然数与四则运算的基本性质。

## 第一节 自然数

自然数是从 0 开始的整数序列：0, 1, 2, 3, ……

加法满足交换律：a + b = b + a。

### 进位数制

十进制每位满十进一。

## 第二节 四则运算

乘法是加法的简便形式。

除法是乘法的逆运算。

# 第二章 代数初步

## 第一节 方程

含有未知数的等式叫做方程。

## 第二节 函数

函数描述输入到输出的映射关系。
"""


def selftest(verbose: bool = True) -> bool:
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix='course_gen_selftest_'))
    try:
        md = tmp / '测试数学书.md'
        md.write_text(_SAMPLE, encoding='utf-8')
        out = tmp / '书库'
        res = generate(md, out_root=out)

        # 断言
        assert res['chapters'] == 2, f"章数应为2，实际 {res['chapters']}"
        assert res['lessons'] == 5, f"课数应为5（导言+2+2），实际 {res['lessons']}"

        book_dir = Path(res['book_dir'])
        assert (book_dir / '00_目录导读.md').exists(), '缺目录导读'
        assert (book_dir / 'progress.json').exists(), '缺 progress.json'

        prog = json.loads((book_dir / 'progress.json').read_text(encoding='utf-8'))
        assert prog['total_lessons'] == 5
        assert prog['current'] == '第01章_数与运算/第00课_本章导言.md', \
            f"current 应为导言课，实际 {prog['current']}"
        assert all(v['status'] == 'unstarted' for v in prog['lessons'].values())

        # 保真：课文件含原文
        les1 = book_dir / '第01章_数与运算/第01课_自然数.md'
        assert les1.exists(), '缺 自然数 课文件'
        txt = les1.read_text(encoding='utf-8')
        assert 'a + b = b + a' in txt, '课文件未保真原文'
        assert '### 进位数制' in txt, '嵌套标题未保真'

        # 目录导读含索引
        toc = (book_dir / '00_目录导读.md').read_text(encoding='utf-8')
        assert '0 / 5 课' in toc, '目录导读进度计数错误'
        assert '第01章 数与运算' in toc

        if verbose:
            print('[course_gen] selftest 通过：'
                  f'{res["chapters"]} 章 / {res["lessons"]} 课，'
                  f'首课={prog["current"]}')
        return True
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description='授业 结构生成器：markdown → 书库/<书名>/ 嵌套课程')
    p.add_argument('input', nargs='?', help='预处理/<书名>.md 路径')
    p.add_argument('--book', help='书名（默认取文件名 stem）')
    p.add_argument('--out', default='书库', help='输出根目录（默认 书库）')
    p.add_argument('--chapter-level', type=int, default=1, help='章标题层级（默认 1=#）')
    p.add_argument('--lesson-level', type=int, default=2, help='课标题层级（默认 2=##）')
    p.add_argument('--dry-run', action='store_true', help='只打印结构不落盘')
    p.add_argument('--selftest', action='store_true', help='运行内置自测')
    args = p.parse_args(argv)

    if args.selftest:
        return 0 if selftest() else 1

    if not args.input:
        p.error('未指定 input，且未加 --selftest')

    res = generate(args.input, book_name=args.book, out_root=args.out,
                   chapter_level=args.chapter_level, lesson_level=args.lesson_level,
                   dry_run=args.dry_run)
    print(f"✅ 生成完成：{res['chapters']} 章 / {res['lessons']} 课")
    print(f"   目录：{res['book_dir']}")
    if res.get('first_lesson'):
        print(f"   首课：{res['first_lesson']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
