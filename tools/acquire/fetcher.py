"""HTTP 抓取层（L1 升级版）：稳健的纯解析型 HTTP 抓取层。

相对 v1 的增强：
- 底层从 requests 换为 httpx（支持 HTTP/2，默认关闭，缺失 h2 自动降级 HTTP/1.1，绝不崩）。
- UA 池：桌面/手机两套真实 UA 随机轮换，规避基础 UA 检测。
- Cookie 会话：client.cookies 持久化；set_cookies() 注入用户 cookie，get_cookies() 回传。
- POST 三形式：表单(application/x-www-form-urlencoded) / 原样(raw bytes) / json。
- 编码探测：gb2312→gb18030，iso-8859-1 回退时按 meta 或尝试 gb18030 解码，最后 utf-8。
- 保留原接口：Fetcher() / get() / post() / parse_header()，与 source_engine.py 兼容。
"""
import ast
import json
import time
import random
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent


# ---------- UA 池 ----------
UA_DESKTOP = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
UA_MOBILE = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1",
]


def parse_header(header_str):
    """把 Legado 的 header 字符串（如 "{'User-Agent':'...'}"）解析成 dict。"""
    if not header_str:
        return {}
    try:
        h = ast.literal_eval(header_str)
        return h if isinstance(h, dict) else {}
    except Exception:
        return {}


# ---------- 每域名限流（B-24，配置与书源规则分离）----------
# 进程内按 host 记录上次请求时刻，请求前按 1/qps 最小间隔节流；可按域名覆盖 QPS。
# 全局共享一个限流器，保证「同一域名无论被几个引擎并发抓，都礼貌」。
_DOMAIN_STATE = {}                       # host -> {"lock": Lock, "last": float}
_DOMAIN_STATE_LOCK = threading.Lock()
_DEFAULT_RATE_CONFIG = {"default_qps": 1.0, "per_domain": {}}


def _host_of(url):
    try:
        netloc = urlparse(url).netloc
        return netloc or "__rel__"
    except Exception:
        return "__rel__"


def _load_rate_config():
    """从 config/rate_limit.json 读全局/每域名 QPS（与书源规则分离）。文件缺省用默认。"""
    p = ROOT / "config" / "rate_limit.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            cfg.setdefault("default_qps", _DEFAULT_RATE_CONFIG["default_qps"])
            cfg.setdefault("per_domain", {})
            return cfg
        except Exception:
            pass
    return dict(_DEFAULT_RATE_CONFIG)


class RateLimiter:
    """每域名礼貌爬取：最小请求间隔 = 1/qps；qps<=0 表示不限流。

    clock / sleeper 可注入，便于确定性单测（无需真实 sleep）。
    """

    def __init__(self, default_qps=1.0, per_domain=None, clock=None, sleeper=None):
        self.default_qps = default_qps
        self.per_domain = per_domain or {}
        self._clock = clock or time.time
        self._sleep = sleeper or time.sleep

    def interval_for(self, host):
        qps = self.per_domain.get(host, self.default_qps)
        return (1.0 / qps) if qps and qps > 0 else 0.0

    def acquire(self, host):
        iv = self.interval_for(host)
        if iv <= 0:
            return
        with _DOMAIN_STATE_LOCK:
            st = _DOMAIN_STATE.get(host)
            if st is None:
                st = _DOMAIN_STATE[host] = {"lock": threading.Lock(), "last": 0.0}
        with st["lock"]:
            now = self._clock()
            wait = st["last"] + iv - now
            if wait > 0:
                self._sleep(min(wait, 5.0))   # 单域名单次最多等 5s，防卡死
            st["last"] = self._clock()


# 全局共享限流器（按需惰性加载配置）
_GLOBAL_LIMITER = None


def get_global_limiter():
    global _GLOBAL_LIMITER
    if _GLOBAL_LIMITER is None:
        cfg = _load_rate_config()
        _GLOBAL_LIMITER = RateLimiter(cfg["default_qps"], cfg.get("per_domain", {}))
    return _GLOBAL_LIMITER


# ---------- 限流自测（B-24 回归，确定性、不联网）----------
def selftest():
    fake = {"t": 1000.0}
    sleeps = []

    def clock():
        return fake["t"]

    def sleeper(d):
        sleeps.append(d)
        fake["t"] += d

    rl = RateLimiter(default_qps=10.0, clock=clock, sleeper=sleeper)  # 0.1s 间隔
    rl.acquire("a.com")                       # last=1000
    rl.acquire("a.com")                       # 需等 0.1s
    assert abs(sleeps[-1] - 0.1) < 1e-9, sleeps
    rl.acquire("b.com")                       # 不同域名不等待
    assert len(sleeps) == 1, sleeps
    assert abs(rl.interval_for("x") - 0.1) < 1e-9
    # qps=0 不限流
    rl0 = RateLimiter(default_qps=0, clock=clock, sleeper=sleeper)
    rl0.acquire("c.com")
    rl0.acquire("c.com")
    assert len(sleeps) == 1, "qps=0 不应节流"
    # 每域名覆盖
    rl2 = RateLimiter(default_qps=1.0, per_domain={"fast.com": 20.0}, clock=clock, sleeper=sleeper)
    assert abs(rl2.interval_for("fast.com") - 0.05) < 1e-9
    print("fetcher 限流自测通过：每域名 1/qps 节流 + 跨域名不互等 + qps=0 关闭（B-24）")
    return True


