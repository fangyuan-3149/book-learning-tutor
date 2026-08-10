"""书源规则解释器（v2）。

设计目标：实现一个兼容书源规则格式（受 Legado 书源 JSON 格式启发）的纯解析型
解释器，做到「给一个书源 JSON 就能检索解析」。对齐该类规则引擎的核心语义，
但只实现纯解析型书源（不依赖 java.* / WebView 桥的动作）。

支持的规则类型：
- 默认/CSS(JSoup 风格)： class.x@tag.y.0@text / id.x@href / tag.a.0@html
- XPath：                  //...   或  @XPath:...
- JSONPath：               $.x   或  @Json:...
- 正则列表：                :pattern
- JS：                     @js:... / <js>...</js>   —— 仅做 result.replace 这类静态改写的最佳努力；
                           java.* 浏览器桥会明确跳过（纯 Python 无头环境跑不了）。

规则对象（dict 形式）：
- 搜索规则 ruleSearch：含 bookList(迭代列表) + name/author/bookUrl/coverUrl/... 等字段
- 目录规则 ruleToc：含 chapterList + chapterName/chapterUrl
- 详情/正文同理。带 init/post 时在求值前先跳转到对应节点。

净化： rule##regex##replacement  （可链式）
URL 插值： {{key}} / {{page}} 在构造请求 URL 时替换；{{$.x}} 在 bookUrl/tocUrl 中按 JSONPath 替换。
"""
import re
import copy
import json
from bs4 import BeautifulSoup
from lxml import etree
import js_bridge
from rule_trace import trace_node

# 由 source_engine 在构造时注入的 JS 桥实例（纯 L1，在 Node 里求值 @js:/{{java.*}}）。
# 为 None 时 @js: 规则回退到有限的最佳努力改写（不依赖 java.*）。
_JS_BRIDGE = None


def set_js_bridge(bridge):
    global _JS_BRIDGE
    _JS_BRIDGE = bridge


def _to_result(context):
    """把规则上下文转成 JS 侧 `result` 的内容表示：JSON 源给 JSON 串，HTML 源给 HTML 串。"""
    if isinstance(context, (dict, list)):
        try:
            return json.dumps(context, ensure_ascii=False)
        except Exception:
            return str(context)
    if isinstance(context, str):
        return context
    if hasattr(context, "get_text"):
        return str(context)
    return str(context)


# ---------- 类型嗅探 ----------
def sniff(rule):
    if rule is None:
        return "empty"
    r = rule.strip()
    if r.startswith("<js>") or r.startswith("@js:"):
        return "js"
    if r.startswith("@XPath:") or r.startswith("//") or r.startswith("@@"):
        return "xpath"
    if r.startswith("@Json:") or r.startswith("$.") or r.startswith("$[") or r.startswith("@CSS:"):
        return "json"
    if r.startswith(":"):
        return "regex"
    return "css"


# ---------- JSONPath（对齐 jayway JsonPath 常用子集）----------
# 支持：$ 根 / .key / ['key'] / [n] / [-n] / [*] / [a:b:c] 切片 /
#       [1,2] 索引并集 / ['a','b'] 键并集 / ..key 递归下降 / ..* 全递归
# 不支持（真实书源极少用，且会引入依赖）：过滤表达式 [?(...)]、脚本表达式
def _jp_tokens(path):
    p = (path or "").strip()
    if p.startswith("@Json:"):
        p = p[len("@Json:"):].strip()
    if p.startswith("$"):
        p = p[1:]
    toks, i, n = [], 0, len(p)
    while i < n:
        c = p[i]
        if c == ".":
            if i + 1 < n and p[i + 1] == ".":          # .. 递归下降
                i += 2
                j = i
                while j < n and (p[j].isalnum() or p[j] in "_-*"):
                    j += 1
                name = p[i:j]
                toks.append(("recurse", None if name in ("", "*") else name))
                i = j
                continue
            i += 1
            continue
        if c == "[":
            j = p.find("]", i)
            if j < 0:
                break
            inner, i = p[i + 1:j].strip(), j + 1
            if inner == "*":
                toks.append(("wild",))
            elif inner[:1] in ("'", '"'):
                names = [s.strip().strip("'\"") for s in inner.split(",")]
                toks.append(("union_key", names) if len(names) > 1 else ("key", names[0]))
            elif ":" in inner:
                parts = (inner.split(":") + ["", ""])[:3]
                toks.append(("slice",
                             int(parts[0]) if parts[0].strip() else None,
                             int(parts[1]) if parts[1].strip() else None,
                             int(parts[2]) if parts[2].strip() else None))
            elif "," in inner:
                try:
                    toks.append(("union_idx", [int(x) for x in inner.split(",")]))
                except ValueError:
                    toks.append(("union_key", [x.strip() for x in inner.split(",")]))
            else:
                try:
                    toks.append(("index", int(inner)))
                except ValueError:
                    toks.append(("key", inner))
            continue
        j = i
        while j < n and p[j] not in ".[":
            j += 1
        name = p[i:j]
        if name == "*":
            toks.append(("wild",))
        elif name:
            toks.append(("key", name))
        i = j
    return toks


