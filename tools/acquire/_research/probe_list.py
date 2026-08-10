# [analysis-only] JS-bridge source analysis utilities, not part of the runtime path.
# Run manually for diagnosis: python tools/acquire/_research/<script>.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让同仓 tools/acquire 可达（source_engine/fetcher 等）
"""书源列表探查 / 试搜工具。

用法：
    python probe_list.py <书源列表URL>                 # 拉取+分类+汇总
    python probe_list.py <书源列表URL> --search 天降     # 在纯解析源上搜关键词
    python probe_list.py <书源列表URL> --search 天降 --max 15

说明：
- 分类：login(有 loginUrl/loginUi) / js(规则含 java. @js <js> @onclick@js webView) / pure(纯解析)
- 只在实际搜索时对 pure 源跑 searchBook；login/js 源在无头环境跑不动，跳过。
"""
import sys
import json
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from source_engine import SourceEngine, load_sources


def classify(src):
    blob = json.dumps(src, ensure_ascii=False)
    if src.get("loginUrl") or src.get("loginUi") or "loginUrl" in blob:
        return "login"
    for tok in ("java.", "@js:", "<js>", "@onclick@js", "webView", "x5://", "http://ie."):
        if tok in blob:
            # 仅当出现在规则值里才算 js 桥；header 里的 java 误判概率低，忽略
            if any(tok in str(v) for v in _rule_values(src)):
                return "js"
    return "pure"


def _rule_values(src):
    out = []
    for k in ("ruleSearch", "ruleBookInfo", "ruleToc", "ruleContent", "ruleFindUrl", "ruleReview"):
        v = src.get(k)
        if isinstance(v, dict):
            out.extend(str(x) for x in v.values())
        elif v:
            out.append(str(v))
    return out


def inspect(url):
    sources = load_sources(url)
    buckets = {"login": [], "js": [], "pure": []}
    for s in sources:
        buckets[classify(s)].append(s)
    print(f"[列表] {url}")
    print(f"  共 {len(sources)} 个源：pure(纯解析)={len(buckets['pure'])}  login(登录)={len(buckets['login'])}  js(JS桥)={len(buckets['js'])}")
    print("  —— 纯解析源（可搜）：")
    for s in buckets["pure"][:40]:
        print(f"    · {s.get('bookSourceName','?')}  <{s.get('bookSourceUrl','')}>")
    return buckets


def search(url, kw, max_n=15):
    sources = load_sources(url)
    pure = [s for s in sources if classify(s) == "pure"]
    print(f"[搜 '{kw}'] 纯解析源 {len(pure)} 个，本次试前 {min(max_n, len(pure))} 个")
    targets = pure[:max_n]
    results = []

    def _one(src):
        try:
            return SourceEngine(src).search(kw)
        except Exception as e:
            return [{"_error": str(e)[:80], "_source": src.get("bookSourceName", "?")}]

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_one, s): s for s in targets}
        for f in as_completed(futs):
            res = f.result()
            results.extend(res)
    ok = [r for r in results if r.get("bookUrl") and not r.get("_error")]
    print(f"  有效结果 {len(ok)} / 总 {len(results)}")
    for r in ok[:30]:
        print(f"    ✔ {r.get('name','?')} — {r.get('author','?')}  [{r.get('_source')}]")
        print(f"      {r.get('bookUrl','')[:90]}")
    for r in results:
        if r.get("_error"):
            print(f"    ✗ {r.get('_source')}: {r['_error']}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--search", default=None)
    ap.add_argument("--max", type=int, default=15)
    args = ap.parse_args()
    if args.search:
        search(args.url, args.search, args.max)
    else:
        inspect(args.url)


if __name__ == "__main__":
    main()
