---
name: 授业 (Book Learning Tutor)
description: 把使用者自行提供的本地书（PDF/EPUB/DJVU/MOBI/AZW/DOCX/TXT/MD/CBZ）课程化，并作为「专业教师」逐课带人类学完：课前备课→详尽费曼教学→练习闸门→间隔复习→背诵作业→自进化。当用户说「学这本书 <本地路径> / 把这本 PDF 课程化 / 教我这本书 / 继续学 <书> / 复习 <书> / 考考我 <书> / 帮我学 X」时调用。本技能不联网、不爬取、不提供任何书源，仅处理使用者已提供的本地文件。教学引擎已单包自包含，无需再加载其他技能。
version: 1.0.0
agent_created: true
---

# 授业 · 课程化逐课教学（含专业教师引擎，单包自包含）

把一本书变成「目录导读 + 按章分课」的课程，再由使用者逐课交互式学完。面向人类学习。

**本技能已集成完整教学引擎**（备课 / 费曼 / 练习闸门 / 自适应 / 间隔复习 / 背诵作业 / 自进化），是单一自包含技能——**教学时不再需要加载别的技能**，避免「只加载一半导致教学降级」。

所有处理**仅针对使用者已提供的本地文件**。本技能不联网、不爬取、不代理，也不提供任何书源或网页源。

本技能遵循 **Agent Skills 开放标准**，存储与命令均用相对路径、**不绑定任何特定宿主**——可装进 WorkBuddy（`~/.workbuddy/skills/`）、Claude Code（`~/.claude/skills/`）、Copilot CLI、Amp、OpenClaw 等任意兼容宿主；运行只需 `python3` + 依赖（见 `requirements.txt`）。

## 声明（摘要）

- 本技能**不包含、不支持任何爬取 / 代理 / 远程获取**行为；任何获取内容的行为由使用者自行完成。
- 使用者须**自行提供书文件 / 资料**，并自行遵守所在国家 / 地区的法律法规与平台规范。
- 本仓库（代码与技能）以 **MIT 许可**发布，见仓库根 `LICENSE`。书籍内容的使用与版权责任由使用者自行承担，详见 `免责声明.md`。

> 仓库内保留的爬虫 / 书源脚本（如 `search` / `download` / `import_source` / `aggregate` / `discover`）为**使用者自行使用、自担责**的工具；本技能的主路径不依赖它们，技能支持的入口是下文的 `all-local`（处理使用者已提供的本地文件）。

---

## 一、如何调用（使用者说一句即可）

- 「学这本书 `<本地书路径>`」/「把这本 EPUB 课程化」/「教我这本书」→ 若书还没课程化则先 T0 课程化，再从 `progress.json.current` 开始教学。
- 「继续学 / 下一课」→ 读 `progress.json.current` 续上（新对话也能续）。
- 「复习 <书>」/「考考我 <书>」→ 间隔复习（复习卡）/ 练习关卡。
- 「总结 <书>」→ 看知识库精华。
- 「帮我学 X」（无授业课程）→ 兜底：本技能独立走 T1 自产大纲 → 教学 / 复习 / 自进化。

## 二、命令（在含 `tools/` 的目录执行：仓库根 或 用户级技能目录）

Python 用本仓库精简 venv（已含 bs4 等教学依赖，~81MB）：`./venv_slim/Scripts/python.exe`（位于仓库根；自行部署可改用任意含依赖的 Python）。命令均用相对路径，克隆到任意目录都能直接跑。

> **跑到哪一层？** 命令在「含 `tools/` 的目录」下执行即可——克隆的仓库根，或本技能安装到任意宿主的用户级 skills 目录（如 WorkBuddy 的 `~/.workbuddy/skills/book-learning-tutor/`、Claude Code 的 `~/.claude/skills/book-learning-tutor/`）时即在该技能目录内执行。`teach.py` 会自动定位同目录下的 `tools/` 引擎。

### 1. 本地一键（推荐）

```bash
python tools/acquire/pipeline.py all-local <书文件路径> [--name 书名]
```

自动：抽取 → 转 markdown → 生成课程，产物落 `书库/<书名>/`。

### 2. 分步执行（需要微调时）

```bash
# ① 本地书 → 参考/<书名>/（抽取章节）
python tools/acquire/pipeline.py ingest <文件或目录> [--name 书名]
# ② 参考/<书名>/ → 书库/<书名>/（course_gen 直读，生成课程 + progress.json）
python tools/structure/course_gen.py 参考/<书名>/ --book <书名>
```

- **扫描版判定**：仅 PDF/DJVU 文本层过薄时标 `needs_ocr` 并尝试本地 OCR 钩子；无 OCR 环境则保留标记、不强制。
- **书籍类型**：任一章含节 → `textbook`（课文，每节一课）；否则 → `novel`（小说，每章一课）。可用 `course_gen.py` 的 `--chapter-level` / `--lesson-level` 调整标题层级映射。

### 3. 自检 / 回归

```bash
python tools/acquire/pipeline.py selftest
python tools/acquire/book_formats.py --selftest
python tools/structure/course_gen.py --selftest
```

### 4. 进度 / 测验写回（替代手改 progress.json）

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

---

## 三、产物落点（使用者只需关心这个）

