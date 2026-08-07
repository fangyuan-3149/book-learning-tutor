"""真实书源离线回归（B-18）：从 1751 真实源池抽样建 fixtures，离线验证引擎摄入真实规则形状。

不联网：只验证「真实源 JSON 能被引擎摄入、四动作规则能被规则解析器接受而不崩溃」，
防止重构把真实世界规则语法搞挂（活体响应需联网，故只做摄入级回归）。

运行：
    python tests/regress_real_sources.py
"""
import sys
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools" / "acquire"))

from source_engine import SourceEngine, load_sources
from rules import parse_object
from bs4 import BeautifulSoup

REAL = HERE / "fixtures" / "sources_real"


def main():
    files = sorted(REAL.glob("*.json"))
    assert files, f"未找到抽样真实源 fixtures（应在 {REAL}）"
    total = ok = 0
    fails = []
    stub = BeautifulSoup("<html><body></body></html>", "html.parser")
    for f in files:
        src = json.loads(f.read_text(encoding="utf-8"))
        name = src.get("bookSourceName", f.name)
        try:
            eng = SourceEngine(src)            # 真实规则形状不应在摄入时崩溃
            for rk in ("ruleSearch", "ruleBookInfo", "ruleToc", "ruleContent"):
                parse_object(src.get(rk, {}), stub, base=eng.base)  # 规则解析器接受真实语法
            eng.js.close()
            ok += 1
        except Exception as e:
            fails.append((name, repr(e)))
        total += 1
    print(f"[B-18] 真实源离线回归：{ok}/{total} 通过（fixtures={len(files)} 条抽样自 1751 真实源池）")
    for n, e in fails:
        print("  FAIL", n, e)
    assert not fails, f"{len(fails)} 个真实源摄入失败"
    print("✅ 真实源（1751 抽样）离线回归通过：引擎摄入真实规则形状无崩溃/解析异常")


if __name__ == "__main__":
    main()
