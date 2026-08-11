# Book Learning Tutor (授业)

> Turn any book on your drive into a **personal AI tutor** that actually teaches — lesson by lesson, with Feynman explanations, practice gates, spaced review, and recitation homework. **Your book never leaves your machine.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](./requirements.txt)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-Open%20Standard-9cf.svg)](#)
[![Cross-host](https://img.shields.io/badge/Works%20on-WorkBuddy%20%7C%20Claude%20Code%20%7C%20Copilot%20CLI%20%7C%20Amp%20%7C%20OpenClaw-important.svg)](#)
[![Tests](https://github.com/fangyuan-3149/book-learning-tutor/actions/workflows/tests.yml/badge.svg)](https://github.com/fangyuan-3149/book-learning-tutor/actions/workflows/tests.yml)

**The problem:** a reader just shows you text — you buy books, highlight them, and forget them. Reading isn't learning.
**This skill:** course-ifies a book into bite-sized lessons and walks you through it like a strict-but-kind teacher — it checks your understanding *before* letting you move on, makes you recite the key points, and brings them back for review on a schedule. Progress is saved, so you can close the chat and resume exactly where you left off.

**What it does:**
- 📚 **Course-ifies any book** (PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ) into a structured lesson tree
- 🎓 **Real Feynman teaching** — explains like a teacher, uses analogies, and won't let you advance until a practice gate (≥80%) confirms you understand
- 🔁 **Spaced review + recitation homework** — brings key points back on a schedule and makes you recite from memory
- 💾 **Progress that survives** — close the chat and resume exactly where you left off (`progress.json`)
- 🔒 **Local-first & private** — your book never leaves your machine; no external LLM key
- 🌐 **Cross-host** — runs in WorkBuddy / Claude Code / Copilot CLI / Amp / OpenClaw
- 🔎 **Optional authorized web fetch** — when you have no local book and explicitly allow it, the agent can search public sources for you (no DRM / paywall bypass)

---

## ▶ See it teach (real session)

*The material below is a real lesson the skill generates — from* Flatland *(public domain). This is what the teaching loop feels like:*

**📚 Lesson 1 — "Of the Nature of Flatland"** · *prep sheet: level = intuitive · must-memorize 📌: Flatland is 2D; inhabitants appear to each other only as straight lines; the penny-on-table analogy*

> **Teacher:** Flatland is a world with only **two dimensions** — length and width, no "up". Its people are living geometric shapes (triangles, squares, circles) who slide around on a flat surface but can never rise above or sink below it.
>
> Here's the part that trips everyone up: **in Flatland, you can't see shapes — you only see straight lines.** Watch: put a penny on a table and look down — it's a circle. Now lower your eye to the table's edge, the way a Flatlander would see. The penny collapses into a single straight line. A triangle, a square, a hexagon — all look identical from the edge: just a line of varying length.
>
> **Teacher:** So how do Flatlanders tell a Triangle from a Square? *(practice gate)*
>
> **You:** They can't by sight alone — they feel edges by touch, or sense the angle as a figure moves past?
>
> **Teacher:** 🔒 **Gate passed (≥80%).** Exactly — recognition is by touch/angle, not vision. That's why the social order (shape = class) is both rigid *and* invisible. **Must-memorize 📌:** *no "up" exists; sight shows only a line.*
>
> **📝 Homework:** write one sentence explaining why a Sphere visiting Flatland would be invisible until it intersects the plane. **🗣 Recite:** the penny analogy, from memory, next lesson.

`progress.json` ← lesson 1 marked `learned`, mastery 0.8; chat closed. Next session, *"continue Flatland"* resumes at lesson 2 and reviews lesson 1 first.

> 📂 A full real sample (TOC guide + lesson 1, from *Flatland*) is browsable in [`examples/flatland/`](./examples/flatland/) — no install needed.

---

## Install

```bash
git clone https://github.com/fangyuan-3149/book-learning-tutor.git
cd book-learning-tutor
python setup_env.py            # builds the slim venv (venv_slim/) with all dependencies
# copy the skill into your agent (pick the host you use):
cp -r . ~/.workbuddy/skills/book-learning-tutor/        # WorkBuddy
# cp -r . ~/.claude/skills/book-learning-tutor/         # Claude Code
# cp -r . ~/.config/amazonq/skills/book-learning-tutor/ # Copilot CLI / Amp / OpenClaw (path varies)
```

## Quick start (3 steps)

**1. Prepare a local book** (PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ) — you supply it; you own the responsibility.

**2. One-shot course-ify:**

```bash
python teach.py "<local book path>/your book.pdf"
# or: python tools/acquire/pipeline.py all-local "<local book path>/your book.pdf"
```

It writes a TOC guide + chapter/lesson folders + `progress.json` into `书库/<book>/`.

**3. Start the teaching loop** — just say to your assistant:

```
teach me this book <book>
```

The assistant starts at lesson 1 and runs the "real teacher" rhythm — prep → Feynman → practice gate (≥80%) → homework (write/memorize/practice) → recitation → spaced review. Progress lives in `书库/<book>/progress.json` and resumes even in a new chat.

---

> **Note:** this repo contains **no book content** and stays offline by default — it processes only the local files *you* provide. Optional fetching from public sources happens **only with your explicit authorization** (no DRM / paywall bypass). You bear responsibility for how you use it; code is MIT — details in [`免责声明.md`](./免责声明.md) / [`LICENSE`](./LICENSE).

## What you do (AI role)

1. **Prepare the source book**: the user supplies a local book file (PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ); the skill extracts chapters → 参考/<book>/
2. **Course-ify**: `tools/structure/course_gen.py` consumes 参考/<book>/ directly → chapter/lesson folders + TOC guide → `书库/<book>/` (no intermediate 预处理/)
3. **Lesson-by-lesson teaching loop**: agent-driven (explain → ask → resolve → quiz → check mastery → advance), progress in progress.json

## Architecture iron rules (user-finalized, must hold)

- **Pure-local parsing first**; the default path does **no web crawling / proxying**. Book-source crawling is an **optional capability that complements the local-file main path** (see the Acquisition pipeline section) — it only runs when you supply source rules and explicitly drive it, and you bear all responsibility (see `免责声明.md`).
- **Zero external LLM key**: every "intelligent" step (writing source rules, teaching lesson by lesson) is done by the agent itself; tools only do deterministic work (fetch / replay-verify / persist / pipeline orchestration).
- **The Skill is the only external interface**: other agents only need to know "how to invoke the Skill" + "output lands in `书库/<book>/`", and don't touch internal engine details.

## Core spec · book-library structure (user-finalized)

```
书库/
└── <book>/
    ├── 00_目录导读.md            # whole-book navigation: chapter→lesson index + concept summary
    ├── 第01章_<chapter>/
    │   ├── 第01课_<lesson>.md      # teaching unit (finest grain within a chapter)
    │   └── ...
    └── progress.json             # progress state (per chapter-lesson: learned/mastery)
```

- **No subdivision below chapter/lesson**: a lesson = the smallest teaching unit (a file may contain sub-concepts internally, but no sub-folder).
- Numbered naming (`第01章_章名` / `第01课_课名`) → stable sort, predictable path.
- Model lesson selection: read only "this lesson + TOC guide + progress" at a time, never the rest of the book.

## Teaching engine: Book Learning Tutor single self-contained professional teacher

One skill contains the full teaching engine — material production (what to teach) + prep / Feynman / practice gate / adaptation / spaced review / recitation homework / self-evolution (teach understandably + deeply + force memorization). **No other skill needs loading during teaching**, avoiding "only half loaded → degraded teaching". Timeline:

```
T0 Material production   book → 书库/<book>/ (TOC guide + lesson bodies + figure blocks + progress.json)  deterministic backbone
T1 Smart enrichment       scan weak/stale → search/arxiv/project-code/official docs → write _enrich.md (no break main course)
T2 Real-teacher teaching  prep search → detailed Feynman → practice gate (≥80%) → post-class homework by weakness (write/memorize/practice)
T3 Review·homework check  spaced review (review cards) + check homework & recitation next lesson
T4 Improvement·self-evolve  suggestion buffer → generality filter → stability freeze (cross-host consistent: suggestions first to teaching notes, manually hardened, no host-specific write-back tool)
```

**Real-teacher workflow (every lesson)**: ① prep search + prep sheet (target level / core concepts / **must-memorize 📌** / extension / example plan / homework plan); ② detailed Feynman teaching (figure pairing, confusion comparison table, practice gate ≥80% to advance); ③ post-class assign **write / memorize / practice** homework by weakness (in `作业.md`, check first next time); ④ staged memorization (each lesson's must-memorize in `背诵.md` + checkpoint, forced like course progress).

> Teaching outputs (prep / review cards / recitation / knowledge base / homework / teaching notes / learner profile) all live in **`storage/` inside the skill dir** (auto-adapts to install location, consistent across hosts), not polluting the book library; course-level progress is always `书库/<book>/progress.json` (atomically written back via `pipeline.py progress`). Detailed teaching principles / adaptive strategy / common pitfalls in the skill's `references/teaching_patterns.md`.

## Acquisition pipeline (optional · user-supplied sources)

> The book-source acquisition below (search / download / import_source / discover) is an **optional capability** that complements the local-file main path (`teach.py` / `all-local`). It only runs when you provide source rules in `data/sources/` (the repo ships none) and explicitly drive it — it makes no unsolicited network calls. If you use it, comply with platform norms and bear all responsibility (see `免责声明.md`). Only use URLs you are authorized for, or that the site explicitly allows crawling; not supported for any unauthorized site (including those explicitly forbidding such tools).

```
Step 1 Search    load_sources → multi-source concurrent searchBook → aggregate results (agent-readable)
Step 2 Download  pick a result → getContent chapter by chapter → 参考/<book>/
Step 3 Course-ify  参考/<book>/ → content cleanup + heading tree → 书库/<book>/ nested course (direct read, no 预处理/)
```

**Source pool (local, user-owned):** the crawler reads source rules from a `data/sources/` directory **on your own machine** — the repo **ships none**, so clone-and-run starts empty. You plug in rules three ways: import from a subscription URL (`import_source.py`), let the agent derive a rule by reading a sample page (`discover.py`), or drop your own `active/` rules in. The pipeline then loads whatever you supplied.

| Dir | Meaning |
|---|---|
| `active/` | pure-parse / JS-extract sources you supplied (pipeline default load) |
| `archive/` | full backup you keep (incl. login / Java bridge / browser-needed sources, archived, not run) |
| `discovered/` | new sources the agent derived by reading sample pages (discover.py output) |
| `imported/` | sources you batch-imported and verified from your own subscription URLs (`verified.json`) |

## Toolchain (`tools/`)

| Module | Responsibility | Layer |
|---|---|---|
| `acquire/fetcher.py` | HTTP layer (desktop UA, gbk/gb18030 heuristic decode, 1 QPS per domain) | engine internal |
| `acquire/rules.py` | source-rule evaluation (CSS/XPath/JSONPath/Regex, incl. `@js:` routing, `_self_matches`) | engine internal |
| `acquire/js_bridge.py` | resident Node evaluating `@js:`/`{{java.*}}` (lazy start + process singleton, no browser) | engine internal |
| `acquire/transforms.py` | response-level decrypt hooks (7 AES/DES configs + md5/HMac, no browser) | engine internal |
| `acquire/source_engine.py` | four actions (search/info/toc/content) + resume crawling + fault-tolerant persist | engine internal |
| `acquire/pipeline.py` | pipeline orchestration (search/download/ingest/all-local/all; course-ify via course_gen direct read of 参考/) | engine internal |
| `acquire/import_source.py` | **external entry**: subscription URL → adaptive unpack + survival pre-filter + per-source verify + dead-cause classify | Skill call |
| `acquire/discover.py` | bare URL → agent reads sample page to derive source rule → replay-verify → write `discovered/` | Skill call |
| `structure/course_gen.py` | 参考/<book>/ direct read → heading tree → 书库/<book>/ nested course + TOC guide + progress.json | Skill call |

**External command surface (Skill call)**: `import_source.py <url>`, `discover.py <url>`, `pipeline.py search/download/all-local/all <...>`, `course_gen.py 参考/<book>/ --book <book>`, `selftest.py` / `debug_source.py` / `rule_trace.py` (troubleshoot).

## Environment

- Python 3.13 (or 3.11+); Node 22 only needed when using the "online source JS bridge" (optional, auto-skipped if absent)
- Only pure-parse dependencies (httpx/bs4 etc.), **no browser / no Playwright / no external LLM key**

## License & disclaimer

- **Code license**: this repo (parse / course-ify engine, skill, scripts) is released under **MIT**, see [`LICENSE`](./LICENSE).
- **Book content**: the repo **contains no book text**; the user must supply local book files and bear copyright and compliance responsibility; details in [`免责声明.md`](./免责声明.md).
- **Crawler scripts**: `search` / `download` / `import_source` / `discover` are optional legacy capabilities, used by the user at their own risk, not in the external main path.

## Contributing

Code is MIT — you're free to fork, modify, and redistribute it (keep the license notice). Bug reports, teaching-pattern improvements, and parser fixes are welcome via issues or PRs. The repo deliberately ships **no book content and no book sources**; please don't add any.

---

# 中文版

# 授业（Book Learning Tutor）：书籍课程化 · 逐课教学闭环

> 把一本书变成「目录导读 + 章 + 课」的文件夹课程，由 **agent 自驱** 一课一课精准教学。本仓库**不包含任何书籍内容**，默认仅处理你提供的本地书、无外部 LLM key；仅在**你明确授权且无本地书时**才可能代为从公开来源获取（不绕过 DRM / 付费墙，使用者自担责）。代码以 **MIT 许可**发布，详见 [`LICENSE`](./LICENSE) 与 [`免责声明.md`](./免责声明.md)。

## 项目一句话

**本地书文件 → 课程文件夹 → agent 逐课教学闭环**：普通阅读器只把书「摆出来」给你看，授业则把书变成会查你懂没懂的老师，辅助人类 / AI 高效率学习——知道书籍构造、感知学习进度、一课一精华（去废话冗余）。

**它能做什么：**
- 📚 **把任意书课程化**（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ）→ 结构化课树
- 🎓 **真·费曼教学**：像老师一样讲解、打比方，用练习闸门（≥80%）确认你真懂才放行
- 🔁 **间隔复习 + 背诵作业**：按节奏回放重点，逼你脱稿复述
- 💾 **进度可续**：关掉对话也能从原处接着学（`progress.json`）
- 🔒 **本地优先、隐私**：书不出本机，无外部 LLM key
- 🌐 **跨宿主**：WorkBuddy / Claude Code / Copilot CLI / Amp / OpenClaw 通用
- 🔎 **可选授权联网获取**：无本地书且你明确授权时，agent 可代你检索公开来源（不绕 DRM/付费墙）

## 快速开始（三步）

> 前提：先跑 `python setup_env.py` 一键建好精简 venv（`venv_slim/`）并装齐依赖（详见 [`setup_env.py`](./setup_env.py) 与 `requirements.txt`）；之后所有命令相对仓库根，克隆到任意目录都能跑。

**1. 准备一本本地书**（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ），自行提供，责任在使用者。

**2. 一键课程化**（抽取 → 转 markdown → 生成课程）：

```bash
python teach.py "<本地书路径>/你的书.pdf"
# 或分步：python tools/acquire/pipeline.py all-local "<本地书路径>/你的书.pdf"
```

跑完会在 `书库/<书名>/` 生成「目录导读 + 分章分课 + progress.json」。

**3. 开始逐课教学** —— 直接对助手说：

```
教我这本书 <书名>
```

助手会从第 1 课起，按 **备课 → 费曼教学 → 练习闸门(≥80%) → 作业(写/背/实践) → 背诵 checkpoint → 间隔复习** 的「真老师」节奏带你学完；进度永久记在 `书库/<书名>/progress.json`，新对话也能续上。

## 你要做什么（AI 角色）

1. **准备原书**：使用者自行提供本地书文件（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ）；本技能抽取章节 → 参考/<书名>/
2. **课程化**：`tools/structure/course_gen.py` 直接消费 参考/<书名>/ → 章/课文件夹 + 目录导读 → `书库/<书名>/`（无需中间 预处理/）
3. **逐课教学闭环**：agent 自驱（讲解 → 问疑 → 解疑 → 出题 → 看掌握 → 推进），进度记 `progress.json`

## 架构铁律（必须守住）

- **纯本地解析优先**；对外技能**不做任何网络爬取 / 代理**。书源爬取属可选能力，是对本地文件主路径的补充；使用者若自行使用须自担责（见 `免责声明.md`）。
- **零外部 LLM key**：所有「智能」步骤（写书源规则、逐课教学）由 agent 自身完成；工具只做确定性工作（抓取 / 回放校验 / 落盘 / 管道编排）。
- **Skill 是唯一对外接口**：其他 agent 只需知道「如何调用 Skill」+「产物落在 `书库/<书名>/`」，不接触内部引擎细节。

## 核心规范 · 书库结构

```
书库/
└── <书名>/
    ├── 00_目录导读.md            # 全书导航：章→课索引 + 知识点摘要
    ├── 第01章_<章名>/
    │   ├── 第01课_<课名>.md      # 教学单元（章节内最小粒度）
    │   └── ...
    └── progress.json             # 进度状态（按 章-课 记录已学/掌握度）
```

- **章节之后不再细化**：课 = 最小教学单元（文件内部可分知识点，不拆子文件夹）
- 命名带编号（`第01章_章名` / `第01课_课名`）→ 排序稳定、路径可预测
- 模型选课：一次只读「本课 + 目录导读 + 进度」三件，不碰全书其他内容

## 教学引擎：授业（Book Learning Tutor）单包自包含专业教师

授业一个技能即包含完整教学引擎——教材生产（教什么）+ 备课 / 费曼 / 练习闸门 / 自适应 / 间隔复习 / 背诵作业 / 自进化（教得懂 + 教得深 + 逼你记住）。**教学时不再需要加载别的技能**，避免「只加载一半导致教学降级」。时间线：

```
T0 教材生产   书 → 书库/<书>/（目录导读+分课正文+配图块+progress.json）  确定性主干
T1 智能补强   扫描薄弱/过时处 → 搜索/arxiv/project-code/官方文档 补强 → 写 _enrich.md（不破主课程）
T2 真老师教学 课前检索备课 → 详尽费曼教学 → 练习闸门(≥80%) → 课后按薄弱布置 写/背/实践 作业
T3 复习·作业追查 间隔复习（复习卡）+ 下次课先查作业与背诵
T4 改进·自进化 建议缓冲 → 普适筛选 → 稳定冻结（**跨宿主一致**：建议先入教学笔记，人工固化，不依赖任何宿主特有的写回工具）
```

**真老师工作流（每课必走）**：① 课前检索 + 出备课单（目标层级 / 核心概念 / **必背清单📌** / 扩展 / 例子预案 / 作业预案）；② 详尽费曼教学（配图对照、易混对比表、练习闸门 ≥80% 才推进）；③ 课后按薄弱布置 **写 / 背 / 实践** 三类作业（记 `作业.md`，下次先查）；④ 背诵分阶段（每课必背写入 `背诵.md` + checkpoint，像课程进度一样逼记住）。

> 教学产物（备课 / 复习卡 / 背诵 / 知识库 / 作业 / 教学笔记 / 习惯画像）全存于**技能目录内的 `storage/`**（随安装位置自动适配，跨宿主一致），不污染书库；课程级进度永远是 `书库/<书名>/progress.json`（用 `pipeline.py progress` 命令原子写回）。详细教学原则 / 自适应策略 / 常见陷阱见技能内 `references/teaching_patterns.md`。

## 获取管道（可选 · 自备用源）

> 下文的书源获取（search / download / import_source / discover）属于**可选能力**，是对本地文件主路径（上方 `teach.py` / `all-local`）的补充：只有当你在 `data/sources/` 提供了源规则（仓库不附带）并显式驱动时才运行，**不会主动发起任何网络调用**。使用者若自行使用，须自行遵守平台规范并承担一切责任（见 `免责声明.md`）。仅可使用你已获授权、或该站点明确允许抓取的网址；不支持对任何未授权站点（含明确禁止此类工具访问的站点）的爬取。

```
Step 1 搜索   load_sources → 多源并发 searchBook → 聚合结果（agent 可读）
Step 2 下载   选一条结果 → 逐章 getContent → 参考/<书名>/
Step 3 课程化  参考/<书名>/ → 正文净化 + 标题树 → 书库/<书名>/ 嵌套课程（直读，无 预处理/）
```

**书源池（本地、使用者自备）**：爬虫从**你本机的** `data/sources/` 目录读规则——仓库**不附带任何书源**，clone 下来默认是空的。填入规则有三种方式：从订阅 URL 批量导入（`import_source.py`）、让 agent 读样本页自动推导（`discover.py`）、或自己把规则放进 `active/`。之后 pipeline 才会加载你提供的源。

| 目录 | 含义 |
|---|---|
| `active/` | 你提供的纯解析 / JS 提取源（pipeline 默认加载） |
| `archive/` | 你保存的全量备份（含登录 / Java 桥 / 需浏览器源，归档不跑） |
| `discovered/` | agent 读样本页推导出的新源（discover.py 产物） |
| `imported/` | 你从自有订阅 URL 批量导入并校验的源（`verified.json`） |

## 工具链（`tools/`）

| 模块 | 职责 | 层级 |
|---|---|---|
| `acquire/fetcher.py` | HTTP 层（桌面 UA、gbk/gb18030 启发式解码、每域 1 QPS） | 引擎内部 |
| `acquire/rules.py` | 书源规则求值（CSS/XPath/JSONPath/Regex，含 `@js:` 路由、`_self_matches`） | 引擎内部 |
| `acquire/js_bridge.py` | 常驻 Node 求值 `@js:`/`{{java.*}}`（懒启动 + 进程单例，无浏览器） | 引擎内部 |
| `acquire/transforms.py` | 响应级解密钩子（7 种 AES/DES 配置 + md5/HMac 等，无浏览器） | 引擎内部 |
| `acquire/source_engine.py` | 四大动作（search/info/toc/content）+ 断点续爬 + 容错落盘 | 引擎内部 |
| `acquire/pipeline.py` | 管道编排（search/download/ingest/all-local/all；课程化由 course_gen 直读 参考/） | 引擎内部 |
| `acquire/import_source.py` | **外化入口**：输入订阅 URL → 自适应拆包 + 存活预筛 + 逐源校验 + 死因分类 | Skill 调用 |
| `acquire/discover.py` | 裸网址 → agent 读样本页推导书源规则 → 回放校验 → 落 `discovered/` | Skill 调用 |
| `structure/course_gen.py` | 参考/<书名>/ 直读 → 标题树 → 书库/<书名>/ 嵌套课程 + 目录导读 + progress.json | Skill 调用 |

**对外命令面（Skill 调用）**：`import_source.py <url>`、`discover.py <url>`、`pipeline.py search/download/all-local/all <...>`、`course_gen.py 参考/<书名>/ --book <书名>`、`selftest.py` / `debug_source.py` / `rule_trace.py`（排错）。

## 环境

- Python 3.13（或 3.11+）；Node 22 仅在使用「在线书源 JS 桥」时才需要（可选，缺则自动跳过）
- 仅纯解析依赖（httpx/bs4 等），**无浏览器 / 无 Playwright / 无外部 LLM key**

## 许可与免责

- **代码许可**：本仓库（解析 / 课程化引擎、技能、脚本）以 **MIT 许可**发布，见 [`LICENSE`](./LICENSE)。
- **书籍内容**：仓库**不包含任何书籍正文**，使用者须自行提供本地书文件，并自行承担版权与合规责任；详见 [`免责声明.md`](./免责声明.md)。
- **爬虫脚本**：`search` / `download` / `import_source` / `discover` 为可选遗留能力，使用者自行使用、自担责，不在对外主路径内。

## 共建与贡献

代码以 MIT 发布，你可自由 fork、修改、再分发（保留许可声明即可）。欢迎通过 issue 或 PR 提交 bug 报告、教学规律改进、解析器修复。本仓库**刻意不包含任何书籍内容、也不附带任何书源**，请勿向仓库添加此类内容。
