"""正文清洗（B-22，对标 W1 cleaner.py，内化零新依赖）。

download_book 抓到每章正文后、落盘前过一遍：去广告/章末噪声行、折叠多余空行、
统一全角空格与段落分隔，产出干净的纯文本，让 书库/ 课程与后续教学环节更干净。

用法：
    from clean import clean_chapter_text
    cleaned = clean_chapter_text(raw_body)

【与 book_formats._clean_book_text 的分工，切勿合并为一套】
- 本模块 clean_chapter_text：面向「网文/小说」逐章正文。敢删"广告/版权归/本章完/
  最新网址"等网文噪声行——这类词在盗版小说站是噪声，删了无损。
- book_formats._clean_book_text：面向「书文件(PDF/EPUB/DOCX/...)」整本抽取。
  *刻意不删* "版权归…/序/前言"等——真实出版书里这是正文/版权页，误删会伤内容。
  它只做排版噪声（全角空格、空行折叠、纯页码行、跨章页眉页脚），不动语义。
两处边界是刻意的：网文噪声词 ≠ 出版书噪声词。后人勿把 _AD_HINTS 搬进书文件清洗。
"""
# 行级噪声关键词（命中整行丢弃）
_AD_HINTS = ("广告", "会员", "开通", "推广", "京ICP", "版权归", "免责声明",
             "联系我们", "请收藏", "手机版", "扫码", "下载app", "下载App",
             "本章完", "未完待续", "请支持", "最新网址", "巴哈姆特", "看小说")
# 章末/章首噪声标记（命中整行丢弃，含标点变体）
_TAIL_MARKERS = ("本章完", "未完待续", "第一卷", "第二卷", "第三卷", "全书完",
                 "（完）", "（未完）", "完结", "待续")


def _is_noise_line(line):
    low = line.lower()
    if any(h.lower() in low for h in _AD_HINTS):
        return True
    s = line.strip(" （）()·•·\t")
    if s in _TAIL_MARKERS:
        return True
    # 仅剩标点/极少字符的空行噪声
    if len(s) <= 1:
        return True
    return False


def clean_chapter_text(text):
    """清洗单章正文纯文本。

    步骤：按行切分 → 去广告/章末噪声行 → 折叠连续空行(>2→1) → 统一全角空格/多余空格 → 去首尾空行。
    """
    if not text:
        return ""
    out = []
    blank = 0
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.replace("\u3000", " ").rstrip()  # 全角空格→半角
        line = line.strip()
        if not line:
            blank += 1
            if blank <= 1:        # 段落间至多留一个空行
                out.append("")
            continue
        blank = 0
        if _is_noise_line(line):
            continue
        # 折叠行内多个空格
        line = " ".join(line.split())
        out.append(line)
    # 去首尾空行
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


# ---------- 自测（B-22 回归，确定性）----------
def selftest():
    raw = (
        "  第一章 退婚  \n\n"
        "斗气大陆，坐落在大陆东域的乌坦城。\n"
        "萧家，作为乌坦城三大家族之一。\n\n\n\n"   # 多余空行应折叠
        "萧炎站在院中，抬头望着天空。\n"
        "　　（本章完）\n"                         # 全角空格+章末标记应去
        "下载App看全文无广告\n"                    # 广告行应去
        "从今往后，那个被称为废物的少年，将不复存在。\n"
    )
    cleaned = clean_chapter_text(raw)
    assert "斗气大陆" in cleaned and "萧炎" in cleaned, "正文本体被误删"
    assert "本章完" not in cleaned, "章末标记未去除"
    assert "下载App" not in cleaned, "广告行未去除"
    assert "\n\n\n" not in cleaned, "多余空行未折叠"
    assert not cleaned.startswith("\n"), "首尾空行未清理"
    assert "　　" not in cleaned, "全角空格未统一"
    print("clean 自测通过：去广告/章末噪声 + 折叠空行 + 统一全角空格（B-22）")
    return True


if __name__ == "__main__":
    selftest()
