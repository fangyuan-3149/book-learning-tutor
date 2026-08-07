---
name: 授业 (shouye)
description: 把一本书（书名/书源订阅/本地 PDF）变成「目录导读 + 按章分课」的课程，再由你自己逐课交互式教学（讲解→问疑→解疑→出题→看掌握→下一课）。当用户说「学这本书 X / 教我这本书 / 把 PDF 课程化 / 导入书源」时调用。
---

# 授业 · 课程化逐课教学

一本书 → 可逐课精学的课程 → 对话式带人类学完。面向人类学习。

**架构铁律**：授业 = **你（agent）驱动 + 确定性工具**。工具只做抓取、解析、校验、落盘；
所有"智能"环节（写书源规则、讲解、出题、判掌握）由你直接做，**不调用任何外部 LLM，不需要任何 API key**。

**能力边界**：只做 L1（纯解析 + JS 桥求值），最多 L2；**不显式开网页**。
需要 `webView` / 验证码 / 浏览器指纹的源直接判为不支持，如实告知用户。

---

## 一、你只需要知道这些命令

所有命令在项目根 `E:\授业` 下执行，Python 用：
`C:/Users/陌下/.workbuddy/binaries/python/envs/default/Scripts/python.exe`

### 1. 导入书源（一条命令搞定，含自动排错）
```bash
python tools/acquire/import_source.py <订阅URL> [--kw 关键词] [--max N]
```
输入任意书源订阅/聚合 URL，它会自动：
抓取（带本地快照缓存）→ 识别格式（数组 / 单源 / Legado shuyuan 包装 / base64+gzip / 裸 blob）
→ 去重 → **主机存活预筛**（死域一次判死，不让每个源各耗满超时）
→ 逐源用 L1 引擎真实搜一次 → 可用源写入 `data/sources/imported/verified.json`（自动并入后续搜索范围）。

不可用时**不会沉默失败**，会给出具体归因：
`DNS_FAIL`(域名没了) / `TIMEOUT` / `HTTP_403` / `HTTP_404`(规则过期) / `NEED_LOGIN` /
`CF_BLOCKED`(Cloudflare，L1 无解) / `ENGINE_BUG`(我们引擎的问题，该修) / `EMPTY`(站活着但搜不到)。

`--selftest` 可离线自检格式识别与错误分类。

### 2. 从裸网址自动生成新书源（你写规则）
```bash
python tools/acquire/discover.py <网站URL>
```
工具负责：判格式(HTML/JSON) → 取样本页 → 登录页过滤 → 回放校验(≤3 次) → 落盘 `data/sources/discovered/`。
**中间"读样本页、推导 CSS/XPath/JSONPath 规则"这一步是你的活**，不是外部 API 的活。

### 3. 搜书 → 下载 → 转 markdown
```bash
python tools/acquire/pipeline.py search   <书名> [--idx N]   # 全源池并发搜，结果缓存 data/search/
python tools/acquire/pipeline.py download <bookUrl> <源名> [书名]   # → 参考/<书名>/ (原文 raw)
python tools/acquire/pipeline.py convert  <书名>            # → 预处理/<书名>.md
python tools/acquire/pipeline.py all      <书名> [--idx N]  # 三步串联
```

### 4. 课程生成
```bash
python tools/structure/course_gen.py <书名>
```
产出 `书库/<书名>/`：`00_目录导读.md` + `第XX章_章名/第XX课_课名.md` + `progress.json`。

### 5. 排错 / 回归
```bash
python tools/acquire/selftest.py          # 本地 fixtures，确定性验证引擎+管道，不联网
python tools/acquire/debug_source.py ...  # 单源分步回放
python tools/acquire/rule_trace.py ...    # 规则求值链路追踪
```

**本地 PDF 备选路径（未来项，当前未实现）**：规划为 `tools/pdf/mineru_run.py` → markdown → `预处理/`（MinerU 待装）。当前授业以「书源获取」为主路径，PDF 入口尚未接线，勿调用不存在的脚本。

---

## 二、产物落在哪（用户只需关心这个）

| 目录 | 内容 |
|---|---|
| `参考/<书名>/` | 原书 raw（供人类对照、调规则） |
| `预处理/<书名>.md` | 净化后的全书 markdown |
| `书库/<书名>/` | **终态课程**：目录导读 + 章/课 + progress.json |
| `data/sources/imported/verified.json` | 已验证可用的书源池 |

---

## 三、主流程

输入解析 → ① 获取文本 → ② 结构生成 → ③ 教学闭环。

### ① 获取
- 给了订阅 URL → 先 `import_source.py` 扩源池。
- 给了书名 → `pipeline.py all <书名>`；搜不到就换关键词或先扩源池。
- 给了裸网址 → `discover.py` + 你写规则。
- 给了 PDF → **当前未实现**（规划 MinerU 路径，脚本尚不存在）；先用书源/订阅 URL 路径。

### ② 结构生成
读 markdown 标题层级，定 `#→章 / ##→课`（**首本书必须人工校验边界**）。
课文件 = 原文保真 + 结构化知识点，**不丢原文**（精华提炼留到教学环节，保证可回溯）。

### ③ 教学闭环（你直接执行，不要写状态机脚本）
1. 读 `00_目录导读.md`，问用户「从哪一课开始？」（首次默认第 01 课）。
2. 每课循环：
   - **a 讲解**：把本课讲得易懂——类比、例子、去废话。
   - **b 问疑**：「这节课哪里没懂？没有就回『无』。」
   - **c 解疑**：针对性补充，循环到用户说「懂了」。
   - **d 出题**：无疑后按 Bloom 认知分层出 2–4 题（记忆/理解/应用/分析）。
   - **e 看掌握**：判分讲评；仍有问题回 c。
   - **f 推进**：写回 `progress.json`，自动进下一课。
3. 全书完成 → 汇总掌握度报告。

**上下文纪律**：每次只加载「本课 + 目录导读 + 进度」三件，绝不塞全书。

### progress.json
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

## 四、纪律
- **版权**：仅开源 / CC / 公有领域 / 用户自有合法源。爬取限合法内容源。
- **每步 改→测→git commit**。
- 遇到源不可用，先看 `import_source.py` 给的归因再动手，别盲改规则。