class Fetcher:
    def __init__(self, proxy=None, timeout=20, delay=0.0, http2=True, verify=False,
                 ua_mode="desktop", rate_limiter=None):
        """
        proxy: "http://host:port" 或 None
        delay: 每个请求后的停顿（秒），用作简易限流（与每域名限流并存）
        http2: 是否启用 HTTP/2（h2 包缺失时自动降级，不报错）
        ua_mode: "desktop" / "mobile" 选择 UA 池
        rate_limiter: 每域名限流器（默认用全局共享实例，配置见 config/rate_limit.json）
        """
        self.timeout = timeout
        self.delay = delay
        self.ua_mode = ua_mode
        self._ua_pool = UA_MOBILE if ua_mode == "mobile" else UA_DESKTOP
        # httpx>=0.28 用 proxy=（单 URL 或 httpx.Proxy），不再接受 dict
        client_kwargs = dict(verify=verify, timeout=timeout, follow_redirects=True)
        if proxy:
            client_kwargs["proxy"] = proxy
        # http2 缺失则降级，绝不因缺少 h2 崩溃
        try:
            self.client = httpx.Client(http2=bool(http2), **client_kwargs)
        except Exception:
            self.client = httpx.Client(**client_kwargs)
        # 默认基础头
        self.client.headers["User-Agent"] = random.choice(self._ua_pool)
        self.client.headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json;q=0.8,*/*;q=0.7"
        )
        self.client.headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
        # 每域名限流（B-24）：默认共享全局实例，配置与书源规则分离
        self.limiter = rate_limiter or get_global_limiter()

    # ---- cookie 会话 ----
    def set_cookies(self, cookie_str):
        """注入 cookie 字符串（name=value; name2=value2）到会话，用于需登录态的来源。"""
        if not cookie_str:
            return
        for part in cookie_str.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            self.client.cookies.set(k.strip(), v)

    def get_cookies(self):
        """回传当前会话所有 cookie（name=value; ...），便于持久化/调试。"""
        return "; ".join(f"{k}={v}" for k, v in self.client.cookies.items())

    def _rotate_ua(self):
        return random.choice(self._ua_pool)

    # ---- 编码探测 ----
    @staticmethod
    def _cjk_ratio(text):
        """文本里 CJK 汉字占比，用于从候选编码里挑出正确的那个。"""
        if not text:
            return 0.0
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        return cjk / len(text)

    @staticmethod
    def _decode(resp):
        """鲁棒解码：中文小说源常把 GBK 正文声明成 utf-8（错配），
        不能盲信声明 charset。用「候选编码→中文占比」启发式选最优。"""
        raw = resp.content
        # 候选编码：声明 / 推断 / 中文站兜底
        candidates = []
        declared = (resp.encoding or "").lower()
        if declared and declared not in ("ascii", "iso-8859-1"):
            candidates.append(declared)
        for enc in ("gb18030", "utf-8", "gbk", "gb2312"):
            if enc not in candidates:
                candidates.append(enc)
        best_enc, best_text, best_score = None, None, -1.0
        for enc in candidates:
            try:
                text = raw.decode(enc)
            except Exception:
                continue
            score = Fetcher._cjk_ratio(text)
            # 同等占比时优先声明/utf-8，减少无谓重解码
            if score > best_score:
                best_score, best_enc, best_text = score, enc, text
        if best_text is not None:
            resp.encoding = best_enc
            return best_text
        return raw.decode("utf-8", errors="replace")

    # ---- 请求核心 ----
    def request(self, url, method="GET", headers=None, data=None, json_body=None, retries=2):
        hdrs = dict(headers or {})
        if not any(k.lower() == "user-agent" for k in hdrs):
            hdrs["User-Agent"] = self._rotate_ua()
        # 每域名礼貌节流（B-24）：请求前按 1/qps 最小间隔等待
        self.limiter.acquire(_host_of(url))
        last_err = None
        for attempt in range(retries + 1):
            try:
                if method == "POST":
                    if json_body is not None:
                        r = self.client.post(url, headers=hdrs, json=json_body)
                    elif data is not None:
                        r = self.client.post(url, headers=hdrs, data=data)
                    else:
                        r = self.client.post(url, headers=hdrs)
                else:
                    r = self.client.get(url, headers=hdrs)
                r.raise_for_status()
                if self.delay:
                    time.sleep(self.delay)
                return self._decode(r)
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(1.5 * attempt)
        raise last_err

    def get(self, url, headers=None):
        return self.request(url, "GET", headers)

    def post(self, url, headers=None, data=None, json_body=None):
        return self.request(url, "POST", headers, data=data, json_body=json_body)

    def get_bytes(self, url, headers=None):
        """下载二进制（漫画页图片 / 音频），返回 bytes（不解码、不解码 charset）。

        漫画页是纯 L1：img src 用 CSS/XPath 取到后，这里只负责把字节拉回来。
        """
        hdrs = dict(headers or {})
        if not any(k.lower() == "user-agent" for k in hdrs):
            hdrs["User-Agent"] = self._rotate_ua()
        self.limiter.acquire(_host_of(url))
        last_err = None
        for attempt in range(3):
            try:
                r = self.client.get(url, headers=hdrs)
                r.raise_for_status()
                return r.content
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(1.5 * attempt)
        raise last_err


if __name__ == "__main__":
    selftest()
