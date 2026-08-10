"""规则执行追踪树（参考 Legado_Max 的 `RuleExecutionNode` 思路）。

为什么需要它：书源规则是一条链（`class.x@tag.a.0@href##\\d+##`），失败时只看到
"结果为空"，无法知道是哪一段断的。追踪树把每一段的输入/输出/匹配数/耗时/异常
都记下来，失败时能直接指到"第 2 段 @tag.a.0 匹配 0 个元素"，这才让写源/修源可维护。

设计约束：
- **零第三方依赖**（纯 stdlib），符合"轻"原则。
- **关闭时零开销**：未启用追踪时 `node()` 走空实现，不建对象、不算耗时。
- 输出两种形态：`render()` 人/agent 可读文本树；`to_dict()` 结构化 JSON。

典型用法::

    tr = RuleTrace("搜索", enabled=True)
    set_tracer(tr)
    ...跑规则...
    set_tracer(None)
    print(tr.render())
"""
import json
import time
from contextlib import contextmanager

__all__ = [
    "RuleTrace", "TraceNode", "set_tracer", "get_tracer", "trace_node",
]

# 规则类型 → 展示名（对齐 Legado_Max RuleType）
TYPE_NAMES = {
    "css": "CSS选择器",
    "xpath": "XPath",
    "json": "JSONPath",
    "regex": "正则",
    "js": "JavaScript",
    "replace": "净化替换",
    "url": "URL模板",
    "field": "字段",
    "object": "规则对象",
    "root": "根",
}


def _preview(val, limit):
    """把任意值压成短预览串，避免追踪本身吃内存。"""
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        s = "[%d项] " % len(val) + " | ".join(_preview(v, 40) or "" for v in val[:3])
    elif isinstance(val, (dict,)):
        try:
            s = json.dumps(val, ensure_ascii=False)
        except Exception:
            s = str(val)
    else:
        s = str(val)
    s = " ".join(s.split())          # 折叠空白，单行显示
    return s if len(s) <= limit else s[:limit] + "…"


class TraceNode:
    __slots__ = ("rule_type", "rule", "input", "output", "match_count",
                 "duration_ms", "error", "children", "note")

    def __init__(self, rule_type, rule):
        self.rule_type = rule_type
        self.rule = rule
        self.input = None
        self.output = None
        self.match_count = None
        self.duration_ms = None
        self.error = None
        self.note = None
        self.children = []

    # --- 供求值代码调用 ---
    def set_input(self, val, limit=120):
        self.input = _preview(val, limit)

    def set_output(self, val, limit=120):
        self.output = _preview(val, limit)
        if isinstance(val, (list, tuple)):
            self.match_count = len(val)

    def set_note(self, text):
        self.note = text

    # --- 判定 ---
    def ok(self):
        return self.error is None and all(c.ok() for c in self.children)

    def empty(self):
        """本段是否"没抓到东西"——定位断链点的关键信号。"""
        return self.match_count == 0 or self.output in ("", "[0项] ", None)

    def total_ms(self):
        return (self.duration_ms or 0) + sum(c.total_ms() for c in self.children)

    def to_dict(self):
        d = {
            "type": self.rule_type,
            "rule": self.rule,
            "input": self.input,
            "output": self.output,
            "matchCount": self.match_count,
            "durationMs": self.duration_ms,
        }
        if self.error:
            d["error"] = self.error
        if self.note:
            d["note"] = self.note
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


class _NullNode:
    """关闭追踪时的空节点：所有写入都是 no-op，保证零开销。"""
    __slots__ = ()

    def set_input(self, *a, **k):
        pass

    def set_output(self, *a, **k):
        pass

    def set_note(self, *a, **k):
        pass


_NULL = _NullNode()


