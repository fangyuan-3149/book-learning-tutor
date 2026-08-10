"""合规聚合引擎（授业 · 源池构建器）

把「已知 shuyuan 订阅 + 本地 Legado 源仓库 + 用户提供的合法 URL」汇成可用源池，
写入 data/sources/imported/verified.json（pipeline 实际加载的池）。

设计纪律（对齐项目铁律）：
- 使用者自行提供书源 / 网页源，责任由使用者承担；本工具不提供任何网站源码、爬虫或代理。
- 零外部 key；纯 L1（不显式开浏览器）。
- 复用 import_source 的 解包→存活预筛→逐源 L1 校验→死因分类→并池 核心。

入口来源（合规）：
1) 已知订阅注册表：复用 ingest_lists.LISTS（一组已知书源订阅；部分可能已失效，
   保留以便周期重试——死站会自然在存活预筛被淘汰）。
2) 本地 Legado 源仓库：扫描 开源阅读/ 下含 bookSourceUrl 的 JSON（社区源集合）。
3) 用户 --url：你亲自提供的合法订阅/聚合 URL（可多次）。

用法：
    python aggregate.py                      # 默认：订阅 + 本地仓库 全扫
    python aggregate.py --url <合法订阅URL>  # 追加你给的源
    python aggregate.py --no-local           # 只扫已知订阅
    python aggregate.py --max 100 --timeout 6 # 快跑（每源最多验100、超时6s）
    python aggregate.py --no-subs --no-local --url <URL>   # 只验你给的
"""
import sys
import json
import time
import argparse
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_source import (import_source, run_validation, VERIFIED, IMPORTED_DIR)
from source_engine import load_sources
from notice import report_source_unavailable
try:
    from ingest_lists import LISTS   # 已知订阅注册表（7 个书源列表，可选）
except ImportError:
    LISTS = {}                       # 缺订阅注册表时仅跳过订阅分支，不影响本地/URL 分支

LOCAL_REPO_ROOT = ROOT / "开源阅读"


def local_source_files(limit=200):
    """扫描本地 Legado 仓库里含 bookSourceUrl 的源 JSON（社区合法源集合）。"""
    out = []
    if not LOCAL_REPO_ROOT.exists():
        return out
    for p in LOCAL_REPO_ROOT.rglob("*.json"):
        if len(out) >= limit:
            break
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if '"bookSourceUrl"' in t or '"bookSourceName"' in t:
            out.append(p)
    return out


def validate_local(p, kw, workers, timeout, probe, verbose):
    """本地源 JSON → 复用统一校验核心并入池。"""
    try:
        srcs = load_sources(p)
    except Exception as e:
        return {"entry": f"local:{p.name}", "parse": "FAIL", "reason": str(e)[:160]}
    srcs = [s for s in srcs if isinstance(s, dict)]
    if not srcs:
        return {"entry": f"local:{p.name}", "parse": "EMPTY"}
    rep = run_validation(srcs, kw=kw, write=True, workers=workers,
                         probe=probe, timeout=timeout, verbose=verbose)
    rep["entry"] = f"local:{p.name}"
    return rep


def summarize(entries):
    tot_cand = sum(e.get("total", 0) for e in entries if "total" in e)
    tot_unique = sum(e.get("unique", 0) for e in entries if "unique" in e)
    tot_validated = sum(e.get("validated", 0) for e in entries if "validated" in e)
    tot_alive = sum(e.get("hosts_alive", 0) for e in entries if "hosts_alive" in e)
    cats = Counter()
    for e in entries:
        cats.update(e.get("cats", {}) or {})
    pool = json.load(open(VERIFIED, encoding="utf-8")) if VERIFIED.exists() else []
    print("\n================ 聚合汇总 ================")
    print(f"入口数(订阅/本地/URL) : {len(entries)}")
    print(f"候选源(累计)          : {tot_cand}")
    print(f"去重后源(累计)        : {tot_unique}")
    print(f"实际校验(累计)        : {tot_validated}")
    print(f"存活域名(累计)        : {tot_alive}")
    print(f"当前 verified 池      : {len(pool)} 条")
    print("结果/死因直方图:")
    for k, v in cats.most_common():
        print(f"  {k:12}: {v}")
    SUMMARY = IMPORTED_DIR / "aggregate_report.json"
    json.dump({"entries": entries, "cats": dict(cats), "pool_size": len(pool),
               "total_candidates": tot_cand},
              open(SUMMARY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"报告 -> {SUMMARY}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", default=[],
                    help="用户提供的合法书源订阅/聚合 URL（可多次）")
    ap.add_argument("--no-subs", action="store_true", help="跳过已知订阅注册表")
    ap.add_argument("--no-local", action="store_true", help="跳过本地 Legado 仓库扫描")
    ap.add_argument("--local-limit", type=int, default=200, help="本地仓库最多扫描文件数")
    ap.add_argument("--kw", default="斗破苍穹")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--max", type=int, default=None, help="每源最多校验数（快跑用）")
    ap.add_argument("--no-probe", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    verbose = not args.quiet
    entries = []

    # 1) 已知订阅注册表
    if not args.no_subs:
        for name, url in LISTS.items():
            try:
                rep = import_source(url, kw=args.kw, max_validate=args.max, write=True,
                                    workers=args.workers, timeout=args.timeout,
                                    probe=not args.no_probe, verbose=verbose, cache=True)
            except Exception as e:
                rep = {"entry": f"sub:{name}", "fetch": "FAIL", "reason": str(e)[:160]}
            rep.setdefault("entry", f"sub:{name}")
            entries.append(rep)
            if verbose:
                print(f"[agg] 订阅 {name}: usable={rep.get('usable')} added={rep.get('added')}")

    # 2) 本地 Legado 源仓库
    if not args.no_local:
        for p in local_source_files(args.local_limit):
            rep = validate_local(p, args.kw, args.workers, args.timeout,
                                 not args.no_probe, verbose)
            entries.append(rep)
            if verbose:
                print(f"[agg] 本地 {p.name}: parse={rep.get('parse')} usable={rep.get('usable')}")

    # 3) 用户提供的合法 URL
    for u in args.url:
        try:
            rep = import_source(u, kw=args.kw, max_validate=args.max, write=True,
                                workers=args.workers, timeout=args.timeout,
                                probe=not args.no_probe, verbose=verbose, cache=True)
        except Exception as e:
            rep = {"entry": f"url:{u}", "fetch": "FAIL", "reason": str(e)[:160]}
        rep.setdefault("entry", f"url:{u}")
        entries.append(rep)
        if verbose:
            print(f"[agg] URL {u}: usable={rep.get('usable')} added={rep.get('added')}")

    summarize(entries)
    # 池为空 → 在线获取全线失败，统一提示使用者自供源
    try:
        pool = json.load(open(VERIFIED, encoding="utf-8")) if VERIFIED.exists() else []
    except Exception:
        pool = []
    if not pool:
        report_source_unavailable("书源池为空：所有订阅 / 本地 / URL 入口均不可用或零存活",
                                  ctx="aggregate")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"[agg] 总耗时 {round(time.time() - t0, 1)}s")
