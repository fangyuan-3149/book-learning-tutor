# Book Learning Tutor (授业): Course-ify Books · Lesson-by-Lesson Teaching Loop

> Established 2026-08-06. Turns a book into a folder-based course ("TOC guide" + chapters + lessons), taught lesson by lesson by an **agent-driven** teacher — zero token waste.
> ⚠️ **Disclaimer**: this repo **contains and provides no book content**; by default it does not go online on its own, and only when **the user explicitly authorizes and has no local book** may it fetch from public sources on their behalf (without bypassing DRM / paywalls); the user must supply a local book or authorize acquisition and bear the responsibility. Code is released under **MIT** (see [`LICENSE`](./LICENSE)); book-content responsibility in [`免责声明.md`](./免责声明.md).
> By default this repo **only processes the local book files the user supplies**, with no external LLM key; **when the user explicitly authorizes and has no local book**, it may search public sources and fetch via the project's acquisition tools (user bears responsibility, no DRM / paywall bypass). The parsing and course-ification engine runs purely locally.

## One-line summary

**Local book file → course folder → agent lesson-by-lesson teaching loop**, helping humans / AI learn efficiently: understand the book's structure, sense learning progress, one essence per lesson (no fluff).

## Quick start (3 steps)

> Prerequisite: first run `python setup_env.py` to build the slim venv (`venv_slim/`) with all dependencies (see [`setup_env.py`](./setup_env.py) and `requirements.txt`); afterward all commands are relative to the repo root and run from any cloned directory.

**1. Prepare a local book** (PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ) — supplied by the user, responsibility on the user.

**2. One-shot course-ify** (extract → convert to markdown → generate course):

```bash
python teach.py "<local book path>/your book.pdf"
# or stepwise: python tools/acquire/pipeline.py all-local "<local book path>/your book.pdf"
```

On finish it generates "TOC guide + chapters/lessons + progress.json" in `书库/<book>/`.

**3. Start lesson-by-lesson teaching** — just say to the assistant:

```
teach me this book <book>
```

The assistant starts from lesson 1 and walks you through with the "real teacher" rhythm — prep → Feynman teaching → practice gate (≥80%) → homework (write/memorize/practice) → recitation checkpoint → spaced review; progress is permanently stored in `书库/<book>/progress.json` and resumes even in a new chat.

## What you do (AI role)

1. **Prepare the source book**: the user supplies a local book file (PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ); the skill extracts chapters → 参考/<book>/
2. **Course-ify**: `tools/structure/course_gen.py` consumes 参考/<book>/ directly → chapter/lesson folders + TOC guide → `书库/<book>/` (no intermediate 预处理/)
3. **Lesson-by-lesson teaching loop**: agent-driven (explain → ask → resolve → quiz → check mastery → advance), progress in progress.json

## Architecture iron rules (user-finalized, must hold)

- **Pure-local parsing first**; the external skill does **no web crawling / proxying**. Book-source crawling is a legacy capability, outside the external skill's scope; if the user uses it themselves they bear responsibility (see `免责声明.md`).
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

## Acquisition pipeline (optional · user responsibility)

> ⚠️ The book-source acquisition below (search / download / import_source / discover) is a **legacy optional capability**: this repo's main path is the `teach.py` / `all-local` above (processing the local files you provided). The crawler scripts make **no outward promise of web crawling / proxying**; if the user uses them, they must comply with platform norms and bear all responsibility (see `免责声明.md`). Only use URLs you are authorized for, or that the site explicitly allows crawling; not supported for any unauthorized site (including those explicitly forbidding such tools).

```
Step 1 Search    load_sources → multi-source concurrent searchBook → aggregate results (agent-readable)
Step 2 Download  pick a result → getContent chapter by chapter → 参考/<book>/
Step 3 Course-ify  参考/<book>/ → content cleanup + heading tree → 书库/<book>/ nested course (direct read, no 预处理/)
```

**Source pool tiers** (`data/sources/`):

| Dir | Meaning |
|---|---|
| `active/` | pure-parse / JS-extract sources (pipeline default load, verified usable) |
| `archive/` | full backup (incl. login / Java bridge / browser-needed sources, archived, not run) |
| `discovered/` | new sources the agent derived by reading sample pages (discover.py output) |
| `imported/` | sources `import_source.py` batch-imported and verified from subscription URLs (`verified.json`) |

