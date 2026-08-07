#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
js_bridge.py — 在本机 Node 里执行 Legado 书源规则中的 @js: / {{java.*}} 片段。

设计（纯 L1，无浏览器、无外部 key）
------------------------------------
- 规则里数千处 @js:/{{}} 片段绝大多数是字符串处理 + java.* 加密/签名/编解码/会话变量，
  用 Node 原生 crypto / 字符串能力即可复现，无需浏览器渲染。
- 唯一需要网络的 java.ajax(url) 由 Python 侧 fetcher 预取（本质就是一次 GET），
  以「URL → 响应体」映射注入 Node，避免"Node 里同步发请求"的难题。
- 只有真正需要 webView/startBrowser 的源才被拒绝（见 url_option.BrowserRequired）。

性能（吸收台账 B-06）
--------------------
PyExecJS 每次 call 都会**重启一个 Node 进程**，实测单次约 210ms —— 一本千章书仅
进程启动就要 3 分半。因此默认走**常驻 Node worker**：
- 进程只起一次，行分隔 JSON 协议（一行请求 / 一行响应）；
- Node 侧用 `vm.Script` 按代码文本哈希缓存**编译结果**，重复规则零重编译；
- `result` / 变量 / ajax 结果都作为**独立字段**传入（不内联进代码文本），
  这样同一条规则在不同章节间代码文本恒定，缓存才真正命中。
Node 起不来时自动回退 PyExecJS，功能不受影响，只是慢。

作用域（吸收台账 B-07）
----------------------
java.put/get 分 source / book / chapter 三层，写入最内层、读取逐层回溯。
换书调用 reset("book")、换章调用 reset("chapter")，避免跨书跨章串变量。
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_JS = os.path.join(HERE, "js_runtime.js")

# java.ajax('literal-url') —— 只有字面量 URL 能被预取；动态 URL 返回空串（与旧行为一致）
_AJAX_RE = re.compile(r"java\.ajax\(\s*(['\"])(.*?)\1\s*\)")

# 常驻 worker 的循环：读一行 JSON → 求值 → 写一行 JSON
_WORKER_LOOP = r"""
const vm = require('vm');
const readline = require('readline');
const __scripts = new Map();

function handle(req) {
  if (req.reset) globalThis.__reset(req.reset);
  if (req.vars) globalThis.__putVars(req.vars, req.varLevel || 'book');
  if (req.scope) globalThis.__setScope(req.scope);
  globalThis.__ajaxMap = req.ajax || {};
  globalThis.result = (req.result === undefined || req.result === null) ? '' : req.result;
  if (!req.code) return '';
  let script = __scripts.get(req.code);
  if (!script) {
    script = new vm.Script(req.code, { filename: 'rule.js' });
    __scripts.set(req.code, script);
  }
  let v = script.runInThisContext();
  if (v === undefined || v === null) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
  if (!line) return;
  let out;
  try {
    out = { ok: true, v: handle(JSON.parse(line)) };
  } catch (e) {
    out = { ok: false, e: String((e && e.message) || e) };
  }
  process.stdout.write(JSON.stringify(out) + '\n');
});
rl.on('close', () => process.exit(0));
"""


def _find_node():
    """优先用受管 Node，其次 PATH 上的 node。"""
    managed = os.path.join(
        os.path.expanduser("~"), ".workbuddy", "binaries", "node",
        "versions", "22.22.2", "node.exe" if os.name == "nt" else "node")
    if os.path.exists(managed):
        return managed
    for name in ("node", "nodejs"):
        p = shutil.which(name)
        if p:
            return p
    return None


