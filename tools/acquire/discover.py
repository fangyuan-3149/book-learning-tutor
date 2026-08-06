"""自动发现模块（agent 驱动，零外部 LLM key）。

架构（对应 计划书第 8 节「真正的第一步」）：给一个网站网址（书页/搜索结果页），
**写规则这步由 agent（本模型）完成**——agent 读样本页 HTML，直接产出 Legado 书源 JSON；
本模块只提供确定性工具，不调用任何外部 LLM：

- detect_format(text)              判定 HTML / JSON
- looks_like_login_page(html)      登录页"先试后判"过滤（password 输入框+登录 title 才判严格登录）
- validate_source(src, url, text, fmt)  用生成的规则在样本页回放，非空即通过
- save_discovered(src)             落 data/sources/discovered/
- discover_from_source(src, url, text=...)  agent 写好源后的一站式校验+落盘

典型 agent 工作流：
    1. agent 用 fetcher/Fetcher 抓样本页 → 得到 HTML
    2. agent（LLM）读 HTML，写出 Legado 书源 JSON（可直接 Write 到 discovered/，或传变量）
    3. agent 调 validate_source(src, url, html, "html") 回放校验
    4. 不通过就改规则重验（≤3 次由 agent 推理循环负责）；通过则 save_discovered 落盘

CLI（agent 预先写好 source.json）：
    python discover.py <样本URL> --source <agent写好的source.json>
"""
import re
import json
import argparse
from pathlib import Path
from bs4 import BeautifulSoup

from fetcher import Fetcher
from rules import parse_object

ROOT = Path(__file__).resolve().parent.parent.parent
DISCOVERED_DIR = ROOT / "data" / "sources" / "discovered"
DISCOVERED_DIR.mkdir(parents=True, exist_ok=True)


# ---------- 格式判定 / 登录过滤 ----------
def detect_format(text):
    s = text.lstrip()
    if s.startswith("{") or s.startswith("["):
        try:
            json.loads(s)
            return "json"
        except Exception:
            pass
    return "html"


def looks_like_login_page(html):
    """登录页"先试后判"：连搜索都跳登录/403 才丢；有 loginUrl 但能搜的保留。"""
    if not html:
        return False
    low = html.lower()
    has_pwd = "<input" in low and ("type=\"password\"" in low or "password" in low)
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    t = (m.group(1) if m else "").lower()
    if has_pwd and ("登录" in t or "login" in t or "sign in" in t):
        return True
    if "请登录" in html and len(html) < 3000:
        return True
    return False


# ---------- 规则回放校验 ----------
def validate_source(src, sample_url, text, fmt):
    """用生成的规则在样本页回放，任一规则集能抽出非空即视为通过。

    src: agent 写好的 Legado 书源 dict
    text: 样本页原始 HTML/JSON
    fmt:  "html" / "json"
    """
    try:
        if fmt == "json":
            root = json.loads(text)
        else:
            root = BeautifulSoup(text, "html.parser")
    except Exception as e:
        return False, f"样本解析失败: {e}"
    base = src.get("bookSourceUrl", "")
    details = []
    for rk in ("ruleSearch", "ruleBookInfo", "ruleToc", "ruleContent"):
        rule = src.get(rk)
        if not rule:
            continue
        try:
            recs = parse_object(rule, root, base=base)
            if recs and any(any(v for v in (r.values() if isinstance(r, dict) else [r])) for r in recs):
                details.append(f"{rk}: OK({len(recs)} 条)")
            else:
                details.append(f"{rk}: 空")
        except Exception as e:
            details.append(f"{rk}: 异常 {e}")
    passed = any("OK" in d for d in details)
    return passed, "; ".join(details)


# ---------- 落盘 ----------
def save_discovered(src):
    name = re.sub(r"[\\/:*?\"<>|]", "_", src.get("bookSourceName", "discovered"))
    p = DISCOVERED_DIR / f"{name}.json"
    p.write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


# ---------- JSON 提取工具（agent 解析模型输出时用，非 LLM 调用）----------
def _extract_json(text):
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            text = m.group(1)
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------- agent 一站式入口 ----------
def discover_from_source(src, sample_url, text=None, fmt=None):
    """agent 写好书源后调用：抓样本（如需）→ 登录过滤 → 回放校验 → 落盘。

    不从外部 LLM 推导规则；规则由 agent 传入。
    """
    if text is None:
        text = Fetcher().get(sample_url)
    fmt = fmt or detect_format(text)
    if fmt == "html" and looks_like_login_page(text):
        return {"_error": "严格需登录（返回登录页），已过滤", "url": sample_url}
    ok, detail = validate_source(src, sample_url, text, fmt)
    if not ok:
        return {"_error": f"校验未通过: {detail}", "url": sample_url, "format": fmt}
    path = save_discovered(src)
    return {"source": src, "saved": path, "validated": detail, "format": fmt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="样本页 URL（书页/搜索结果页）")
    ap.add_argument("--source", required=True, help="agent 预先写好的书源 JSON 路径")
    args = ap.parse_args()
    src = json.loads(Path(args.source).read_text(encoding="utf-8"))
    res = discover_from_source(src, args.url)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
