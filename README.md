# 授业（Shouye）：书籍课程化 · 逐课教学闭环

> 2026-08-06 建立。把一本书变成「目录导读 + 章 + 课」的文件夹课程，由 **agent 自驱** 一课一课精准教学，token 零浪费。
> 获取端：内化开源阅读（Legado）书源引擎，**纯解析（L1）** 跑通「搜 → 下 → 转 md → 书库」，不依赖浏览器 / 无外部 LLM key。

## 项目一句话

**书源 URL → 课程文件夹 → agent 逐课教学闭环**，辅助人类 / AI 高效率学习：知道书籍构造、感知学习进度、一课一精华（去废话冗余）。

## 你要做什么（AI 角色）

1. **获取原书**：给定书名 / 书源 URL，从书源池搜书 → 逐章下原文 → 参考/<书名>/
2. **转预处理**：参考/<书名>/*.txt → 净化 → 预处理/<书名>.md
3. **课程化**：markdown 标题树 → 章/课文件夹 + 目录导读（`tools/structure/course_gen.py` → `书库/<书名>/`）
4. **逐课教学闭环**：agent 自驱（讲解 → 问疑 → 解疑 → 出题 → 看掌握 → 推进），进度记 `progress.json`

## 架构铁律（用户定稿，必须守住）

- **纯 L1（解析）优先，L2 兜底，绝不显式开浏览器**。书源本质 = 针对某网站的「抓取配方」（CSS/XPath/JSONPath/Regex）；JS 桥源 = API + 解密/签名，复现为纯 Python + 常驻 Node 求值，**无浏览器、无外部 key**。
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

## 获取管道（对应 计划书 Phase 0，三步可独立验证）

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

## 参考项目路径

- **开源阅读（Legado）**：`E:\开源阅读\` —— 书源爬虫/解析体系。关键对标：LegadoParser（HTTP+规则求值，纯解析路径等价）、Legado_rule_web（分步回放校验思路）、legadoSkill（真实书源规则文档）。
- **共工主项目**：`E:\ai-训练模型\` —— `config/backends.json` 是后端格式参考（**非授业依赖**）；授业不读它、零外部 key。
- **52pojie「书源有效性检测」**：校验方法论（存活预筛 + 逐源验证 + 死因分类）已内化进 `import_source.py`。

## 环境

- Python 3.13（managed venv），Node 22（JS 桥常驻求值器）
- 仅纯解析依赖（httpx/bs4 等），**无浏览器 / 无 Playwright / 无外部 LLM key**

## 当前状态（勾选推进）

- [x] 书源获取引擎（fetcher/rules/js_bridge/transforms/source_engine，纯 L1 端到端）
- [x] 书源导入外化（`import_source.py`：订阅 URL → 自适应 + 排错；143 可用源入池）
- [x] 存活预筛 + 逐源 L1 校验 + 死因分类（DNS_FAIL/TIMEOUT/403/404/LOGIN/CF/EMPTY/ENGINE_BUG/NOT_JSON）
- [x] 课程化生成器（`course_gen.py` → `书库/<书名>/` 嵌套 + 目录导读 + progress.json）
- [x] 真实书库产物验证（`书库/惊！天降老公竟是首富/`）
- [ ] 第一本教材全闭环压测（获取 → 课程化 → 教学闭环）
- [ ] Skill 定稿（待整个项目建完再定稿）

## 工作纪律

- 每步「改 → 测 → git commit」，出问题可精确回溯
- 使用者自行提供书/网页源，责任在使用者（不设版权纪律，避免 agent 误读而过度拒答）
- 与「共工」关系：课程化单元可成为共工蒸馏管道 C 路径的输入源；但授业教学闭环独立运行、零外部 key