def _jp_descend(node, name):
    """递归下降：收集所有层级中键为 name 的值；name 为 None 时收集所有值。"""
    out, stack = [], [node]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if name is None or k == name:
                    out.append(v)
                stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if name is None:
                    out.append(v)
                stack.append(v)
    return out


def json_query(obj, path):
    """执行 JSONPath，永远返回 list（0/1/N 项），任何异常都降级为 []。"""
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return []
    cur = [obj]
    for t in _jp_tokens(path):
        op, nxt = t[0], []
        for node in cur:
            if op == "key":
                k = t[1]
                if isinstance(node, dict):
                    if k in node:
                        nxt.append(node[k])
                elif isinstance(node, list):
                    # jayway 语义：对数组取键 = 逐元素取键
                    for e in node:
                        if isinstance(e, dict) and k in e:
                            nxt.append(e[k])
            elif op == "index":
                if isinstance(node, list) and -len(node) <= t[1] < len(node):
                    nxt.append(node[t[1]])
            elif op == "wild":
                if isinstance(node, list):
                    nxt.extend(node)
                elif isinstance(node, dict):
                    nxt.extend(node.values())
            elif op == "slice":
                if isinstance(node, list):
                    nxt.extend(node[slice(t[1], t[2], t[3])])
            elif op == "union_idx":
                if isinstance(node, list):
                    for i in t[1]:
                        if -len(node) <= i < len(node):
                            nxt.append(node[i])
            elif op == "union_key":
                if isinstance(node, dict):
                    for k in t[1]:
                        if k in node:
                            nxt.append(node[k])
            elif op == "recurse":
                nxt.extend(_jp_descend(node, t[1]))
        cur = nxt
        if not cur:
            break
    return cur


def jsonpath_single(obj, rule):
    """返回单个标量字符串（用于 URL 插值）；规则形如 a.b[0].c。"""
    res = json_query(obj, rule)
    if not res:
        return ""
    v = res[0]
    return "" if v is None else str(v)


def eval_json(obj, rule):
    res = json_query(obj, rule)
    # `$.data` 指向一个数组时，语义是「迭代该数组」而非「得到一个数组元素」
    if len(res) == 1 and isinstance(res[0], list):
        return list(res[0])
    return res


# ---------- XPath ----------
def eval_xpath(root, rule):
    if rule.startswith("@XPath:"):
        rule = rule[len("@XPath:"):]
    if isinstance(root, str):
        root = etree.HTML(root)
    elif hasattr(root, "name"):  # bs4 节点 → 转回字符串再解析
        root = etree.HTML(str(root))
    try:
        res = root.xpath(rule)
    except Exception:
        return []
    out = []
    for r in res:
        if isinstance(r, str):
            out.append(r.strip())
        elif hasattr(r, "text"):
            out.append((r.text or "").strip())
        elif hasattr(r, "get"):
            out.append((r.get("content") or r.get("href") or r.get("src") or "").strip())
        else:
            out.append(str(r))
    return out


