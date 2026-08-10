"""统一「在线获取失败」提示（授业 · 数据源不可用时告知使用者 / agent）。

设计背景：
- 技能主路径是本地文件 → all-local 课程化，本就不联网、不爬取、不提供任何书源。
- 仓库里保留的爬虫/书源脚本（search/download/import_source/aggregate/discover）
  是「使用者自行使用、自担责」的工具。当它们因**网页不可达 / 代码出错**而无
  法取得内容时，统一调本模块把原因反馈出来，并引导使用者：
    ① 自行寻找正版 / 合法来源下载原书；或
    ② 直接把本地书文件交给 agent，用 `all-local <路径>` 处理。

输出走 stderr，避免污染 stdout 上的 JSON 结构化结果（import_source / discover 用）。
"""

import sys


def report_source_unavailable(reason, *, ctx="", file=None):
    """打印统一失败提示（不抛异常，交由调用方决定退出与否）。

    reason: 具体失败原因（如 "DNS 解析失败" / "HTTP 403" / "所有书源均不可达"）。
    ctx:    触发场景标识（如 "search 斗破苍穹" / "import_source"）。
    """
    out = file or sys.stderr
    bar = "=" * 56
    lines = [
        "",
        bar,
        "⚠️  在线获取失败，本书无法从在线源取得。",
    ]
    if ctx:
        lines.append(f"    场景：{ctx}")
    lines.append(f"    原因：{reason}")
    lines += [
        "-" * 56,
        "    请使用者自行处理（责任由使用者承担）：",
        "    1) 寻找正版 / 合法来源，下载原书到本地；或",
        "    2) 直接把本地书文件交给 agent，使用：",
        "         python tools/acquire/pipeline.py all-local <本地书路径>",
        "",
        "    本工具不提供任何网站源码、书源、爬虫或代理；",
        "    仅供学习辅助。完整条款见仓库根 免责声明.md。",
        bar,
        "",
    ]
    print("\n".join(lines), file=out, flush=True)
