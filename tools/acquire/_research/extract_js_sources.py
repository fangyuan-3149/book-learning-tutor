# [analysis-only] JS-bridge source analysis utilities, not part of the runtime path.
# Run manually for diagnosis: python tools/acquire/_research/<script>.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让同仓 tools/acquire 可达（source_engine/fetcher 等）
"""提取 JS 桥源到候选池，并导出全部源域名供杀软加白名单。

背景（2026-08-06）：
- 用户选择：报毒走"杀软加白名单"，JS 桥源走"站点自身接口"（agent 逐站逆向出
  JS 调用的 XHR/数据接口，改写成纯 L1 源，无浏览器、无外部 key）。
- 此前 ingest_lists 只持久化了 pure 工作源，JS 桥源(3059)被丢弃。本工具把它们
  重新提取落盘到 active/js_candidates.json，作为后续 convert_js_to_api 的材料。
- 同时导出所有"会被用到"的源域名（pure 候选池 + js 候选池）到 data/av_whitelist_domains.txt，
  供用户在杀软里加例外，避免搜索/转换时弹窗。仅读干净的 GitHub/jsdelivr 列表 URL，不打脏站。

用法：
    python extract_js_sources.py
"""
import sys
import json
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_lists import load_all, kind_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
ACTIVE = ROOT / "data" / "sources" / "active"
WHITELIST = ROOT / "data" / "av_whitelist_domains.txt"


def extract_js():
    """重新载入 7 列表，提取 JS 桥源（按 bookSourceUrl 去重）落盘。"""
    data = load_all()
    js, seen = [], set()
    for name, srcs in data.items():
        for s in srcs:
            if kind_of(s) == "js":
                u = s.get("bookSourceUrl")
                if u and u not in seen:
                    seen.add(u)
                    js.append(s)
    out = ACTIVE / "js_candidates.json"
    out.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
    return js


def hosts_of(path):
    try:
        items = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return set()
    hosts = set()
    for s in items:
        u = s.get("bookSourceUrl", "")
        try:
            h = urlparse(u).netloc
            if h:
                hosts.add(h)
        except Exception:
            pass
    return hosts


def main():
    js = extract_js()
    print(f"[js] 提取 JS 桥源 {len(js)} 个 -> {ACTIVE / 'js_candidates.json'}", flush=True)

    hosts = set()
    hosts |= hosts_of(ACTIVE / "js_candidates.json")
    hosts |= hosts_of(ACTIVE / "verified_candidates.json")
    WHITELIST.write_text("\n".join(sorted(hosts)), encoding="utf-8")
    print(f"[whitelist] {len(hosts)} 个域名 -> {WHITELIST}", flush=True)


if __name__ == "__main__":
    main()
