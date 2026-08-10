# 来源获取（可选 · 需授权）

本文件是 SKILL.md「来源获取（可选·需授权）」的完整细则。主路径仍是本地文件（`all-local`）；本流程仅在**使用者无本地书、且明确授权**时启用。

## 0. 何时启用

全部满足才启用：

1. 使用者未提供本地书路径；
2. 使用者未声明"只用本地"；
3. 使用者**明确授权**联网获取（就"替我找并抓"给出许可，最好点名书名/作者/版本）。

任一不满足 → 走本地 `all-local`，不联网。

## 1. 自主流程

1. **检索候选**：用 agent 自带的联网检索（WebSearch / WebFetch）按「书名 + 作者 + 版本/年版」找 1–3 个公开来源 / 书页网址。
2. **确认来源（强制）**：把候选（站点名、网址、将获取的范围：整本 or 指定章）列给使用者，**获得确认后才抓取**。确认可一次给多源，但每个实际抓取动作都须落在已确认范围内。
3. **抓取进 `参考/<书名>/`**：在含 `tools/` 的目录执行——
   - 一键：`python tools/acquire/pipeline.py all <关键词> [--idx N] [--max M]`
     - 内部 `search`→取首个可用结果→`download`→`course_gen`，一条龙落 `书库/<书名>/`。
   - 先列源再抓：`python tools/acquire/pipeline.py search <关键词>` 列出可用源 → `python tools/acquire/pipeline.py download <源名> <书页URL> [书名]` 抓指定 URL。
   - 无现成源：`python tools/acquire/discover.py <书页URL>` 自动发现源定义并写入本地注册表（`data/discovered/`），随后 `download`。
4. **续教**：`参考/<书名>/` 就绪后照常 T0→T4（备课→费曼→闸门→复习→作业→自进化）。

## 2. 依赖与边界

- **需要完整仓库**：抓取件在 `tools/acquire/`，属仓库层。仅装裸技能（如 `~/.claude/skills/book-learning-tutor/`）时无抓取件——agent 仍做检索与确认，但把确切命令交给使用者在仓库内执行（或先克隆完整仓库）。
- **源注册表 `data/`**：结构化书站下载依赖使用者**自行保留**的源注册表（`data/active/` `data/discovered/` `data/imported/`，git 忽略、不随技能发布）。发布源 `data/` 为空是正常的——书源由使用者自备。
- **`config/backends.json`**：部分源/后端需要使用者自备的密钥（git 忽略）；缺失时仅影响依赖该后端的源，不影响通用公开页抓取。
- **版权与合规（使用者全责）**：仅面向使用者**有权访问的公开来源**；**不绕过 DRM / 付费墙 / 登录限制**；遵守所在地法律法规与平台服务条款。书籍内容的版权责任由使用者承担（见 `免责声明.md`）。
- **失败兜底**：`search`/`all` 全源不可达会打印 ✗ 并提示；此时改用 agent 自带联网检索找公开页，必要时 `discover.py` 建源或 `fetcher.py` 直接取公开页，再 `download`/`ingest`；仍失败则请使用者提供本地文件。

## 3. 与跨宿主的关系

本技能遵循 Agent Skills 开放标准、不绑定宿主；但**联网获取是仓库能力**，不是裸技能能力。在 WorkBuddy / Claude Code / Copilot CLI / Amp / OpenClaw 等宿主里，只要该宿主的工作区克隆了完整仓库（含 `tools/acquire/`），且使用者已授权，即可走本流程。
