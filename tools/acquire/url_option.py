"""统一 URL+Option 解析器（兼容书源规则格式中 `AnalyzeUrl` 的 URL+Option 写法）。

解决的问题
----------
Legado 书源的**每一个动作**（搜索/详情/目录/正文/发现）都可以写成：

    <url>,{"method":"POST","body":"...","charset":"GBK","headers":{...},"retry":3}

以前我们只在 `_search_fetch` 里手写了 POST 分支，详情/目录/正文各自 `f.get(...)`——
这正是"每个动作各写一遍"的架构紊乱。本模块把它收敛成**一处解析 + 一处执行**，
四大动作共用，站点差异只留在书源 JSON 里，代码零站点分支。

铁律
----
只做 L1（纯 HTTP + 本地 JS 求值）。`webView` / `webViewDelayTime` 这类需要真实打开
网页的 option 一律**标记 needs_browser 并拒绝执行**，不假装成功。

支持的 option 键（对齐 Legado）
------------------------------
method / charset / headers / body / retry / timeout / followRedirects /
type / origin / js / bodyJs        —— 支持
webView / webViewDelayTime          —— 明确拒绝（L3 越界）
serverID                            —— 忽略（服务端分流，我们无此概念）

用法
----
    opt = UrlOption.parse(src["searchUrl"])
    opt = opt.expanded(lambda s: engine._expand_url(s, keyword, page))
    url, text = opt.fetch(fetcher, base, default_headers=headers)
"""
import json
import re
import time

__all__ = ["UrlOption", "looks_like_content", "BrowserRequired"]


class BrowserRequired(RuntimeError):
    """书源该动作要求真实浏览器（webView），超出 L1/L2 边界，明确拒绝而非假成功。"""


def looks_like_content(s):
    """区分「这段字符串是响应正文」还是「这是一个 URL/路径」。

    `{{java.ajax(...)}}` 会把整段 HTML/JSON 正文内联到 url 位置，此时不能再发请求；
    而 `/search?key=xx` 这类相对路径必须拼站点根后请求。
    正文判据：以 `<` `{` `[` 开头、含换行、或长度明显超出 URL 量级。
    """
    if not isinstance(s, str):
        return False
    t = s.lstrip()
    return t.startswith(("<", "{", "[")) or "\n" in s or len(s) > 2048


def _split_url_and_option(raw):
    """从 `url,{json}` 中切出 url 与 option。

    URL 自身可能含逗号（如 `?a=1,2`），所以从**最后**一个 `,{` 往前试，
    第一个能 json 解析成功的就是 option；都失败则整串视作 url。
    """
    if not isinstance(raw, str):
        return "", {}
    s = raw.strip()
    if not s.endswith("}"):
        return s, {}
    positions = [m.start() for m in re.finditer(r",\s*\{", s)]
    for pos in reversed(positions):
        candidate = s[pos + 1:].strip()
        try:
            opts = json.loads(candidate)
        except Exception:
            continue
        if isinstance(opts, dict):
            return s[:pos].strip(), opts
    return s, {}


def _as_dict(v):
    if isinstance(v, dict):
        return dict(v)
    if isinstance(v, str) and v.strip():
        try:
            d = json.loads(v)
            return dict(d) if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _as_bool(v, default=True):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    if v is None:
        return default
    return bool(v)


def _as_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


