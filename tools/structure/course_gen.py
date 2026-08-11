#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
course_gen.py —— 授业 管道四阶段·阶段③ 结构生成器

把一本书（参考/<书名>/ 抽取目录 或 手动 markdown 文件）按标题层级
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
- 依赖标准库；HTML 正文净化时惰性使用 bs4（与管道一致）；可 fixture 自测，不依赖外部站。
- 标题→章/课 映射可配置；无合适层级时自动降级（H2→章 / H3→课 / 全文单课）。

用法：
    python course_gen.py 参考/天降/            # 直接吃抽取目录（推荐，无需中间预处理文件）
    python course_gen.py 某书.md                  # 兼容：直接喂 markdown 文件（手动/测试）
    python course_gen.py 参考/天降/ --book 天降 --out 书库
    python course_gen.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 共享：文件名清洗（全仓唯一实现，见 tools/common/sanitize.py）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from sanitize import safe_name

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*#*\s*$')
ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


# ---------------------------------------------------------------------------
# 参考/ → markdown 转换辅助（原 pipeline.convert 的逻辑整体迁入，使 course_gen
# 能直接消费 参考/<书名>/ 抽取目录，废掉常驻的 预处理/ 中间层）
# ---------------------------------------------------------------------------
def _strip_num_prefix(title):
    """去掉标题首部『第N章/节/课』编号词（避免与自动加的 第XX章 重复）。"""
    return re.sub(r"^第[0-9零一二三四五六七八九十百千]+\s*[章章节节节课部分段篇]\s*",
                  "", (title or "")).strip()


def _sanitize_body(text):
    """正文内若以 '#' 起头（如 Python 代码清单注释、被抽进正文的页眉），会被误判为
    markdown 标题→垃圾章。转义行首 '#' 为 '\\#'（渲染为字面 '#'，不触发标题），
    既保真又消除垃圾章。"""
    if not text:
        return ""
    return re.sub(r"(?m)^#", r"\\#", text)


