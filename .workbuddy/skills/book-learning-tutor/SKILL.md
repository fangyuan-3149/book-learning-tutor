---
name: 授业 (Book Learning Tutor)
description: 把使用者自行提供的本地书（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ）或本地资料课程化，并逐课交互式带人类学习。当用户说「学这本书 <本地路径> / 把这本 PDF 课程化 / 教我这本书」时调用。本技能不联网、不爬取、不提供任何书源或网页源，仅处理使用者已提供的本地文件。
agent_created: true
---

# 授业 · 课程化逐课教学

把一本书变成「目录导读 + 按章分课」的课程，再由使用者逐课交互式学完。面向人类学习。

所有处理**仅针对使用者已提供的本地文件**。本技能不联网、不爬取、不代理，也不提供任何书源或网页源。

## 声明（摘要）

- 本技能**不包含、不支持任何爬取 / 代理 / 远程获取**行为；任何获取内容的行为由使用者自行完成。
- 使用者须**自行提供书文件 / 资料**，并自行遵守所在国家 / 地区的法律法规与平台规范。
- 本仓库（代码与技能）以 **MIT 许可**发布，见仓库根 `LICENSE`。书籍内容的使用与版权责任由使用者自行承担，详见 `免责声明.md`。

> 仓库内保留的爬虫 / 书源脚本（如 `search` / `download` / `import_source` / `aggregate` / `discover`）为**使用者自行使用、自担责**的工具；本技能的主路径不依赖它们，技能支持的入口是下文的 `all-local`（处理使用者已提供的本地文件）。

---

## 一、如何调用（使用者说一句即可）

触发语示例：

- 「学这本书 `<本地书路径>`」
- 「把这本 EPUB 课程化」
- 「教我这本书」（并给出本地文件路径）

接到请求后，按下方「命令」直接执行；无需了解内部结构。

## 二、命令（在仓库/工作区根目录下执行）

Python 使用本仓库精简 venv（已含 bs4 等教学依赖，体积 ~81MB）：
`./venv_slim/Scripts/python.exe`（位于仓库根；若自行部署可改用任意含依赖的 Python）。
命令均使用相对路径，克隆到任意目录都能直接跑。

> **跑到哪一层？** 命令在「含 `tools/` 的目录」下执行即可——克隆的仓库根，或本技能被安装到用户级（`~/.workbuddy/skills/book-learning-tutor/`）时即在该技能目录内执行。其中 `teach.py` 会自动定位同目录下的 `tools/` 引擎，无需关心绝对路径。

### 1. 本地一键（推荐）

把一本本地书直接变成课程：

```bash
python tools/acquire/pipeline.py all-local <书文件路径> [--name 书名]
```

自动完成：抽取 → 转 markdown → 生成课程。产物落在 `书库/<书名>/`。
示例（更省事的方式见仓库根 `teach.py`，一条命令完成全部）：

```bash
python tools/acquire/pipeline.py all-local "<本地书路径>/Flatland.epub"
```

### 2. 分步执行（需要微调时）

```bash
# ① 本地书 → 参考/<书名>/（抽取章节）
python tools/acquire/pipeline.py ingest <文件或目录> [--name 书名]

# ② 参考/<书名>/ → 书库/<书名>/（course_gen 直读，生成课程 + progress.json）
python tools/structure/course_gen.py 参考/<书名>/ --book <书名>
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
| `参考/<书名>/` | 原书抽取结果（`_sections.json` / `_meta.json`，既是检查点也是 course_gen 直读输入） |
| `书库/<书名>/` | **终态课程**：`00_目录导读.md` + `第XX章_章名/第XX课_课名.md` + `progress.json` |

---

## 四、教学闭环（直接执行，不要写状态机脚本）

1. 读 `00_目录导读.md`，问使用者「从哪一课开始？」（首次默认第 01 课；`progress.json` 的 `current` 已指向第一课）。
2. 每课循环：
   - **a 讲解**：把本课讲得易懂——类比、例子、去废话。若本课含 `## 配图（多模态训练单元）` 块，把对应图片调出来给学习者看（图文对照比纯文字更易懂；图片路径就在该块内，可直接打开/展示）。
   - **b 问疑**：「这节课哪里没懂？没有就回『无』。」
   - **c 解疑**：针对性补充，循环到使用者说「懂了」。
   - **d 出题**：无疑后按 Bloom 认知分层出 2–4 题（记忆 / 理解 / 应用 / 分析）。先跑一次
     `progress --quiz-template` 看提纲；题目与参考答案由你基于本课正文拟写，再用
     `progress --add-quiz` 留存（见下方命令）。
   - **e 看掌握**：判分讲评；把学习者作答与对错写回（仍用 `--add-quiz --correct true/false`）；仍有问题回 c。
   - **f 推进**：`progress --next`（或 `--done <课>`）写回并自动进下一课。
3. 全书完成 → `progress --report` 汇总掌握度，`progress --review` 列出需复习的弱课。

**上下文纪律**：每次只加载「本课 + 目录导读 + 进度」三件，绝不塞全书。

### 教学执行引擎（叠加 learning-assistant 原则，作为 §四 的执行层）

授业与本技能**按时间顺序融合**为专业教师整体（非嵌套）：`T0 授业产教材 → T1 本技能智能补强 → T2 费曼教学 → T3 复习/作业 → T4 自进化沉淀`。授业提供"教什么"（教材主干），本技能提供"教得懂+教得深"（6 原则+费曼循环+补强+复习+自进化，全套能力保留）。分工：

