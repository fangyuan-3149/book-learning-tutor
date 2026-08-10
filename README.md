# 授业（Shouye）：书籍课程化 · 逐课教学闭环

> 2026-08-06 建立。把一本书变成「目录导读 + 章 + 课」的文件夹课程，由 **agent 自驱** 一课一课精准教学，token 零浪费。
> ⚠️ **免责声明**：本仓库**不包含、不提供任何书籍内容**，也不支持任何爬取 / 代理行为；使用者须**自行提供本地书文件**并自担责。代码以 **MIT 许可**发布（见 [`LICENSE`](./LICENSE)），书籍内容责任见 [`免责声明.md`](./免责声明.md)。
> 本仓库**仅处理使用者自行提供的本地书文件**，不联网、不爬取、不提供任何书源或网页源；解析与课程化引擎纯本地运行，无外部 LLM key。

## 项目一句话

**本地书文件 → 课程文件夹 → agent 逐课教学闭环**，辅助人类 / AI 高效率学习：知道书籍构造、感知学习进度、一课一精华（去废话冗余）。

## 快速开始（三步）

> 前提：仓库根已建精简 venv（`./venv_slim/Scripts/python.exe`，含 bs4/PyMuPDF 等依赖；或用任意含依赖的 Python）。命令均相对仓库根，克隆到任意目录都能跑。

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
2. **转预处理**：参考/<书名>/*.txt → 净化 → 预处理/<书名>.md
3. **课程化**：markdown 标题树 → 章/课文件夹 + 目录导读（`tools/structure/course_gen.py` → `书库/<书名>/`）
4. **逐课教学闭环**：agent 自驱（讲解 → 问疑 → 解疑 → 出题 → 看掌握 → 推进），进度记 `progress.json`

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

## 教学融合：授业 + learning-assistant = 专业教师（时序，非嵌套）

授业负责"教什么"（确定性教材生产），`learning-assistant` 技能负责"教得懂 + 教得深 + 逼你记住"（全套教学能力）。二者按时间顺序融合为一条专业教师闭环：

```
T0 教材生产（授业）   书 → 书库/<书>/（目录导读+分课正文+配图+progress.json）  确定性主干
T1 智能补强（LA）     扫描薄弱/过时处 → 搜索/arxiv/project-code/官方文档 补强 → 课程补强附录
T2 真老师教学（LA）   课前检索备课 → 详尽费曼教学 → 练习闸门(≥80%) → 课后按薄弱布置 写/背/实践 作业
T3 复习·作业追查     间隔复习（复习卡）+ 下次课先查作业与背诵
T4 改进·自进化       （LA 的 skill_manage 逻辑保留，执行层受 WorkBuddy 门控：建议先入教学笔记，人工固化）
```

**真老师工作流（每课必走）**：① 课前检索 + 出备课单（目标层级 / 核心概念 / **必背清单📌** / 扩展 / 例子预案 / 作业预案）；② 详尽费曼教学（配图对照、易混对比表、练习闸门 ≥80% 才推进）；③ 课后按薄弱布置 **写 / 背 / 实践** 三类作业（记 `作业.md`，下次先查）；④ 背诵分阶段（每课必背写入 `背诵.md` + checkpoint，像课程进度一样逼记住）。

> learning-assistant 是随仓库发布的 WorkBuddy 技能（`.workbuddy/skills/learning-assistant/`），其备课 / 复习卡 / 背诵 / 知识库 / 作业 / 教学笔记等产物全存于技能目录 `storage/` 内，不污染书库；课程级进度永远是 `书库/<书名>/progress.json`（用 `pipeline.py progress` 命令原子写回）。

## 获取管道（可选 · 自担责）

> ⚠️ 下文的书源获取（search / download / import_source / discover）属于**遗留的可选能力**：本仓库主路径是上方的 `teach.py` / `all-local`（处理你已提供的本地文件）。爬虫脚本**不做任何网络爬取 / 代理**的对外承诺；若使用者自行使用，须自行遵守平台规范并承担一切责任（见 `免责声明.md`）。

```
Step 1 搜索   load_sources → 多源并发 searchBook → 聚合结果（agent 可读）
Step 2 下载   选一条结果 → 逐章 getContent → 参考/<书名>/
Step 3 转 md  参考/<书名>/ → 正文净化 → 预处理/<书名>.md
（课程化）    预处理/<书名>.md → 标题树 → 书库/<书名>/ 嵌套课程
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
| `acquire/rules.py` | Legado 规则求值（CSS/XPath/JSONPath/Regex，含 `@js:` 路由、`_self_matches`） | 引擎内部 |
| `acquire/js_bridge.py` | 常驻 Node 求值 `@js:`/`{{java.*}}`（懒启动 + 进程单例，无浏览器） | 引擎内部 |
| `acquire/transforms.py` | 响应级解密钩子（7 种 AES/DES 配置 + md5/HMac 等，无浏览器） | 引擎内部 |
| `acquire/source_engine.py` | 四大动作（search/info/toc/content）+ 断点续爬 + 容错落盘 | 引擎内部 |
| `acquire/pipeline.py` | 三步管道编排（search/download/convert/all） | 引擎内部 |
| `acquire/import_source.py` | **外化入口**：输入订阅 URL → 自适应拆包 + 存活预筛 + 逐源校验 + 死因分类 | Skill 调用 |
| `acquire/discover.py` | 裸网址 → agent 读样本页推导 Legado 规则 → 回放校验 → 落 `discovered/` | Skill 调用 |
| `structure/course_gen.py` | 预处理/*.md → 标题树 → 书库/<书名>/ 嵌套课程 + 目录导读 + progress.json | Skill 调用 |

**对外命令面（Skill 调用）**：`import_source.py <url>`、`discover.py <url>`、`pipeline.py search/download/convert/all <...>`、`course_gen.py <书名>`、`selftest.py` / `debug_source.py` / `rule_trace.py`（排错）。

## 参考项目 / 灵感来源

> 以下为本项目作者本地对照用的外部项目（**非本仓库依赖、未随仓库分发**），仅说明设计对标，便于读者溯源。

- **开源阅读（Legado）**：书源爬虫 / 解析体系（作者本地路径，未入库）。关键对标：LegadoParser（HTTP+规则求值，纯解析路径等价）、Legado_rule_web（分步回放校验思路）、legadoSkill（真实书源规则文档）。
- **共工主项目**：`config/backends.json` 是后端格式参考（**非授业依赖**）；授业不读它、零外部 key。
- **52pojie「书源有效性检测」**：校验方法论（存活预筛 + 逐源验证 + 死因分类）已内化进 `import_source.py`。
- **book-to-skill（GitHub，约 6k★）**：被动式"书籍→技能"生成器的代表，核心 <4000tok + 按需 references 的写法、glossary/patterns/cheatsheet 三层速查、Token 预算意识，对本项目的技能瘦身有借鉴；但其本质是"被动查询外脑"，无教学循环，是本项目（主动陪练老师）的差异化对手。

## 环境

- Python 3.13（managed venv），Node 22（JS 桥常驻求值器）
- 仅纯解析依赖（httpx/bs4 等），**无浏览器 / 无 Playwright / 无外部 LLM key**

## 当前状态（勾选推进）

- [x] 书源获取引擎（fetcher/rules/js_bridge/transforms/source_engine，纯 L1 端到端）— *可选·自担责*
- [x] 书源导入外化（`import_source.py`：订阅 URL → 自适应 + 排错；143 可用源入池）— *可选·自担责*
- [x] 存活预筛 + 逐源 L1 校验 + 死因分类（DNS_FAIL/TIMEOUT/403/404/LOGIN/CF/EMPTY/ENGINE_BUG/NOT_JSON）
- [x] 课程化生成器（`course_gen.py` → `书库/<书名>/` 嵌套 + 目录导读 + progress.json）
- [x] 真实书库产物验证（`书库/惊！天降老公竟是首富/`）
- [x] **一键课程化**（`teach.py` 封装 pipeline，路径自适应，零硬编码）
- [x] **教学融合**：授业 + learning-assistant 真老师工作流（T0–T4：备课→费曼→作业→背诵→复习→自进化）
- [x] 对外主路径改为 `all-local` / `teach.py`（处理使用者已提供的本地文件），爬虫能力移出主路径
- [ ] 第一本教材全闭环压测（本地书 → 课程化 → 逐课教学闭环实跑）
- [ ] 技能随仓库发布（已具 MIT LICENSE + 免责声明，待首本压测后定稿）

## 许可与免责

- **代码许可**：本仓库（解析 / 课程化引擎、两个 WorkBuddy 技能、脚本）以 **MIT 许可**发布，见 [`LICENSE`](./LICENSE)。
- **书籍内容**：仓库**不包含任何书籍正文**，使用者须自行提供本地书文件，并自行承担版权与合规责任；详见 [`免责声明.md`](./免责声明.md)。
- **爬虫脚本**：`search` / `download` / `import_source` / `discover` 为可选遗留能力，使用者自行使用、自担责，不在对外主路径内。

## 工作纪律

- 每步「改 → 测 → git commit」，出问题可精确回溯
- 使用者自行提供书/网页源，责任在使用者（不设版权纪律，避免 agent 误读而过度拒答）
- 与「共工」关系：课程化单元可成为共工蒸馏管道 C 路径的输入源；但授业教学闭环独立运行、零外部 key