def html_to_text(html):
    """极简 HTML→纯文本（保留段落）。无 '<' 时原样返回（纯文本抽取零开销）；
    含 HTML 时惰性使用 bs4（与管道一致），无 bs4 退化为去标签正则。"""
    if not html or "<" not in html:
        return (html or "").strip()
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return re.sub(r"<[^>]+>", "", html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return re.sub(r"\n{3,}", "\n\n", text)

PROGRESS_VERSION = 1

# 标题前缀「第X章 / 第X节 / 第X课」——文件名叫我们自己的 第XX章 前缀，故剥离避免重复
_NUM_PREFIX = re.compile(r'^第[0-9零一二三四五六七八九十百千]+[章章节节节课部分段]\s*')

# 顶层书名目录命名须与管道（pipeline / figures_to_book / inline_figures）一致，
# 否则 figures/inline 按 书库/<书名> 找不到本目录。统一实现见 tools/common/sanitize.py。
_safe_book = safe_name  # 兼容旧调用点


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
def sanitize(name: str, maxlen: int = 120) -> str:
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
    """执行结构生成（输入为 markdown 文件，兼容手动/测试喂 .md）。返回汇总 dict。"""
    src = Path(input_md)
    if not src.exists():
        raise FileNotFoundError(f'找不到 markdown：{src}')
    text = src.read_text(encoding='utf-8')
    if book_name is None:
        book_name = src.stem
    return _generate_from_text(text, book_name, out_root, chapter_level, lesson_level, dry_run)


def _generate_from_text(text: str,
                        book_name: str,
                        out_root: str | Path = '书库',
                        chapter_level: int = 1,
                        lesson_level: int = 2,
                        dry_run: bool = False) -> dict:
    """结构生成核心：给定全文 markdown 文本，切成章/课并落盘。返回汇总 dict。"""
    book = sanitize(book_name)

    root = _build_tree(text)
    chapters = organize(root, chapter_level, lesson_level)

    out_root = Path(out_root)
    book_dir = out_root / _safe_book(book_name)

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
            # 整章即一个块、无子节（小说常见）：课名用章标题本身，而非"全文"
            lessons = [{'title': ch_disp or ch['title'], 'body': ch['intro']}]
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
            # 全章/全课标题：供 inline 全标题匹配，彻底解耦文件名截断（避免 40 字符截断
            # 导致的目录碰撞 / 子串误绑）。向后兼容：旧 progress.json 缺此字段时 inline 退回截断目录名。
            'chapter': e['chapter'],
            'lesson': e['lesson'],
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
            'book': _safe_book(book_name),
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
# 参考/ 直读：抽取目录 → 书库/<书名>/（替代常驻的 预处理/ 中间层）
# ---------------------------------------------------------------------------
def generate_from_ref(ref_dir: str | Path,
                      book_name: str | None = None,
                      out_root: str | Path = '书库',
                      chapter_level: int = 1,
                      lesson_level: int = 2,
                      dry_run: bool = False) -> dict:
    """直接消费 参考/<书名>/ 抽取目录（_sections.json + NNNN_*.txt + _meta.json），
    组装成与 convert 等价的 markdown，再走 _generate_from_text。无需落盘 预处理/。

    章/节层级与净化（html_to_text + _sanitize_body）与原 pipeline.convert 完全一致，
    故产出课程与原先逐字节等价，嵌套不变量不变。
    """
    src_dir = Path(ref_dir)
    if not src_dir.exists():
        raise FileNotFoundError(f'找不到原书目录（参考/）：{src_dir}')
    meta_p = src_dir / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}

    man_p = src_dir / "_sections.json"
    if man_p.exists():
        manifest = json.loads(man_p.read_text(encoding="utf-8"))
    else:
        # 兼容下载/旧目录：每个 NNNN_*.txt = 一章（小说源每章一文件），section=None
        files = sorted(src_dir.glob("[0-9][0-9][0-9][0-9]_*.txt"))
        manifest = [{"chapter": fp.name[5:-4], "section": None,
                     "title": fp.name[5:-4], "file": fp.name} for fp in files]

    # 按章分组（保持首次出现顺序）
    order = []
    groups = {}
    for e in manifest:
        ch = e.get("chapter") or e.get("title") or "正文"
        if ch not in groups:
            groups[ch] = []
            order.append(ch)
        groups[ch].append(e)

    parts = []
    for ch in order:
        parts.append(f"# {_strip_num_prefix(ch)}\n")  # 章：一级标题
        for e in groups[ch]:
            body = ""
            if e.get("body") is not None:
                # 爬虫/本地抽取路径：节级正文切片已随 _sections.json 落盘，直接消费，
                # 避免整章正文重复挂到每个节下。
                body = _sanitize_body(html_to_text(e["body"]))
            else:
                # 兼容旧清单/无 body 的条目：回退读整文件（章级 section=None 走此分支）。
                fpath = src_dir / e["file"]
                if fpath.exists():
                    body = _sanitize_body(html_to_text(fpath.read_text(encoding="utf-8")))
            if e.get("section"):
                parts.append(f"## {_strip_num_prefix(e['section'])}\n\n{body}\n")  # 节：二级
            else:
                parts.append(f"{body}\n")  # 小说章：正文直接挂章下（→每章一课）
    header = (f"{meta.get('name','')}\n\n"
              f"> 作者：{meta.get('author','')} ｜ 来源：{meta.get('source','')} ｜ "
              f"章节数：{meta.get('chapterCount','')} ｜ 类型：{meta.get('bookType','')}\n\n")
    md = header + "\n".join(parts)
    if book_name is None:
        book_name = src_dir.name
    return _generate_from_text(md, book_name, out_root, chapter_level, lesson_level, dry_run)