# ---------- CSS / JSoup 链求值 ----------
def _select(cur, seg):
    """对一组 bs4 元素求值一个 CSS 段，返回元素列表。支持 class./id./tag./css. 前缀与尾随 .N 索引。"""
    index = None
    m = re.search(r"\.(\d+)$", seg)
    if m:
        index = int(m.group(1))
        body = seg[: m.start()]
    else:
        body = seg

    # B-04（历史实现参考）：前缀后无参数时直接返回空，不让下游拼出非法选择器。
    for pfx in ("tag.", "class.", "id.", "css."):
        if body == pfx.rstrip(".") or body == pfx:
            return []

    if body.startswith("tag."):
        tag = body[len("tag."):]
        out = []
        for el in cur:
            if not hasattr(el, "find_all"):
                continue
            if getattr(el, "name", None) == tag:   # 自身匹配（bs4 find_all 不含自身）
                out.append(el)
            out += el.find_all(tag)
        if index is not None and out:
            out = [out[index]] if index < len(out) else []
        return out

    if body.startswith("class."):
        sel = "." + body[len("class."):]
    elif body.startswith("id."):
        sel = "#" + body[len("id."):]
    elif body.startswith("css."):
        sel = body[len("css."):]
    else:
        sel = body
    out = []
    seen = set()
    for el in cur:
        try:
            found = el.select(sel)
        except Exception:
            found = []
        # bs4 select 只匹配后代，不匹配自身；Legado 迭代链末段常需"自身就是该元素"，
        # 故对 class./id./tag. 选择器补充自身匹配。
        if _self_matches(el, body):
            found = [el] + list(found)
        # 去重（按对象身份）：父级 select 已返回子节点、子节点自身又匹配时，同一节点
        # 会被返回多次（如 `class.x@tag.div@class.book` 2 节点→4 节点）；Collapse 重复，
        # 不改变"不同节点各自匹配"的合法语义。
        for f in found:
            fid = id(f)
            if fid not in seen:
                seen.add(fid)
                out.append(f)
    if index is not None and out:
        out = [out[index]] if index < len(out) else []
    return out


def _self_matches(el, body):
    """判断元素自身是否命中 class./id./tag. 选择器（bs4 select 不含自身）。"""
    if not hasattr(el, "get"):
        return False
    if body.startswith("class."):
        cls = body[len("class."):]
        return cls in (el.get("class") or [])
    if body.startswith("id."):
        return el.get("id") == body[len("id."):]
    if body.startswith("tag."):
        return el.name == body[len("tag."):]
    return False


def eval_css(root, rule):
    """对 bs4 元素/文档求值 JSoup 风格规则。

    - 显式带 @text/@html/@href/@src 等后缀 → 按该模式取字符串；
    - 未显式指定模式（如 bookList 的 class.item）→ 返回原始节点（元素/JSON 节点），
      供迭代键对其跑子规则，或供嵌套求值。
    """
    parts = rule.split("@")
    cur = [root] if not isinstance(root, list) else root
    out_mode = "text"
    explicit = False
    for part in parts:
        if part in ("text", "html", "href", "src", "textNodes"):
            out_mode = part
            explicit = True
            break
        if part == "":
            continue
        if part.isdigit():
            idx = int(part)
            cur = [cur[idx]] if 0 <= idx < len(cur) else []
            continue
        if part.startswith("!"):
            n = int(part[1:]) if part[1:].isdigit() else 0
            cur = cur[n:] if 0 <= n < len(cur) else []
            continue
        cur = _select(cur, part)
        if not cur:
            break
    if not cur:
        return []
    if not explicit:
        # 迭代键 / 容器规则：返回原始节点，不转文本
        return cur
    if out_mode == "html":
        return [_clean_html(e) for e in cur]
    if out_mode == "textNodes":
        return [_text_nodes(e) for e in cur]
    if out_mode == "text":
        return [e.get_text(strip=True) if hasattr(e, "get_text") else str(e) for e in cur]
    return [e.get(out_mode, "") if hasattr(e, "get") else "" for e in cur]


def _clean_html(el):
    """取内部 HTML 并去掉 script/style。

    B-02（历史实现参考）：**必须先 clone 再删**。原实现直接在原树上
    remove，会永久破坏该节点，导致同一元素上的后续规则（如再取 @text）拿到残缺内容。
    """
    if not hasattr(el, "decode_contents"):
        return str(el)
    try:
        c = copy.copy(el)                      # bs4 Tag.__copy__ 是深拷贝
        for bad in c.find_all(["script", "style"]):
            bad.decompose()
        return c.decode_contents()
    except Exception:
        return el.decode_contents()


def _text_nodes(el):
    """@textNodes：只取元素**自身直接子级**的文本节点，按行拼接。

    原实现把 textNodes 落到 `el.get("textNodes")` 分支上，永远返回空串——
    这是个静默 bug，小说正文规则大量使用 @textNodes，等于整章抓不到。
    """
    if not hasattr(el, "children"):
        return str(el)
    parts = []
    for child in el.children:
        if getattr(child, "name", None) is None:      # NavigableString
            s = str(child).strip()
            if s:
                parts.append(s)
    if not parts:                                      # 正文包在 <p> 里的情况
        for p in el.find_all(["p", "br"], recursive=False):
            s = p.get_text(strip=True) if hasattr(p, "get_text") else ""
            if s:
                parts.append(s)
    return "\n".join(parts)