class NodeWorker:
    """常驻 Node 子进程，行分隔 JSON 协议。崩溃自动重启。"""

    def __init__(self, node_path, runtime_js):
        self.node = node_path
        self.runtime = runtime_js
        self.proc = None
        self._lock = threading.Lock()
        self._boot_file = None
        self._start()
        atexit.register(self.close)

    def _start(self):
        import tempfile
        src = open(self.runtime, encoding="utf-8").read() + "\n" + _WORKER_LOOP
        fd, path = tempfile.mkstemp(suffix="_worker.js", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        self._boot_file = path
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW，不弹黑框
        self.proc = subprocess.Popen(
            [self.node, path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", bufsize=1, **kwargs)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def call(self, payload):
        with self._lock:
            if not self.alive():
                self._start()
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            try:
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
                out = self.proc.stdout.readline()
            except Exception:
                self._start()          # 管道断了：重启一次再试
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
                out = self.proc.stdout.readline()
            if not out:
                raise RuntimeError("Node worker 无响应（进程可能已退出）")
            resp = json.loads(out)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("e") or "unknown js error")
        return resp.get("v", "")

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.close()
                self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        finally:
            if self._boot_file and os.path.exists(self._boot_file):
                try:
                    os.remove(self._boot_file)
                except Exception:
                    pass


class JsBridge:
    """在 Node 里求值 Legado 规则的 @js: / {{java.*}} 片段。"""

    def __init__(self, fetcher=None, prefer_worker=True):
        self._fetcher = fetcher            # callable(url, headers=None) -> str
        self.variables = {}                # 兼容旧接口：外部可直接赋值
        self.headers = {}
        self._worker = None
        self._ctx = None                   # PyExecJS 兜底上下文
        self._ajax_cache = {}
        self.backend = "none"
        if prefer_worker:
            node = _find_node()
            if node:
                try:
                    self._worker = NodeWorker(node, RUNTIME_JS)
                    self._worker.call({"code": "1+1"})   # 冒烟，确认真的能用
                    self.backend = "worker"
                except Exception:
                    self._worker = None
        if self._worker is None:
            import execjs
            self._ctx = execjs.compile(open(RUNTIME_JS, encoding="utf-8").read())
            self.backend = "execjs"

    # ---- 作用域（B-07）----
    def reset(self, level="chapter"):
        """清空指定层及其内层变量。level ∈ {source, book, chapter}。"""
        if self._worker:
            try:
                self._worker.call({"reset": level})
            except Exception:
                pass
        else:
            self.variables = {} if level in ("source", "book") else self.variables

    # ---- ajax 预取 ----
    def _prefetch_ajax(self, expression, headers):
        urls = [m.group(2) for m in _AJAX_RE.finditer(expression)]
        if not urls:
            return {}
        out = {}
        for u in urls:
            if u in self._ajax_cache:
                out[u] = self._ajax_cache[u]
                continue
            body = ""
            if self._fetcher:
                try:
                    body = self._fetcher(u, headers) or ""
                except Exception:
                    body = ""
            self._ajax_cache[u] = body
            out[u] = body
        return out

    def eval(self, expression, result="", variables=None, headers=None, scope="chapter"):
        """求值表达式。

        expression: JS 代码片段（可含 java.*）
        result:     当前待处理内容（注入为 JS 全局 result）
        variables:  会话变量字典（注入到 book 层，并声明同名裸变量）
        headers:    供 java.ajax 预取使用的请求头
        scope:      java.put 的写入层（source/book/chapter）
        """
        expr = expression or ""
        hdrs = headers if headers is not None else self.headers
        merged = dict(self.variables or {})
        if variables:
            merged.update(variables)
        ajax = self._prefetch_ajax(expr, hdrs)

        if self._worker:
            try:
                return self._worker.call({
                    "code": expr, "result": result, "vars": merged,
                    "ajax": ajax, "scope": scope,
                })
            except RuntimeError as e:
                raise RuntimeError("JS求值失败: %s | expr=%s" % (e, expr[:200]))
        return self._eval_execjs(expr, result, merged, ajax)

    def _eval_execjs(self, expr, result, variables, ajax):
        """兜底路径：每次重新拼装代码（慢，但功能一致）。"""
        pre = []
        if variables:
            pre.append("globalThis.__putVars(%s,'book');" % json.dumps(variables, ensure_ascii=False))
        pre.append("globalThis.__ajaxMap = %s;" % json.dumps(ajax, ensure_ascii=False))
        pre.append("globalThis.result = %s;" % json.dumps(result, ensure_ascii=False))
        code = "\n".join(pre) + "\n" + expr
        try:
            out = self._ctx.call("__run", code)
        except Exception as e:
            raise RuntimeError("JS求值失败: %s | expr=%s" % (e, expr[:200]))
        return "" if out is None else str(out)

    def close(self):
        if self._worker:
            self._worker.close()
            self._worker = None


if __name__ == "__main__":
    import base64
    import hashlib  # noqa: F401  (保留：部分书源调试时会用到)
    import sys
    import time
    sys.path.insert(0, HERE)

    def fake_fetch(url, headers=None):
        return '{"ok":1,"name":"番茄"}'

    b = JsBridge(fetcher=fake_fetch)
    print("后端:", b.backend)

    # 1) 字符串清理
    r1 = b.eval(r"result.replace(/正文卷\.?/,'').trim()", result="  正文卷.测试 ")
    assert r1 == "测试", r1
    print("1)", r1)

    # 2) md5
    r2 = b.eval("java.md5Encode('abc')")
    assert r2 == "900150983cd24fb0d6963f7d28e17f72", r2
    print("2)", r2)

    # 3) AES 解密与 Python 侧一致
    from transforms import aes_base64_decode_to_string as py_aes
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    pt = '{"code":0,"data":"ok"}'
    key, iv = "f041c49714d39908", "0123456789abcdef"
    ct = AES.new(key.encode(), AES.MODE_CBC, iv.encode()).encrypt(pad(pt.encode(), 16))
    b64 = base64.b64encode(ct).decode()
    r3p = py_aes(b64, key, "AES/CBC/PKCS5Padding", iv)
    r3n = b.eval('java.aesBase64DecodeToString(%s,"%s","AES/CBC/PKCS5Padding","%s")'
                 % (json.dumps(b64), key, iv))
    assert r3p == r3n == pt, (r3p, r3n)
    print("3) python == node:", r3n)

    # 4) 会话变量
    r4 = b.eval("java.put('x','hello'); java.get('x')")
    assert r4 == "hello", r4
    print("4)", r4)

    # 5) ajax 预取（Legado 中 java.ajax 返回字符串，真实写法需 JSON.parse）
    r5 = b.eval("JSON.parse(java.ajax('https://example.com/api')).name", result="{}")
    assert r5 == "番茄", r5
    print("5)", r5)

    # 6) B-07 分层作用域：chapter 层变量换章即清，book 层保留
    b.reset("source")
    b.eval("java.put('bk','B')", scope="book")
    b.eval("java.put('ch','C')", scope="chapter")
    assert b.eval("java.get('bk')+'/'+java.get('ch')") == "B/C"
    b.reset("chapter")
    assert b.eval("java.get('bk')+'/'+java.get('ch')") == "B/", "换章应只清 chapter 层"
    b.reset("book")
    assert b.eval("java.get('bk')+'/'+java.get('ch')") == "/", "换书应清 book+chapter"
    print("6) 分层作用域 OK（chapter→book→source 回溯，逐层清理）")

    # 7) B-06 编译缓存 + 常驻进程：同一规则跑 200 次
    b.reset("source")
    N = 200
    t0 = time.time()
    for i in range(N):
        b.eval("result.trim().toUpperCase()", result="  ab%d  " % i)
    dt = (time.time() - t0) * 1000
    print("7) %d 次同规则求值 %.0f ms，单次 %.2f ms（后端 %s）" % (N, dt, dt / N, b.backend))
    if b.backend == "worker":
        assert dt / N < 20, "常驻 worker 单次应远低于 20ms，实测 %.2f ms" % (dt / N)

    # 8) 裸变量名可用（{{java.md5Encode(key)}} 场景）
    r8 = b.eval("java.md5Encode(key)", variables={"key": "abc"})
    assert r8 == "900150983cd24fb0d6963f7d28e17f72", r8
    print("8) 裸变量注入 OK")

    b.close()
    print("js_bridge 自测全部通过")
