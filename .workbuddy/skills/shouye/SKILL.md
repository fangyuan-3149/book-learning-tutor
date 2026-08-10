---
name: 授业 (shouye)
description: 把使用者自行提供的本地书（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ）或本地资料课程化，并逐课交互式带人类学习。当用户说「学这本书 <本地路径> / 把这本 PDF 课程化 / 教我这本书」时调用。本技能不联网、不爬取、不提供任何书源或网页源，仅处理使用者已提供的本地文件。
agent_created: true
---

# 授业 · 课程化逐课教学

把一本书变成「目录导读 + 按章分课」的课程，再由使用者逐课交互式学完。面向人类学习。

所有处理**仅针对使用者已提供的本地文件**。本技能不联网、不爬取、不代理，也不提供任何书源或网页源。

## 声明（摘要）

- 本技能**不包含、不支持任何爬取 / 代理 / 远程获取**行为；任何获取内容的行为由使用者自行完成。
- 使用者须**自行提供书文件 / 资料**，并自行遵守所在国家 / 地区的法律法规与平台规范。
- 本技能以「原样」提供，采用**非商业性使用**许可。完整条款见仓库根 `免责声明.md`。

> 仓库内保留的爬虫 / 书源脚本（如 `search` / `download` / `import_source` / `aggregate` / `discover`）为**使用者自行使用、自担责**的工具；本技能的主路径不依赖它们，技能支持的入口是下文的 `all-local`（处理使用者已提供的本地文件）。

---

## 一、如何调用（使用者说一句即可）

触发语示例：

- 「学这本书 `E:/books/xxx.pdf`」
- 「把这本 EPUB 课程化」
- 「教我这本书」（并给出本地文件路径）

接到请求后，按下方「命令」直接执行；无需了解内部结构。

## 二、命令（在项目根 `E:\授业` 下执行）

Python 使用项目 venv：
`C:/Users/陌下/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
（外部仓库请改用该仓库自身的 Python；命令路径保持不变。）

### 1. 本地一键（推荐）

把一本本地书直接变成课程：

```bash
python tools/acquire/pipeline.py all-local <书文件路径> [--name 书名]
```

自动完成：抽取 → 转 markdown → 生成课程。产物落在 `书库/<书名>/`。
示例：

```bash
python tools/acquire/pipeline.py all-local "E:/books/Flatland.epub"
```

### 2. 分步执行（需要微调时）

```bash
# ① 本地书 → 参考/<书名>/（抽取章节）
python tools/acquire/pipeline.py ingest <文件或目录> [--name 书名]

# ② 参考/<书名>/ → 预处理/<书名>.md（净化、定章/节层级）
python tools/acquire/pipeline.py convert <书名>

# ③ 预处理/<书名>.md → 书库/<书名>/（生成课程 + progress.json）
python tools/structure/course_gen.py 预处理/<书名>.md --book <书名>
```

- **扫描版判定**：仅 PDF/DJVU 文本层过薄时标 `needs_ocr` 并尝试本地 OCR 钩子；无 OCR 环境则保留标记、不强制。
- **书籍类型**：任一章含节 → `textbook`（课文，每节一课）；否则 → `novel`（小说，每章一课）。可由 `course_gen.py` 的 `--chapter-level` / `--lesson-level` 调整标题层级映射。

### 3. 自检 / 回归

```bash
python tools/acquire/pipeline.py selftest
python tools/acquire/book_formats.py --selftest
python tools/structure/course_gen.py --selftest
```

---

## 三、产物落点（使用者只需关心这个）

| 目录 | 内容 |
|---|---|
| `参考/<书名>/` | 原书抽取结果（`_sections.json` / `_meta.json`，供对照） |
| `预处理/<书名>.md` | 净化后的全书 markdown |
| `书库/<书名>/` | **终态课程**：`00_目录导读.md` + `第XX章_章名/第XX课_课名.md` + `progress.json` |

---

## 四、教学闭环（直接执行，不要写状态机脚本）

1. 读 `00_目录导读.md`，问使用者「从哪一课开始？」（首次默认第 01 课）。
2. 每课循环：
   - **a 讲解**：把本课讲得易懂——类比、例子、去废话。
   - **b 问疑**：「这节课哪里没懂？没有就回『无』。」
   - **c 解疑**：针对性补充，循环到使用者说「懂了」。
   - **d 出题**：无疑后按 Bloom 认知分层出 2–4 题（记忆 / 理解 / 应用 / 分析）。
   - **e 看掌握**：判分讲评；仍有问题回 c。
   - **f 推进**：写回 `progress.json`，自动进下一课。
3. 全书完成 → 汇总掌握度报告。

**上下文纪律**：每次只加载「本课 + 目录导读 + 进度」三件，绝不塞全书。

### progress.json 结构

```json
{
  "book": "<书名>",
  "current": "第01章_章名/第01课_课名",
  "lessons": {
    "第01章_章名/第01课_课名": {"status": "done", "mastery": 0.9, "unresolved": [], "quiz": []}
  }
}
```

---

## 五、纪律

- 每步 改 → 测 → 提交。
- 遇到产物不符合预期，先看 `参考/<书名>/_meta.json` 的 `bookType` / `needs_ocr` 再判断。
