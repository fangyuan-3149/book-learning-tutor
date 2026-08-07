"""书源导入外化工具（授业 · 给 Skill 调用的统一入口）

目标：把「手动找位置、改格式、再验证」这套散落流程，收敛成**一个命令**：
    输入一个书源订阅/聚合 URL → 自动抓取 → 自动识别格式（数组/单源/
    Legado shuyuan 订阅包装/base64+gzip）→ 归一为 SourceEngine 兼容 dict →
    用 L1 引擎逐一校验可用性 → 可用源写入 data/sources/imported/verified.json
    （自动并入后续搜索范围）；不可用源附**具体原因**（死域/超时/需登录/CF拦/
    引擎异常 trace），实现「不可用也能自行排查」。

CLI：
    python import_source.py <url> [--kw 斗破苍穹] [--max N] [--no-write]
    python import_source.py --selftest

设计铁律（对齐项目）：只做 L1，最多 L2；不显式开网页；依赖最小化。
"""

import sys
import json
import base64
import gzip
import hashlib
import time
from pathlib import Path
from collections import Counter
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetcher import Fetcher
from source_engine import SourceEngine

IMPORTED_DIR = ROOT / "data" / "sources" / "imported"
IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
VERIFIED = IMPORTED_DIR / "verified.json"
RAW_DIR = ROOT / "data" / "sources" / "imported_raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def _log(msg, verbose=True):
    if verbose:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# 1) 格式识别：把各种书源订阅形态归一为「源对象列表」
# ---------------------------------------------------------------------------
def unwrap(text):
    """返回 (obj, fmt)。obj 可能是 list / dict / None。"""
    t = text.strip()
    # a0) 返回的是网页而不是 JSON（最常见误用：给了仓库页而非 raw 直链）
    if t[:200].lower().lstrip().startswith(("<!doctype", "<html", "<?xml")):
        return None, "html-page"
    # a) 先尝试纯 JSON 解析
    obj = None
    try:
        obj = json.loads(t)
    except Exception:
        pass
    if obj is not None:
        if isinstance(obj, list):
            return obj, "plain"
        if isinstance(obj, dict):
            if "bookSourceName" in obj or "ruleSearch" in obj:
                return obj, "plain"  # 单源
            if "code" in obj or "origin" in obj:
                # b) Legado shuyuan 订阅包装
                code = obj.get("code") or obj.get("origin") or ""
                if not isinstance(code, (str, bytes)):
                    return obj, "plain-dict"
                try:
                    raw = base64.b64decode(code)
                    try:
                        return json.loads(gzip.decompress(raw)), "shuyuan+gzip"
                    except Exception:
                        pass
                    try:
                        return json.loads(raw), "shuyuan+json"
                    except Exception:
                        pass
                except Exception as e:
                    return None, f"shuyuan-decode-fail:{e}"
                return obj, "plain-dict"
            return obj, "plain-dict"  # 登录页/错误页包装等
        return obj, "plain"
    # c) 裸 base64 blob
    try:
        raw = base64.b64decode(t)
        try:
            return json.loads(gzip.decompress(raw)), "base64+gzip"
        except Exception:
            pass
        try:
            return json.loads(raw), "base64+json"
        except Exception:
            pass
    except Exception:
        pass
    return None, "unrecognized"


def normalize(obj):
    """源对象列表化。"""
    if isinstance(obj, dict) and ("bookSourceName" in obj or "ruleSearch" in obj):
        return [obj]
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def _looks_like_login_page(obj):
    s = json.dumps(obj, ensure_ascii=False).lower()
    return ("user_not_login" in s) or ("未登录" in s) or ("login" in s and "code" in s)


# ---------------------------------------------------------------------------
# 2) 错误分类（死源可救性判定）
# ---------------------------------------------------------------------------
def classify_error(e):
    s = str(e)
    sl = s.lower()
    if any(k in s for k in ("getaddrinfo", "connecterror", "nameresolution", "nodename")):
        return "DNS_FAIL"
    if "timed out" in sl or "timeout" in sl:
        return "TIMEOUT"
    if "403" in s:
        return "HTTP_403"
    if "404" in s:
        return "HTTP_404"
    if "user_not_login" in sl or "未登录" in sl or "login" in sl:
        return "NEED_LOGIN"
    # CF 反爬标记
    if any(k in s for k in ("just a moment", "checking your browser", "ddos protection")):
        return "CF_BLOCKED"
    # 我们引擎自身的规则求值异常（非站死，可修引擎）
    if any(k in sl for k in ("java.", "jsexception", "json", "keyerror", "nonetype", "module", "execjs", "traceback")):
        return "ENGINE_BUG"
    return "OTHER"


