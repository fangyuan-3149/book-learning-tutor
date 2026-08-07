"""无规则兜底正文抽取（B-20，对标 trafilatura/readability 算法思想，内化零新依赖）。

为什么自研而不引 trafilatura：trafilatura 拉 5~6 个依赖、readability-lxml 仅 lxml；
而小说正文页结构极简单（一个内容容器 + 若干 <p>），用「文本/链接密度 + 标签黑名单 +
段落聚合」即可覆盖绝大多数阅读网址，~150 行纯 bs4(html.parser) 实现。

用途：当某站没有可用书源规则（discover 写规则失败）时，作为兜底把正文抠出来，
保证「大部分阅读网址」仍能拿到正文，而不是整站放弃。

用法：
    from extract import extract_main_text
    text = extract_main_text(html)
"""
from bs4 import BeautifulSoup

# 噪声标签：直接剥离，不参与密度计算
_NOISE_TAGS = ("script", "style", "noscript", "svg", "header", "footer",
               "nav", "aside", "head", "meta", "link", "form", "iframe")

# 行级广告/导航噪声关键词（命中则丢弃该行）
_AD_HINTS = ("广告", "会员", "下载app", "下载App", "开通", "推广", "京ICP",
             "版权归", "免责声明", "联系我们", "请收藏", "手机版", "扫码")


def _link_text_len(el):
    return sum(len(a.get_text(strip=True)) for a in el.find_all("a"))


def _extract_paragraphs(el):
    """从候选容器里取出正文段落列表（按 <p> 优先，否则按块文本切分）。"""
    ps = el.find_all("p")
    out = []
    for p in ps:
        t = p.get_text(" ", strip=True)
        if t:
            out.append(t)
    if len(out) >= 2:
        return out
    # 回退：直接取容器文本，按换行聚合
    txt = el.get_text("\n", strip=True)
    return [ln.strip() for ln in txt.split("\n") if ln.strip()]


def _is_ad_line(line):
    low = line.lower()
    return any(h.lower() in low for h in _AD_HINTS)


def extract_main_text(html, min_line_len=15):
    """从 HTML 抽取正文纯文本（段落用空行分隔）。

    算法：
      1) 剥离噪声标签；
      2) 优先用 <p> 段落密度：文本够长、链接占比低、非广告行 → 直接聚合；
      3) 否则找「纯文本密度最高」的容器块（文本长且链接不占主导），再取其中段落；
      4) 最后兜底取 body 全文。
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in _NOISE_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    # ---- 路径 2：<p> 段落密度直接命中 ----
    paras = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if not t or len(t) < min_line_len:
            continue
        link_len = _link_text_len(p)
        if link_len and link_len / len(t) > 0.5:
            continue  # 链接主导，跳过
        if _is_ad_line(t):
            continue
        paras.append(t)
    if len(paras) >= 2 and sum(len(p) for p in paras) >= 80:
        return "\n\n".join(paras)

    # ---- 路径 3：密度最高的容器块 ----
    best, best_score = None, 0
    for el in soup.find_all(["div", "article", "section", "td", "li", "main"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        link_len = _link_text_len(el)
        pure = len(txt) - link_len
        # 链接占比过高视为导航/广告块，惩罚
        if link_len and link_len / len(txt) > 0.6:
            pure = pure // 4
        if pure > best_score:
            best_score, best = pure, el
    if best and best_score >= 80:
        cand = _extract_paragraphs(best)
        cand = [c for c in cand if len(c) >= min_line_len and not _is_ad_line(c)]
        if cand:
            return "\n\n".join(cand)

    # ---- 路径 4：兜底 body ----
    body = soup.body or soup
    txt = body.get_text("\n", strip=True)
    lines = [ln.strip() for ln in txt.split("\n") if ln.strip() and len(ln.strip()) >= min_line_len]
    lines = [ln for ln in lines if not _is_ad_line(ln)]
    return "\n\n".join(lines)


# ---------- 自测（B-20 回归，确定性、不联网）----------
def selftest():
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent.parent
    html = (ROOT / "tests" / "fixtures" / "chapter_noisy.html").read_text(encoding="utf-8")
    text = extract_main_text(html)
    assert text.strip(), "抽取结果为空"
    assert "斗气大陆" in text and "萧炎" in text, "未抽到正文章节内容"
    assert "下载App" not in text, "广告行未过滤"
    assert "示例小说网" not in text, "header/nav 噪声未去除"
    assert "京ICP" not in text, "footer 噪声未去除"
    assert "武动乾坤" not in text, "aside 推荐噪声未去除"
    assert text.count("\n\n") >= 2, "正文未按段落聚合"
    print("extract 自测通过：噪声标签剥离 + 段落密度抽正文 + 广告行过滤（B-20）")
    return True


if __name__ == "__main__":
    selftest()