# ---------------------------------------------------------------------------
# 漫画课程化（B-25）：原书目录 → 书库/<书名>/ 章/课 + pages/ 原图
# ---------------------------------------------------------------------------
def generate_comic(ref_dir: str | Path,
                   book_name: str | None = None,
                   out_root: str | Path = '书库',
                   dry_run: bool = False) -> dict:
    """把漫画原书目录（参考/<书名>/，每话一个 NNNN_话名/ 文件夹含 pages/ 原图 + transcript.md）
    转成与小说一致的 书库/<书名>/第XX章/第XX课/ 结构：每话 = 一章内的一课，课内 pages/ 存原图、
    transcript.md 保留原图里的对白文字（用户确认漫画已含文字，不另 OCR）。"""
    import shutil
    ref = Path(ref_dir)
    if not ref.exists():
        raise FileNotFoundError(f'找不到原书目录：{ref}')
    if book_name is None:
        book_name = ref.name
    book = sanitize(book_name)
    out_root = Path(out_root)
    book_dir = out_root / _safe_book(book_name)

    # 章文件夹：按前导编号排序
    ch_folders = sorted(
        [p for p in ref.iterdir() if p.is_dir() and re.match(r'^\d+_', p.name)],
        key=lambda p: int(re.match(r'^\d+', p.name).group()))
    if not ch_folders:
        raise ValueError(f'{ref} 下未找到漫画章文件夹（NNNN_话名/）')

    lesson_entries = []
    toc_lines = [f'# {book_name} · 目录导读（漫画）', '', '> 进度：0 / ? 课（未开始）', '',
                 '## 章节索引', '']
    cnum = 0
    for cf in ch_folders:
        cnum += 1
        rest = cf.name.split('_', 1)[1] if '_' in cf.name else cf.name
        ch_title = file_title(rest) or f'第{cnum:02d}章'
        ch_disp = strip_number_prefix(rest) or rest
        ch_dirname = f'第{cnum:02d}章_{ch_title}'
        pages = cf / 'pages'
        n_pages = len([x for x in pages.iterdir() if x.is_file()]) if pages.exists() else 0
        les_dirname = f'第01课_{ch_title}'
        rel = f'{ch_dirname}/{les_dirname}'
        toc_lines.append(f'### 第{cnum:02d}章 {ch_disp}')
        toc_lines.append(f'- [第01课 {ch_disp}]({rel})  —  漫画 {n_pages} 页')
        toc_lines.append('')
        lesson_entries.append({'rel': rel, 'chapter': cf.name, 'lesson': ch_disp, 'pages': pages})

    total = len(lesson_entries)
    toc_lines[2] = f'> 进度：0 / {total} 课（未开始）'
    toc_text = '\n'.join(toc_lines).rstrip() + '\n'

    lessons_map = {e['rel']: {'status': 'unstarted', 'mastery': 0,
                              'unresolved': [], 'quiz': [],
                              'chapter': e['chapter'], 'lesson': e['lesson']}
                   for e in lesson_entries}
    progress = {'version': PROGRESS_VERSION, 'book': book_name,
                'current': lesson_entries[0]['rel'] if lesson_entries else None,
                'total_lessons': total, 'updated': None, 'lessons': lessons_map,
                'bookType': 'comic'}

    if dry_run:
        return {'book': book, 'book_dir': str(book_dir), 'chapters': len(ch_folders),
                'lessons': total, 'toc': toc_text, 'comic': True, 'dry_run': True}

    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / '00_目录导读.md').write_text(toc_text, encoding='utf-8')
    (book_dir / 'progress.json').write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    for e in lesson_entries:
        les_dir = book_dir / e['rel']
        les_dir.mkdir(parents=True, exist_ok=True)
        # 复制原图（书库自包含）
        src_pages = e['pages']
        if src_pages.exists():
            dst_pages = les_dir / 'pages'
            dst_pages.mkdir(parents=True, exist_ok=True)
            for img in sorted(src_pages.iterdir()):
                if img.is_file():
                    shutil.copy2(img, dst_pages / img.name)
        # transcript：保留原图里的对白文字，不另 OCR
        src_tr = src_pages.parent / 'transcript.md'
        tr = src_tr.read_text(encoding='utf-8') if src_tr.exists() else f'# {e["lesson"]}\n'
        (les_dir / 'transcript.md').write_text(tr, encoding='utf-8')

    return {'book': book, 'book_dir': str(book_dir), 'chapters': len(ch_folders),
            'lessons': total, 'comic': True, 'dry_run': False}


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

        # 小说风格：章无子节 → 章本身即一课（覆盖 generate 的「整章无子节」分支）
        nov = tmp / '测试小说.md'
        nov.write_text("# 第一章 风起\n\n夜色笼罩着小镇，少年推开了那扇斑驳的木门。\n\n"
                       "# 第二章 云涌\n\n远方传来战鼓，命运自此转折。\n", encoding='utf-8')
        nres = generate(nov, out_root=out)
        assert nres['chapters'] == 2, f"小说章数应为2，实际 {nres['chapters']}"
        assert nres['lessons'] == 2, f"小说无子节→每章一课，应为2，实际 {nres['lessons']}"
        nbook = Path(nres['book_dir'])
        assert (nbook / '第01章_风起' / '第01课_风起.md').exists(), '小说章未成为课'
        nprog = json.loads((nbook / 'progress.json').read_text(encoding='utf-8'))
        assert nprog['current'] == '第01章_风起/第01课_风起.md', nprog['current']
        nles = (nbook / '第01章_风起' / '第01课_风起.md').read_text(encoding='utf-8')
        assert '夜色笼罩着小镇' in nles, '小说课未保真原文'

        # 漫画课程化自测（离线 fixture：假原书目录 + 假图）
        ref = tmp / '漫画书'
        cf = ref / '0001_第一话'
        (cf / 'pages').mkdir(parents=True)
        (cf / 'pages' / '001.jpg').write_bytes(b'\xff\xd8\xff\xd8jpg')
        (cf / 'pages' / '002.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        (cf / 'transcript.md').write_text('# 第一话\n\n（对白见原图）\n', encoding='utf-8')
        cres = generate_comic(ref, out_root=out)
        assert cres['chapters'] == 1 and cres['lessons'] == 1, cres
        cbook = Path(cres['book_dir'])
        assert (cbook / '第01章_第一话' / '第01课_第一话' / 'pages' / '001.jpg').exists(), '漫画页未复制'
        assert (cbook / '第01章_第一话' / '第01课_第一话' / 'transcript.md').exists(), '缺 transcript'
        cprog = json.loads((cbook / 'progress.json').read_text(encoding='utf-8'))
        assert cprog['bookType'] == 'comic' and cprog['total_lessons'] == 1

        if verbose:
            print('[course_gen] selftest 通过：'
                  f'小说 {res["chapters"]} 章 / {res["lessons"]} 课，'
                  f'漫画 {cres["chapters"]} 章 / {cres["lessons"]} 课（每话=一课），'
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
    p.add_argument('input', nargs='?', help='参考/<书名>/ 目录 或 任意 markdown 文件')
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

    inp = Path(args.input)
    # 漫画原书目录（参考/<书名>/，含 NNNN_话名/pages/）：自动走漫画课程化
    if inp.is_dir() and any(p.is_dir() and (p / 'pages').exists() for p in inp.iterdir()):
        res = generate_comic(inp, book_name=args.book, out_root=args.out,
                             dry_run=args.dry_run)
        print(f"✅ 漫画生成完成：{res['chapters']} 章 / {res['lessons']} 课（每话=一课）")
        print(f"   目录：{res['book_dir']}")
        return 0
    # 文本原书目录（参考/<书名>/，含 _sections.json 或 NNNN_*.txt）：直接消费，无需 预处理/
    if inp.is_dir():
        if (inp / "_sections.json").exists() or list(inp.glob("[0-9][0-9][0-9][0-9]_*.txt")):
            res = generate_from_ref(inp, book_name=args.book, out_root=args.out,
                                    dry_run=args.dry_run)
            print(f"✅ 生成完成（参考/直读）：{res['chapters']} 章 / {res['lessons']} 课")
            print(f"   目录：{res['book_dir']}")
            if res.get('first_lesson'):
                print(f"   首课：{res['first_lesson']}")
            return 0
        p.error(f'输入目录 {inp} 既不是漫画原书布局（含 NNNN_话名/pages/）'
                f'也不是文本原书布局（含 _sections.json / NNNN_*.txt）')

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
