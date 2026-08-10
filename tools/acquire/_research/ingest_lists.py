# [analysis-only] JS-bridge source analysis utilities, not part of the runtime path.
# Run manually for diagnosis: python tools/acquire/_research/<script>.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让同仓 tools/acquire 可达（source_engine/fetcher 等）
"""摄取并分类全部书源列表，把可用（pure）源探测后装入 active/ 池。

设计目标（离线分类 + 并发探测可用源，自动跳过无头环境无法处理的类型）：
- 离线分类：login（有 loginUrl，按规则过滤）/ js（java.* 或 @js 桥，L1 不做浏览器也过滤）
  / pure（无登录、无 JS 桥，引擎可跑）。
- pure 源：并发探测搜索是否真返回书，把"工作"的去重后写入 active/verified_all.json。
- 复用 SourceEngine.search，共享一个 Fetcher（httpx 线程安全）以提速。

用法：
    python ingest_lists.py                 # 仅离线分类，打印每列表与合计计数
    python ingest_lists.py --probe         # 分类 + 并发探测 pure 源并落盘 verified_all.json
    python ingest_lists.py --probe --limit 200   # 只探测前 200 个 pure 源（先小批量验证）
    python ingest_lists.py --probe --workers 32 --keyword 天降
"""
import sys
import json
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_engine import load_sources, SourceEngine
from fetcher import Fetcher

ROOT = Path(__file__).resolve().parent.parent.parent
ACTIVE = ROOT / "data" / "sources" / "active"

# 已知书源订阅列表（部分可能已失效，存活预筛会自然淘汰）
LISTS = {
    "iu2": "https://legado.aoaostar.com/sources/71e56d4f.json",
    "full2159": "https://gcore.jsdelivr.net/gh/yuedu520/yuedu/250422.json",
    "curated997": "https://gcore.jsdelivr.net/gh/yuedu520/yuedu/250415.json",
    "breaking": "https://legado.aoaostar.com/sources/4dc410d1.json",
    "yicheng": "https://www.gitlink.org.cn/api/yi-c/yd/raw?filepath=sy.json",
    "male69": "https://gcore.jsdelivr.net/gh/yuedu520/yuedu/250412.json",
    "fd_male": "https://legado.aoaostar.com/sources/b778fe6b.json",
}
KW = "天降"


def kind_of(src):
    """login / js / pure 三分类。"""
    if src.get("loginUrl"):
        return "login"
    s = json.dumps(src, ensure_ascii=False)
    if ("java." in s) or ("@onclick@js" in s) or ("@js:" in s) or ("<js>" in s) or ("@js>" in s):
        return "js"
    return "pure"


def load_all():
    data = {}
    for name, url in LISTS.items():
        try:
            data[name] = load_sources(url)
            print(f"[load] {name}: {len(data[name])} 源", flush=True)
        except Exception as e:
            print(f"[warn] {name} 载入失败: {e}", flush=True)
            data[name] = []
    return data


def classify_report(data):
    tot = pure = login = js = 0
    for name, srcs in data.items():
        c = {"pure": 0, "login": 0, "js": 0}
        for s in srcs:
            c[kind_of(s)] += 1
        tot += len(srcs)
        pure += c["pure"]
        login += c["login"]
        js += c["js"]
        print(f"  {name:12} {len(srcs):5} 源 | pure={c['pure']:4} login={c['login']:4} js={c['js']:4}", flush=True)
    print(f"  合计 {tot} 源 | pure={pure} login={login} js={js}", flush=True)
    return tot, pure, login, js


def probe(data, workers=24, keyword=KW, limit=None):
    shared = Fetcher(timeout=8)  # 共享客户端（httpx 线程安全）
    working = []
    seen = set()
    pure_all = []
    for name, srcs in data.items():
        for s in srcs:
            if kind_of(s) == "pure":
                pure_all.append((name, s))
    if limit:
        pure_all = pure_all[:limit]
    print(f"[probe] pure 源总数={len(pure_all)}，并发={workers}，关键词={keyword}", flush=True)

    def one(item):
        name, s = item
        try:
            eng = SourceEngine(s, shared)
            eng._save_debug = lambda *a, **k: None  # 探测阶段不落盘 debug
            recs = eng.search(keyword)
            n = len(recs)
        except Exception as e:
            return (name, s, 0, str(e)[:60])
        return (name, s, n, None)

    done = 0
    worked = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, pure_all, chunksize=8):
            done += 1
            name, s, n, err = r
            if n > 0:
                worked += 1
                url = s.get("bookSourceUrl")
                if url and url not in seen:
                    seen.add(url)
                    working.append(s)
            if done % 100 == 0:
                print(f"  [probe] 进度 {done}/{len(pure_all)} 工作={worked}", flush=True)
    print(f"[probe] 完成：工作源 {len(working)} 个（按 bookSourceUrl 去重后）", flush=True)
    return working


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="探测 pure 源并写入 active/verified_all.json")
    ap.add_argument("--limit", type=int, default=None, help="只探测前 N 个 pure 源（小批量验证用）")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--keyword", default=KW)
    args = ap.parse_args()

    data = load_all()
    print("== 分类汇总 ==", flush=True)
    classify_report(data)

    if args.probe:
        working = probe(data, workers=args.workers, keyword=args.keyword, limit=args.limit)
        out = ACTIVE / "verified_all.json"
        out.write_text(json.dumps(working, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[write] {len(working)} 个工作源 -> {out}", flush=True)
        # bimidu.json 已被 verified_all 覆盖，删除避免重复搜索
        old = ACTIVE / "bimidu.json"
        if old.exists():
            old.unlink()
            print(f"[clean] 删除旧的 {old.name}", flush=True)


if __name__ == "__main__":
    main()