# ---------------------------------------------------------------------------
# 3) 单源 L1 校验
# ---------------------------------------------------------------------------
def validate_one(src, kw, fetcher=None):
    try:
        # debug=False：批量校验不落盘原始响应（否则上千源能堆出上百 MB 垃圾）
        rs = SourceEngine(src, fetcher=fetcher, debug=False).search(kw)
        if rs and any(r.get("bookUrl") for r in rs):
            return "OK", len([r for r in rs if r.get("bookUrl")])
        return "EMPTY", 0
    except Exception as e:
        return classify_error(e), 0


# ---------------------------------------------------------------------------
# 3.5) 主机存活预筛（关键提速：死站一次判死，不再让每个源各耗 3×timeout）
# ---------------------------------------------------------------------------
def host_of(u):
    try:
        return (urlparse(u).netloc or "").lower()
    except Exception:
        return ""


def dedup_sources(srcs):
    """按 bookSourceUrl 去重（订阅包里同站重复源极多）。"""
    seen, out = set(), []
    for s in srcs:
        key = (s.get("bookSourceUrl") or s.get("bookSourceName") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def probe_hosts(hosts, timeout=6, workers=24, verbose=True):
    """对每个唯一 host 只发 1 次轻量 GET（retries=0），判定 ALIVE / 死因。

    死站在这里一次性淘汰，避免它下面的 N 个源各自跑满 retries×timeout。
    """
    f = Fetcher(timeout=timeout)
    res, done = {}, [0]
    total = len(hosts)

    def _p(h):
        try:
            f.request("http://" + h if "://" not in h else h, retries=0)
            return "ALIVE"
        except Exception as e:
            c = classify_error(e)
            # 站活着但拒绝根路径（403/404）不算死，后面照常验规则
            return "ALIVE" if c in ("HTTP_403", "HTTP_404") else c

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_p, h): h for h in hosts}
        for ft in as_completed(futs):
            res[futs[ft]] = ft.result()
            done[0] += 1
            if verbose and done[0] % 50 == 0:
                alive = sum(1 for v in res.values() if v == "ALIVE")
                _log(f"  [probe] {done[0]}/{total} 存活 {alive}")
    return res