class RuleTrace:
    def __init__(self, name="", enabled=True, preview=120):
        self.name = name
        self.enabled = enabled
        self.preview = preview
        self.root = TraceNode("root", name or "(root)")
        self._stack = [self.root]

    @contextmanager
    def node(self, rule_type, rule):
        if not self.enabled:
            yield _NULL
            return
        n = TraceNode(rule_type, rule if isinstance(rule, str) else str(rule))
        self._stack[-1].children.append(n)
        self._stack.append(n)
        t0 = time.perf_counter()
        try:
            yield n
        except Exception as e:
            n.error = "%s: %s" % (type(e).__name__, e)
            raise
        finally:
            n.duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            self._stack.pop()

    # --- 汇总 ---
    def ok(self):
        return self.root.ok()

    def flatten(self):
        out = []

        def walk(n):
            out.append(n)
            for c in n.children:
                walk(c)
        walk(self.root)
        return out

    def first_break(self):
        """返回第一个"有规则但抓到 0 项"的节点——断链点。给 agent 修源用。"""
        for n in self.flatten():
            if n.rule_type == "root":
                continue
            if n.error:
                return n
            if n.match_count == 0:
                return n
        return None

    def to_dict(self):
        return {
            "name": self.name,
            "ok": self.ok(),
            "totalMs": self.root.total_ms(),
            "tree": self.root.to_dict(),
        }

    def render(self, show_input=False):
        """渲染成文本树。默认不显示输入（太长），排错时开 show_input=True。"""
        lines = ["规则执行追踪: %s  [%s]  %.2fms" % (
            self.name or "(未命名)", "成功" if self.ok() else "有失败", self.root.total_ms())]

        def walk(n, prefix, last):
            if n is not self.root:
                mark = "└─ " if last else "├─ "
                tag = TYPE_NAMES.get(n.rule_type, n.rule_type)
                cnt = "" if n.match_count is None else "  →%d项" % n.match_count
                bad = ""
                if n.error:
                    bad = "  ✗ %s" % n.error
                elif n.match_count == 0:
                    bad = "  ✗ 未匹配"
                lines.append("%s%s[%s] %s%s  %sms%s" % (
                    prefix, mark, tag, n.rule, cnt, n.duration_ms, bad))
                if show_input and n.input is not None:
                    lines.append("%s%s  入: %s" % (prefix, "   " if last else "│  ", n.input))
                if n.output is not None:
                    lines.append("%s%s  出: %s" % (prefix, "   " if last else "│  ", n.output))
                if n.note:
                    lines.append("%s%s  注: %s" % (prefix, "   " if last else "│  ", n.note))
                prefix = prefix + ("   " if last else "│  ")
            for i, c in enumerate(n.children):
                walk(c, prefix, i == len(n.children) - 1)

        walk(self.root, "", True)
        brk = self.first_break()
        if brk is not None:
            lines.append("")
            lines.append("⚠ 断链点: [%s] %s  ← 修源时先改这一段" % (
                TYPE_NAMES.get(brk.rule_type, brk.rule_type), brk.rule))
        return "\n".join(lines)


# ---------- 全局当前追踪器（rules.py 通过它埋点，无需改函数签名）----------
_CURRENT = None


def set_tracer(tracer):
    global _CURRENT
    _CURRENT = tracer


def get_tracer():
    return _CURRENT


@contextmanager
def trace_node(rule_type, rule):
    """埋点入口。无追踪器时零开销直接 yield 空节点。"""
    cur = _CURRENT
    if cur is None or not cur.enabled:
        yield _NULL
        return
    with cur.node(rule_type, rule) as n:
        yield n


if __name__ == "__main__":
    # 自测 1：正常链路
    tr = RuleTrace("搜索-正常")
    set_tracer(tr)
    with trace_node("object", "ruleSearch") as o:
        with trace_node("css", "class.bookbox") as n:
            n.set_output(["<div/>", "<div/>"])
        with trace_node("css", "tag.h4@text") as n:
            n.set_output(["斗破苍穹", "斗罗大陆"])
    set_tracer(None)
    assert tr.ok(), "正常链路应成功"
    assert tr.first_break() is None, "正常链路不应有断链点"
    print(tr.render())

    # 自测 2：断链定位
    tr2 = RuleTrace("搜索-断链")
    set_tracer(tr2)
    with trace_node("object", "ruleSearch"):
        with trace_node("css", "class.bookbox") as n:
            n.set_output(["<div/>"])
        with trace_node("css", "class.authorNAME@text") as n:
            n.set_output([])          # 拼错 class → 0 项
        with trace_node("css", "tag.h4@text") as n:
            n.set_output(["斗破苍穹"])
    set_tracer(None)
    brk = tr2.first_break()
    assert brk is not None and brk.rule == "class.authorNAME@text", "断链点定位错误: %s" % brk
    print()
    print(tr2.render())

    # 自测 3：异常捕获 + 关闭时零开销
    tr3 = RuleTrace("异常")
    set_tracer(tr3)
    try:
        with trace_node("regex", ":[bad("):
            raise ValueError("正则编译失败")
    except ValueError:
        pass
    set_tracer(None)
    assert not tr3.ok(), "异常应标记失败"
    assert "正则编译失败" in tr3.render()

    set_tracer(None)
    with trace_node("css", "whatever") as n:
        n.set_output(["x"])           # 无追踪器时不应报错
    print()
    print("rule_trace 自测全部通过")