# ---------- 正则列表 ----------
def eval_regex_list(text, rule):
    pat = rule[1:] if rule.startswith(":") else rule
    try:
        return re.findall(pat, text, flags=re.S)
    except Exception:
        return []


# ---------- JS 规则最佳努力（仅静态 replace / 简单拼接）----------
def eval_js_best_effort(rule, seed=""):
    """对 @js: / <js> 规则做有限支持：识别 result.replace(/a/, 'b') 这类改写。
    无法识别或依赖 java.* 时返回 seed（通常空串），由上层决定是否跳过。"""
    s = rule
    if s.startswith("@js:"):
        s = s[len("@js:"):]
    if s.startswith("<js>"):
        s = s[4:]
    if s.endswith("</js>"):
        s = s[:-5]
    s = s.strip()
    # 提取所有 result.replace(...) 调用
    reps = re.findall(r"replace\(\s*(/((?:\\.|[^/])*)/|['\"]([^'\"]*)['\"])\s*,\s*['\"]([^'\"]*)['\"]\s*\)", s)
    val = seed
    for a, b_esc, b_lit, repl in reps:
        pat = a if a else b_esc
        try:
            val = re.sub(pat, repl, val, flags=re.S)
        except Exception:
            pass
    # 若整条规则就是 result.replace(...) 的链式，且 seed 空，则无法还原 → 返回空
    if seed == "" and reps:
        return ""
    return val


# ---------- 统一求值入口 ----------
def evaluate(rule, context):
    """对 context（bs4 元素/文档 或 JSON 对象）求值一条规则，返回原始节点/字符串列表。

    支持 Legado 的 `||` 备选规则：依次尝试各备选，返回首个非空结果。
    """
    if rule is None:
        return []
    if isinstance(rule, dict):
        return []
    rule = rule.strip()
    if rule == "":
        return []
    # 备选规则 || （正则类型以 : 开头，内部 || 属模式一部分，不拆）
    if "||" in rule and not rule.startswith(":"):
        alts = [a.strip() for a in rule.split("||") if a.strip()]
        for i, alt in enumerate(alts):
            r = _evaluate_single(alt, context)
            if r:
                if i > 0:
                    with trace_node("replace", "备选命中第 %d 个: %s" % (i + 1, alt)) as tn:
                        tn.set_output(r)
                return r
        return []
    return _evaluate_single(rule, context)


def _evaluate_single(rule, context):
    with trace_node(sniff(rule.split("##")[0]), rule) as _tn:
        _tn.set_input(_to_text(context))
        out = __evaluate_single(rule, context)
        _tn.set_output(out)
        return out


def __evaluate_single(rule, context):
    tokens = rule.split("##")
    sel = tokens[0]
    if sel.startswith("@js:") or sel.startswith("<js>"):
        body = sel[4:] if sel.startswith("<js>") else sel[len("@js:"):]
        if body.endswith("</js>"):
            body = body[:-5]
        if _JS_BRIDGE is not None:
            try:
                res = _JS_BRIDGE.eval(
                    body.strip(),
                    result=_to_result(context),
                    variables=getattr(_JS_BRIDGE, "variables", None),
                    headers=getattr(_JS_BRIDGE, "headers", None),
                )
                return [res]
            except Exception:
                pass
        return [eval_js_best_effort(sel)]
    typ = sniff(sel)
    if typ == "xpath":
        out = eval_xpath(context, sel)
    elif typ == "json":
        out = eval_json(context, sel)
    elif typ == "regex":
        out = eval_regex_list(_to_text(context), sel)
    else:
        out = eval_css(context, sel)
    # 链式净化：rule##regex##repl（成对=替换）；单 ##regex = 删除该串
    if len(tokens) > 1:
        new_out = []
        rest = tokens[1:]
        for v in out:
            s = str(v)
            i = 0
            while i < len(rest):
                regex = rest[i]
                repl = rest[i + 1] if i + 1 < len(rest) else ""
                try:
                    s = re.sub(regex, repl, s, flags=re.S)
                except Exception:
                    pass
                i += 2
            new_out.append(s)
        out = new_out
    return out