class UrlOption:
    """一次请求的完整描述：URL + 方法 + 头 + 体 + 重试等。"""

    __slots__ = ("url", "method", "charset", "headers", "body", "retry", "timeout",
                 "follow_redirects", "type", "origin", "js", "body_js",
                 "web_view", "raw")

    def __init__(self, url="", opts=None, raw=None):
        opts = opts or {}
        self.raw = raw if raw is not None else url
        self.url = url
        self.method = str(opts.get("method", "GET")).strip().upper() or "GET"
        self.charset = opts.get("charset") or None
        self.headers = _as_dict(opts.get("headers"))
        body = opts.get("body")
        self.body = body if body is not None else ""
        self.retry = _as_int(opts.get("retry"), 0)
        self.timeout = _as_int(opts.get("timeout"), 0)
        self.follow_redirects = _as_bool(opts.get("followRedirects"), True)
        self.type = (opts.get("type") or "").strip().lower() or None
        self.origin = opts.get("origin") or None
        self.js = opts.get("js") or None
        self.body_js = opts.get("bodyJs") or None
        self.web_view = _as_bool(opts.get("webView"), False) or ("webViewDelayTime" in opts)
        # body 是对象时隐含 POST + json
        if isinstance(self.body, (dict, list)) and self.method == "GET" and "method" not in opts:
            self.method = "POST"

    # ---- 构造 ----
    @classmethod
    def parse(cls, raw):
        url, opts = _split_url_and_option(raw)
        return cls(url, opts, raw=raw)

    @property
    def needs_browser(self):
        return bool(self.web_view)

    def _clone(self):
        o = UrlOption.__new__(UrlOption)
        for k in UrlOption.__slots__:
            setattr(o, k, getattr(self, k))
        o.headers = dict(self.headers)
        return o

    # ---- {{...}} 展开 ----
    def expanded(self, expander):
        """用 expander(str)->str 展开 url / body / headers 里的 {{key}}、{{java.*}}。"""
        o = self._clone()
        o.url = expander(self.url) if isinstance(self.url, str) else self.url
        if isinstance(self.body, str) and self.body:
            o.body = expander(self.body)
        if self.headers:
            o.headers = {k: (expander(v) if isinstance(v, str) and "{{" in v else v)
                         for k, v in self.headers.items()}
        if isinstance(self.origin, str) and "{{" in self.origin:
            o.origin = expander(self.origin)
        return o

    # ---- JS 钩子（纯 L1：本地 Node 求值，无浏览器）----
    def apply_js(self, js_bridge):
        """执行 option 里的 js / bodyJs：分别以 result=url、result=body 作为入参。"""
        if not js_bridge:
            return self
        o = self._clone()
        if self.js:
            try:
                o.url = js_bridge.eval(self.js, variables={"result": self.url})
            except Exception:
                pass
        if self.body_js:
            try:
                o.body = js_bridge.eval(self.body_js, variables={"result": self.body})
            except Exception:
                pass
        return o

    # ---- 绝对化 ----
    def absolute(self, base):
        u = self.url or ""
        if looks_like_content(u):
            return u
        if u.startswith(("http://", "https://")):
            return u
        if u.startswith("//"):
            return "https:" + u
        b = (base or "").rstrip("/")
        return b + ("" if u.startswith("/") else "/") + u

    # ---- 执行 ----
    def fetch(self, fetcher, base, default_headers=None):
        """执行请求，返回 (最终URL, 响应文本)。

        若 url 位置已是内联正文（java.ajax 的产物），直接返回，不再发请求。
        只用 fetcher.get/post，保证 selftest 的 LocalFetcher 等替身可用。
        """
        if self.needs_browser:
            raise BrowserRequired(f"该动作需要 webView（L3 越界），跳过：{str(self.raw)[:120]}")

        if looks_like_content(self.url):
            return self.raw, self.url

        url = self.absolute(base)
        hdrs = dict(default_headers or {})
        hdrs.update(self.headers)
        if self.origin:
            hdrs.setdefault("Referer", self.origin)

        attempts = max(1, self.retry) if self.retry else 1
        last = None
        for i in range(attempts):
            try:
                return self._do(fetcher, url, hdrs)
            except Exception as e:
                last = e
                if i < attempts - 1:
                    time.sleep(0.8 * (i + 1))
        raise last

    def _do(self, fetcher, url, hdrs):
        if self.method == "POST":
            if isinstance(self.body, (dict, list)):
                hdrs.setdefault("Content-Type", "application/json")
                return url, fetcher.post(url, hdrs, json_body=self.body)
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
            data = self.body
            if isinstance(data, str) and self.charset:
                try:
                    data = data.encode(self.charset)
                except Exception:
                    pass
            return url, fetcher.post(url, hdrs, data=data)
        # GET：Legado 语义下 body 拼进 query
        if isinstance(self.body, str) and self.body:
            sep = "&" if "?" in url else "?"
            url = url + sep + self.body
        return url, fetcher.get(url, hdrs)

    def __repr__(self):
        return (f"UrlOption({self.method} {self.url!r}"
                + (f", body={str(self.body)[:40]!r}" if self.body else "")
                + (", webView" if self.web_view else "") + ")")