# ---------------------------------------------------------------------------
# 4) 主入口
# ---------------------------------------------------------------------------
def import_source(url, kw="斗破苍穹", max_validate=None, write=True, workers=12,
                  probe=True, timeout=8, verbose=True, cache=True):
    report = {"url": url, "kw": kw}

    # 抓取（优雅失败）；cache=True 时命中本地 raw 快照，避免反复拉 9MB 订阅包
    cache_p = RAW_DIR / (hashlib.md5(url.encode()).hexdigest()[:8] + ".json")
    text = None
    if cache and cache_p.exists() and cache_p.stat().st_size > 0:
        text = cache_p.read_text(encoding="utf-8", errors="ignore")
        report["fetch"] = "CACHE"
        _log(f"[1/4] 命中本地快照 {cache_p.name}（{len(text)//1024} KB）", verbose)
    if text is None:
        try:
            text = Fetcher(timeout=timeout).request(url)
            report["fetch"] = "OK"
            cache_p.write_text(text, encoding="utf-8")
            _log(f"[1/4] 抓取成功（{len(text)//1024} KB）", verbose)
        except Exception as e:
            report["fetch"] = "FAIL"
            report["reason"] = classify_error(e)
            report["detail"] = str(e)[:240]
            _log(f"[1/4] 抓取失败：{report['reason']}", verbose)
            return report

    # 格式识别
    obj, fmt = unwrap(text)
    report["format"] = fmt
    if fmt == "html-page":
        # 自行排查：页面里找 .json 直链，直接告诉用户"你可能想要的是这个"
        import re as _re
        cands = []
        for m in _re.findall(r'''["'(\s](https?://[^"'()\s]+?\.json[^"'()\s]*)''', text):
            if m not in cands:
                cands.append(m)
        for m in _re.findall(r'''["'](/[^"'()\s]+?\.json[^"'()\s]*)''', text):
            full = urlparse(url)._replace(path=m.split("?")[0], query="").geturl()
            if full not in cands:
                cands.append(full)
        report["parse"] = "NOT_JSON"
        report["reason"] = "该 URL 返回网页而非书源 JSON（多半给成了仓库页/短链落地页，需要 raw 直链）"
        if cands:
            report["hint_json_links"] = cands[:8]
        report["detail"] = text[:200]
        _log(f"[2/4] 返回的是网页不是 JSON；候选直链 {len(cands)} 条", verbose)
        return report
    if obj is None:
        report["parse"] = "FAIL"
        report["detail"] = text[:240]
        return report
    if isinstance(obj, dict) and _looks_like_login_page(obj):
        report["parse"] = "NEED_LOGIN"
        report["detail"] = text[:240]
        return report

    srcs = normalize(obj)
    if not srcs:
        report["parse"] = "EMPTY"
        report["detail"] = (json.dumps(obj, ensure_ascii=False)[:240] if not isinstance(obj, list) else "no source objects")
        return report
    report["parse"] = "OK"
    report["total"] = len(srcs)
    srcs = dedup_sources(srcs)
    report["unique"] = len(srcs)
    _log(f"[2/4] 解析 fmt={fmt} 共 {report['total']} 源，去重后 {len(srcs)}", verbose)

    cat = Counter()
    # ---- 主机存活预筛 ----
    dead_hosts = {}
    if probe:
        hosts = sorted({host_of(s.get("bookSourceUrl", "")) for s in srcs} - {""})
        _log(f"[3/4] 主机预筛：{len(hosts)} 个唯一域名…", verbose)
        st = probe_hosts(hosts, timeout=min(timeout, 6), workers=max(workers * 2, 24), verbose=verbose)
        dead_hosts = {h: v for h, v in st.items() if v != "ALIVE"}
        alive_srcs = [s for s in srcs if host_of(s.get("bookSourceUrl", "")) not in dead_hosts]
        for s in srcs:
            h = host_of(s.get("bookSourceUrl", ""))
            if h in dead_hosts:
                cat[dead_hosts[h]] += 1
        report["hosts_total"] = len(hosts)
        report["hosts_alive"] = len(hosts) - len(dead_hosts)
        _log(f"[3/4] 存活域名 {report['hosts_alive']}/{len(hosts)}，待验源 {len(alive_srcs)}", verbose)
        srcs = alive_srcs

    # ---- 校验（并发） ----
    n = min(max_validate, len(srcs)) if max_validate else len(srcs)
    report["validated"] = n
    usable = []  # (src, cnt)
    vf = Fetcher(timeout=timeout)
    done = [0]

    def _one(s):
        try:
            return validate_one(s, kw, fetcher=vf)
        except BaseException as e:
            return classify_error(e), 0

    _log(f"[4/4] 逐源校验 {n} 个（关键词「{kw}」）…", verbose)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, s): s for s in srcs[:n]}
        for ft in as_completed(futs):
            st, cnt = ft.result()
            cat[st] += 1
            done[0] += 1
            if st == "OK":
                usable.append((futs[ft], cnt))
            if verbose and done[0] % 25 == 0:
                _log(f"  [validate] {done[0]}/{n} 可用 {len(usable)}", verbose)

    report["cats"] = dict(cat)
    report["usable"] = len(usable)

    # 写入可用源（按 bookSourceName 去重）
    if write and usable:
        existing = json.load(open(VERIFIED, encoding="utf-8")) if VERIFIED.exists() else []
        seen = {x.get("bookSourceName") for x in existing}
        added = 0
        for s, _ in usable:
            name = s.get("bookSourceName")
            if name not in seen:
                existing.append(s)
                seen.add(name)
                added += 1
        json.dump(existing, open(VERIFIED, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        report["written"] = str(VERIFIED)
        report["added"] = added
        report["pool_size"] = len(existing)
    return report


# ---------------------------------------------------------------------------
# 5) CLI / 自测
# ---------------------------------------------------------------------------
def _selftest():
    # 用内置的死 URL 与一份内存源验证「抓取失败分类」与「格式识别」
    print("[import_source selftest]")
    # 格式识别覆盖
    samples = [
        ("plain array", json.dumps([{"bookSourceName": "t", "ruleSearch": {}}])),
        ("single", json.dumps({"bookSourceName": "t", "ruleSearch": {}})),
        ("shuyuan", json.dumps({"code": base64.b64encode(gzip.compress(json.dumps([{"bookSourceName": "t", "ruleSearch": {}}]).encode())).decode()})),
        ("garbage", "not json at all <<<"),
        ("html-page", "<!doctype html><html><body>repo page</body></html>"),
        ("bare b64", base64.b64encode(json.dumps([{"bookSourceName": "t"}]).encode()).decode()),
    ]
    for name, txt in samples:
        obj, fmt = unwrap(txt)
        print(f"  {name:12s} -> fmt={fmt:14s} obj={'list' if isinstance(obj,list) else type(obj).__name__}")
    # 抓取失败分类（用一个必死的域名）
    try:
        Fetcher().request("http://this-domain-does-not-exist-xyz123.local/x.json")
    except Exception as e:
        print(f"  死域分类 -> {classify_error(e)}")
    print("  selftest done.")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--kw", default="斗破苍穹")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--no-probe", action="store_true", help="跳过主机存活预筛")
    ap.add_argument("--no-cache", action="store_true", help="忽略本地 raw 快照，强制重抓")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    if not args.url:
        ap.print_help()
        return
    t0 = time.time()
    rep = import_source(args.url, kw=args.kw, max_validate=args.max,
                        write=not args.no_write, workers=args.workers,
                        probe=not args.no_probe, timeout=args.timeout,
                        verbose=not args.quiet, cache=not args.no_cache)
    rep["elapsed_s"] = round(time.time() - t0, 1)
    print(json.dumps(rep, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