def _to_text(context):
    if isinstance(context, str):
        return context
    if isinstance(context, list):
        return "\n".join(_to_text(x) for x in context)
    if hasattr(context, "get_text"):
        return context.get_text("\n")
    return str(context)


# ---------- 规则对象解析 ----------
_SPECIAL_KEYS = {"init", "post", "replaceRegex", "checkItem", "bookUrl", "tocUrl", "bookList", "chapterList", "list"}


def _eval_url_rule(rule_val, item, base):
    """求 bookUrl/tocUrl 这类 URL 字段。

    Legado 里 bookUrl 有两种写法，必须都支持（此前只支持第 2 种，导致 HTML 源的
    `tag.a.0@href` 被当字面量拼成 `http://站点/tag.a.0@href`，由追踪树 B-05 抓出）：
      1) **普通规则**： `tag.a.0@href` / `class.item@href` → 需要真正求值抽取
      2) **URL 模板**： `/api/book/{{$.book_id}}` → 只做 JSONPath 插值，不求值
    判据：含 `{{` 即模板，否则按规则求值。最后统一相对路径拼站点根。
    """
    if not isinstance(rule_val, str):
        return ""
    rule_val = rule_val.strip()
    if not rule_val:
        return ""

    if "{{" in rule_val:
        url = rule_val
        if isinstance(item, (dict, list)):
            for m in re.findall(r"\{\{\$\.([^}]+)\}\}", url):
                url = url.replace("{{$." + m + "}}", jsonpath_single(item, m))
    else:
        vals = evaluate(rule_val, item)
        url = _field_text(vals[0]) if vals else ""

    if url and not url.startswith(("http://", "https://", "//")):
        url = base.rstrip("/") + "/" + url.lstrip("/")
    elif url.startswith("//"):
        url = "https:" + url
    return url


def parse_object(rule_dict, root, base=""):
    """解析一条规则对象。

    返回：
    - 若存在迭代键(bookList/chapterList/list)：list[dict]，每个元素是一条记录（字段→单值）
    - 否则：list[dict]，长度 1，单条记录
    记录的 bookUrl/tocUrl 字段会被拼成完整 URL。
    """
    if not isinstance(rule_dict, dict):
        return []
    # init 先跳转（JSON 源常见）
    if "init" in rule_dict and rule_dict["init"]:
        init_vals = evaluate(rule_dict["init"], root)
        if init_vals:
            root = init_vals[0]
    iter_key = next((k for k in ("bookList", "chapterList", "list") if k in rule_dict), None)
    if iter_key is None:
        items = [root]
    else:
        with trace_node("object", "%s = %s" % (iter_key, rule_dict[iter_key])) as tn:
            items = evaluate(rule_dict[iter_key], root)
            tn.set_output(items)
            if not items:
                tn.set_note("迭代列表为空 → 后续所有字段都不会有值，先修这条")
    records = []
    for it in items:
        rec = {}
        for k, v in rule_dict.items():
            if k in _SPECIAL_KEYS:
                continue
            with trace_node("field", "%s = %s" % (k, v)) as tn:
                vals = evaluate(v, it)
                rec[k] = _field_text(vals[0]) if vals else ""
                tn.set_output(rec[k])
        if "bookUrl" in rule_dict:
            with trace_node("url", "bookUrl = %s" % rule_dict["bookUrl"]) as tn:
                rec["bookUrl"] = _eval_url_rule(rule_dict["bookUrl"], it, base)
                tn.set_output(rec["bookUrl"])
        if "tocUrl" in rule_dict:
            with trace_node("url", "tocUrl = %s" % rule_dict["tocUrl"]) as tn:
                rec["tocUrl"] = _eval_url_rule(rule_dict["tocUrl"], it, base)
                tn.set_output(rec["tocUrl"])
        records.append(rec)
    return records


def _field_text(val):
    """B-03（历史实现参考）：字段规则末段没写 `@text` 时，规则引擎默认取文本。

    我们的 eval_css 对"未显式指定模式"统一返回原始节点（迭代键需要这个行为），
    到了**字段层**必须收敛成字符串，否则 `class.author`（没写 @text）会把一个
    bs4 节点塞进结果，最终 str() 出一整段 HTML。
    """
    if isinstance(val, str):
        return val
    if hasattr(val, "get_text"):
        return val.get_text(strip=True)
    if isinstance(val, (int, float)):
        return str(val)
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        try:
            return json.dumps(val, ensure_ascii=False)
        except Exception:
            return str(val)
    return str(val)