| 层 | 谁 | 职责 |
|---|---|---|
| T0 教材生产 | 授业 pipeline | 书→`书库/<书>/`（目录导读+分课正文+配图块）+ `progress.json`（章节/掌握度/测验骨架） |
| T1 智能补强 | learning-assistant 引擎 | 保留全套：扫描课程薄弱/过时处 → 搜索/大纲评估/arxiv/project-code/官方文档 补强，写入课程补强附录（不破坏主课程） |
| T2 教学执行 | learning-assistant 引擎 | 费曼循环、练习闸门(≥80%才推进)、自适应(难→拆/易→加速)、对比表、配图对照 |
| 进度真相 | `progress.json` | 唯一权威：current/status/mastery/quiz，永远用 `progress` 命令原子写回，禁止手改 |
| T3/T4 改进沉淀 | learning-assistant 引擎 | 复习卡+背诵+习惯档案+自进化建议缓冲（skill_manage 逻辑，执行层环境门控） |

在 §四 a–f 循环上叠加：

- **每课前定目标层级**：读 `progress.json` 该课 `mastery` 与 `00_目录导读.md` 难度，明确"学完你能 A 级(能读) 还是 B 级(能写) 做什么"。
- **a 讲解升级**：遇易混淆概念必须给**对比表**（符号/写法/含义/例子/口诀逐行比）；信息量足（每概念 2–3 角度举例）；含 `## 配图` 块则图文对照。
- **新增「讲」(费曼复述)**：d 出題前，先让学习者用自己话复述核心概念，按 掌握/部分掌握/模糊/不会 四级评估（对→"对"，错→"不对"+原因，不迎合不挑刺，非原则小错记下下次）。
- **练习闸门**：d 出题后答对率 ≥ 80% 才进 f 推进；< 80% 回 c 补盲区，不强行推进。用户说"这个我会"也至少出 1 题验证，不出题默认相信是最大陷阱。
- **自适应**：该课 `mastery` 历史低或导读标 🔴 困难 → 拆小节逐节走；连续轻松通过 → 加速少重复。
- **学后沉淀**：每课结束用 `progress --add-quiz` 留存测验；生成 2–3 张复习卡与（需背的）背诵条，落点见下。
- **间隔复习**：新课前先复习 `progress --review` 列出的弱课；用户说"复习"从复习卡抽 5 张按优先级（🔴近学+曾模糊 > 🟡久未复习 > 🟢已稳）。

**落点约定（避免双份进度）**：
- 课程内进度 → `书库/<书>/progress.json`（唯一真相，永远用 `progress` 命令写回，禁手改）。
- 备课单 / 复习卡 / 背诵 / 知识库 / 作业 / 教学笔记 → 存 **learning-assistant 技能目录内**（不污染书库）：`.workbuddy/skills/learning-assistant/storage/<书名>/`（`备课/` 每课备课单、`复习卡.md`、`背诵.md`(必背+checkpoint)、`知识库.md`、`作业.md`(写/背/实践)、`教学笔记.md`）。
- 跨书学习者画像 → 同技能目录 `storage/习惯.md`（记录最佳时长/偏好解释方式/理解速度/薄弱·擅长领域，跨书复用）；learning-assistant 原 `.last_session` 概念在本项目**改读 `progress.json` 的 `current`**，不另建。
- **自进化限制（如实告知）**：learning-assistant 原设计用 Hermes `skill_manage` 自动改自己 SKILL.md；WorkBuddy 下该动作不执行。改为：教学中识别出的**可复用**改进建议记入 `storage/<书名>/教学笔记.md`，由你/我人工筛选后固化进 learning-assistant 的 SKILL.md；单用户专属调整只进 `习惯.md`，不进 SKILL.md。

### 进度 / 测验写回命令（替代手改 progress.json）

在仓库根目录下，用本仓库精简 venv 执行：

```bash
# 出题提纲（Bloom 四层）
python tools/acquire/pipeline.py progress <书名> --quiz-template

# 完成当前课并推进（可带掌握度 0~1）
python tools/acquire/pipeline.py progress <书名> --next --mastery 0.8
# 或单独标记某课完成（LESSON=序号/子串/全路径）
python tools/acquire/pipeline.py progress <书名> --done 2 --mastery 0.9

# 给某课追加一条测验（agent 拟题，留存判分）
python tools/acquire/pipeline.py progress <书名> --add-quiz 1 \
    --q "..." --bloom 记忆 --a "参考答案/讲解" --learner "学习者作答" --correct true

# 汇总 / 弱课复习清单（仅列「已学过但薄弱」的课）
python tools/acquire/pipeline.py progress <书名> --report
python tools/acquire/pipeline.py progress <书名> --review
```

### progress.json 结构

```json
{
  "book": "<书名>",
  "current": "第01章_章名/第01课_课名",
  "lessons": {
    "第01章_章名/第01课_课名": {
      "status": "done", "mastery": 0.9, "unresolved": [],
      "quiz": [{"q": "题目", "bloom": "记忆", "a": "答案", "learner": "作答", "correct": true, "ts": "2026-08-10 20:00"}]
    }
  }
}

---

## 五、纪律

- 每步 改 → 测 → 提交。
- 遇到产物不符合预期，先看 `参考/<书名>/_meta.json` 的 `bookType` / `needs_ocr` 再判断。
