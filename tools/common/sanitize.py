"""文件系统安全的名称清洗 —— 全仓唯一实现，禁止在别处另写。

书库/<书名>/、参考/<书名>/、figures/inline 都按清洗后的书名寻址，三者必须一致，
否则配图 / inline 会按 书库/<书名> 找不到本目录。

只替换文件系统非法字符、保留空格；空名退回 'untitled'。
"""
import re

_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def safe_name(name: str) -> str:
    """清洗为安全的目录 / 文件名：去掉文件系统非法字符，空则退回 'untitled'。"""
    return _ILLEGAL.sub("_", str(name)).strip() or "untitled"