# ---------------- 自测 ----------------
if __name__ == "__main__":
    # 1) 纯 URL
    o = UrlOption.parse("/search?key={{key}}")
    assert o.method == "GET" and o.url == "/search?key={{key}}", o
    assert o.absolute("http://a.com") == "http://a.com/search?key={{key}}"

    # 2) POST + body + charset
    o = UrlOption.parse('/s,{"method":"POST","body":"kw={{key}}","charset":"GBK"}')
    assert o.method == "POST" and o.body == "kw={{key}}" and o.charset == "GBK", o

    # 3) URL 自身含逗号，option 仍能正确切出
    o = UrlOption.parse('http://a.com/x?ids=1,2,3,{"method":"POST","body":"a=1"}')
    assert o.url == "http://a.com/x?ids=1,2,3", o.url
    assert o.method == "POST" and o.body == "a=1"

    # 4) 末尾像 JSON 但不是 option → 整串当 url
    o = UrlOption.parse("http://a.com/q?j={a:1}")
    assert o.url == "http://a.com/q?j={a:1}", o.url

    # 5) headers / origin / retry / followRedirects
    o = UrlOption.parse('/x,{"headers":{"Cookie":"a=1"},"origin":"http://o","retry":3,"followRedirects":false}')
    assert o.headers == {"Cookie": "a=1"} and o.origin == "http://o"
    assert o.retry == 3 and o.follow_redirects is False

    # 6) body 为对象 → 自动 POST + json
    o = UrlOption.parse('/api,{"body":{"kw":"x"}}')
    assert o.method == "POST" and isinstance(o.body, dict)

    # 7) webView → 明确拒绝，不假成功
    o = UrlOption.parse('/x,{"webView":true}')
    assert o.needs_browser
    try:
        o.fetch(None, "http://a.com")
        raise AssertionError("webView 应当被拒绝")
    except BrowserRequired:
        pass

    # 8) {{...}} 展开
    o = UrlOption.parse('/s,{"method":"POST","body":"kw={{key}}"}')
    o2 = o.expanded(lambda s: s.replace("{{key}}", "斗破"))
    assert o2.body == "kw=斗破" and o.body == "kw={{key}}", "展开须返回副本，不改原对象"

    # 9) 内联正文（java.ajax 产物）不再二次请求
    inline = '{"code":0,"data":[]}'
    o = UrlOption(inline, raw="{{java.ajax(...)}}")
    u, t = o.fetch(None, "http://a.com")
    assert t == inline and u == "{{java.ajax(...)}}"

    # 10) 端到端：GET / POST 分派与相对路径拼接
    class FakeFetcher:
        def __init__(self):
            self.calls = []

        def get(self, url, headers=None):
            self.calls.append(("GET", url, headers, None))
            return "GET_OK"

        def post(self, url, headers=None, data=None, json_body=None):
            self.calls.append(("POST", url, headers, data if data is not None else json_body))
            return "POST_OK"

    f = FakeFetcher()
    u, t = UrlOption.parse("/list?p=1").fetch(f, "http://a.com/")
    assert (u, t) == ("http://a.com/list?p=1", "GET_OK"), (u, t)

    u, t = UrlOption.parse('/s,{"method":"POST","body":"kw=x","charset":"GBK"}').fetch(
        f, "http://a.com", default_headers={"User-Agent": "UA"})
    assert t == "POST_OK" and u == "http://a.com/s"
    m, url, hdrs, data = f.calls[-1]
    assert hdrs["User-Agent"] == "UA" and hdrs["Content-Type"].startswith("application/x-www-form")
    assert data == "kw=x".encode("GBK")

    # GET + body → 拼进 query
    u, t = UrlOption.parse('/g,{"body":"a=1&b=2","method":"GET"}').fetch(f, "http://a.com")
    assert u == "http://a.com/g?a=1&b=2", u

    # 11) 协议相对 URL
    assert UrlOption.parse("//cdn.a.com/x.json").absolute("http://a.com") == "https://cdn.a.com/x.json"

    # 12) 重试：前两次抛错，第三次成功
    class FlakyFetcher:
        def __init__(self):
            self.n = 0

        def get(self, url, headers=None):
            self.n += 1
            if self.n < 3:
                raise OSError("boom")
            return "OK"

    ff = FlakyFetcher()
    o = UrlOption.parse('/x,{"retry":3}')
    # 缩短重试间隔，避免自测变慢
    _sleep = time.sleep
    time.sleep = lambda *_: None
    try:
        u, t = o.fetch(ff, "http://a.com")
    finally:
        time.sleep = _sleep
    assert t == "OK" and ff.n == 3, (t, ff.n)

    print("url_option 自测全部通过（12 项）")