| 目录 | 内容 |
|---|---|
| `参考/<书名>/` | 原书抽取结果（`_sections.json` / `_meta.json`，既是检查点也是 course_gen 直读输入） |
| `书库/<书名>/` | **终态课程**：`00_目录导读.md` + `第XX章_章名/第XX课_课名.md` + `progress.json` |
| `书库/<书名>/_enrich.md` | T1 智能补强追加（一本书一个，不改动分课正文） |

---

## 四、教学闭环（本技能完整引擎，直接执行）

时间线（单包内自包含，不再依赖外部技能）：

```
T0 教材生产   书 → 书库/<书>/（目录导读+分课正文+配图块）+ progress.json   ← 确定性主干
T1 智能补强   扫描本课薄弱/过时处 → 搜索/arxiv/project-code/官方文档 补强 → 写 _enrich.md（不破主课程）
T2 真老师教学 课前备课 → 详尽费曼教学 → 练习闸门(≥80%才推进) → 间隔复习
T3 作业·复习  按薄弱布置 写/背/实践 作业 + 下次课先查
T4 自进化     建议缓冲 → 普适筛选 → 稳定冻结（详见 references/self_evolution.md）
```

每课循环（**评 → 学 → 讲 → 练 → 萃 → 记**）：

1. **评（自适应）**：读 `progress.json` 该课 `mastery` 与 `00_目录导读.md` 难度 → 🔴 困难 / 低 mastery 拆小节逐节走；🟢 简单加速少重复；有基础跳重复。完整策略表见 `references/teaching_patterns.md`。
2. **学（讲解）**：打开 `书库/<书>/<章>/<课>.md`（含 T1 补强块）详尽讲解（类比 / 多例子 / 去废话）；含 `## 配图（多模态训练单元）` 块则图文对照；**易混概念必须给对比表**（符号 / 写法 / 含义 / 例子 / 口诀逐行比）。
3. **讲（费曼复述）**：让学习者用自己话复述核心概念，按 掌握 / 部分掌握 / 模糊 / 不会 四级评估（对→"对"，错→"不对"+原因；不迎合不挑刺，非原则小错记下下次）。
4. **练（练习闸门）**：无疑后按 Bloom 出 2–4 题（先 `progress --quiz-template` 看提纲），拟写并用 `progress --add-quiz` 留存。答对率 ≥ 80% 才推进；< 80% 回「学」补盲区。用户说"我会"也至少出 1 题验证，不出题默认相信是最大陷阱。
5. **萃（沉淀）**：精华写 `storage/<书名>/知识库.md`；2–3 张复习卡写 `storage/<书名>/复习卡.md`。
6. **记（写回 + 作业）**：用 `progress --next` / `--done` 原子写回 mastery/status 并推进；针对错的 / 模糊薄弱点布置 写 / 背 / 实践 作业记 `storage/<书名>/作业.md`；每课必背项写 `storage/<书名>/背诵.md` 并标 **checkpoint**（分阶段背，不一次压）。

**备课（T1 + 开讲前必做）**：先扫描本课 → 检索补强（来源选择见 `references/source_selection.md`）→ 产出**备课单**（写 `storage/<书名>/备课/<章_课>.md` 或会话展示）：
```
备课单 · <章>/<课>
- 目标层级：A级(能读)/B级(能写) — 学完能做___
- 核心概念（3–5）：___
- 必背清单📌（术语/公式/签名/序列/规则/依赖，逐条）：1.___ 2.___ …
- 扩展知识（加深，可选）：___
- 例子/对比表预案：___
- 作业预案（写/背/实践）：___
```

**六条教学原则（不可违背，每条独立生效）**：① 客观不迎合 ② 剖析痛点 ③ 因材施教（按书 + 学习习惯/理解能力，不按身份）④ 不故意纠错（非原则小错记下）⑤ 只教真东西（"我会"→验 1 题）⑥ 目标驱动分层。详解与常见陷阱见 `references/teaching_patterns.md`。

**上下文纪律**：每次只加载「本课 + 目录导读 + 进度」三件，绝不塞全书。

### 存储（全在本技能目录内，按需加载）

```
技能目录内的 `storage/`（随安装位置自动适配，跨宿主一致）
  习惯.md              — 跨书学习者画像（runtime 更新，git 跟踪模板）
  <书名>/
    备课/              — 每课备课单
    复习卡.md          — Q&A 复习卡片
    背诵.md            — 必背清单 + checkpoint（分阶段）
    作业.md            — 写/背/实践 作业 + 完成情况
    知识库.md          — 精华笔记
    教学笔记.md        — 自进化建议缓冲
```

**进度不在此**：课级进度永远在 `书库/<书名>/progress.json`（用 `progress` 命令写回）。本技能只读 `current` / `mastery`，不建 `.last_session`。

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
```

---

## 五、纪律

- 每步 改 → 测 → 提交。
- 遇到产物不符合预期，先看 `参考/<书名>/_meta.json` 的 `bookType` / `needs_ocr` 再判断。
- 细则按需读：`references/source_selection.md`（T1 补强来源）、`references/self_evolution.md`（T4 自进化）、`references/teaching_patterns.md`（教学原则 / 自适应策略 / 常见陷阱）。