> Current `imported/verified.json` = **143 unique usable sources** (union across imports; survival pre-filter + per-source L1 verify + dead-cause classification).

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

## Working discipline

- Each step "change → test → git commit", precisely reversible on failure
- The user supplies book/web sources; responsibility on the user (no copyright discipline set, to avoid the agent misreading and over-refusing)

---

# 中文版

# 授业（Book Learning Tutor）：书籍课程化 · 逐课教学闭环

> 2026-08-06 建立。把一本书变成「目录导读 + 章 + 课」的文件夹课程，由 **agent 自驱** 一课一课精准教学，token 零浪费。
> ⚠️ **免责声明**：本仓库**不包含、不提供任何书籍内容**；默认不主动联网，仅在**使用者明确授权且无本地书时**可代为从公开来源获取（不绕过 DRM / 付费墙），使用者须自行提供本地书或授权获取并自担责。代码以 **MIT 许可**发布（见 [`LICENSE`](./LICENSE)），书籍内容责任见 [`免责声明.md`](./免责声明.md)。
> 本仓库**默认仅处理使用者自行提供的本地书文件**，无外部 LLM key；**经使用者明确授权且无本地书时**，可代为联网检索公开来源并用项目抓取工具获取（使用者自担责，不绕过 DRM / 付费墙）。解析与课程化引擎纯本地运行。

## 项目一句话

**本地书文件 → 课程文件夹 → agent 逐课教学闭环**，辅助人类 / AI 高效率学习：知道书籍构造、感知学习进度、一课一精华（去废话冗余）。

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

## 架构铁律（用户定稿，必须守住）

- **纯本地解析优先**；对外技能**不做任何网络爬取 / 代理**。书源爬取属遗留能力，不在对外技能范围内；使用者若自行使用须自担责（见 `免责声明.md`）。
- **零外部 LLM key**：所有「智能」步骤（写书源规则、逐课教学）由 agent 自身完成；工具只做确定性工作（抓取 / 回放校验 / 落盘 / 管道编排）。
- **Skill 是唯一对外接口**：其他 agent 只需知道「如何调用 Skill」+「产物落在 `书库/<书名>/`」，不接触内部引擎细节。

## 核心规范 · 书库结构（用户定稿）

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

## 获取管道（可选 · 自担责）

> ⚠️ 下文的书源获取（search / download / import_source / discover）属于**遗留的可选能力**：本仓库主路径是上方的 `teach.py` / `all-local`（处理你已提供的本地文件）。爬虫脚本**不做任何网络爬取 / 代理**的对外承诺；若使用者自行使用，须自行遵守平台规范并承担一切责任（见 `免责声明.md`）。仅可使用你已获授权、或该站点明确允许抓取的网址；不支持对任何未授权站点（含明确禁止此类工具访问的站点）的爬取。

```
Step 1 搜索   load_sources → 多源并发 searchBook → 聚合结果（agent 可读）
Step 2 下载   选一条结果 → 逐章 getContent → 参考/<书名>/
Step 3 课程化  参考/<书名>/ → 正文净化 + 标题树 → 书库/<书名>/ 嵌套课程（直读，无 预处理/）
```

**书源池分层**（`data/sources/`）：

| 目录 | 含义 |
|---|---|
| `active/` | 纯解析 / JS 提取源（pipeline 默认加载，已验证可用） |
| `archive/` | 全量备份（含登录 / Java 桥 / 需浏览器源，归档不跑） |
| `discovered/` | agent 读样本页推导出的新源（discover.py 产物） |
| `imported/` | `import_source.py` 从订阅 URL 批量导入并校验的可用源（`verified.json`） |

> 当前 `imported/verified.json` = **143 条唯一可用源**（跨历次导入 union；存活预筛 + 逐源 L1 校验 + 死因分类）。

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

## 工作纪律

- 每步「改 → 测 → git commit」，出问题可精确回溯
- 使用者自行提供书/网页源，责任在使用者（不设版权纪律，避免 agent 误读而过度拒答）
