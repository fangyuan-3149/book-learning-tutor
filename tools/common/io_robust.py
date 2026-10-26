"""容错写文件（与 sanitize.py 同级，供课程化链路共用）。

原本定义在 tools/acquire/source_engine.py 里，随搜书能力一起剥离后，
本地课程化链路（pipeline ingest / figures）仍需它，故在此落地一份。

背景：沙箱或编辑器占用会拦截对**已存在文件**的覆盖写（PermissionError）。
首次写正常成功；重跑被拦截时先尝试旁挂文件（<名>.retry<后缀>）避免丢数据，
仍失败则警告并返回 False，绝不抛异常中断整批处理。
"""
from pathlib import Path


def write_robust(path, text, *, label="文件"):
    """容错写文本文件。返回 True/False，不抛 OSError。"""
    path = Path(path)
    try:
        path.write_text(text, encoding="utf-8")
        return True
    except OSError as e:
        try:
            side = path.with_name(path.stem + ".retry" + path.suffix)
            side.write_text(text, encoding="utf-8")
            print(f"[warn] {label}写入被拦截，已存旁挂：{side.name} -> {e}")
            return True
        except OSError as e2:
            print(f"[warn] {label}写入失败（跳过，不影响其他文件）：{path.name} -> {e2}")
            return False


def write_robust_bytes(path, data, *, label="文件"):
    """容错写二进制文件（插图等）。逻辑同 write_robust。"""
    path = Path(path)
    try:
        path.write_bytes(data)
        return True
    except OSError as e:
        try:
            side = path.with_name(path.stem + ".retry" + path.suffix)
            side.write_bytes(data)
            print(f"[warn] {label}写入被拦截，已存旁挂：{side.name} -> {e}")
            return True
        except OSError as e2:
            print(f"[warn] {label}写入失败（跳过）：{path.name} -> {e2}")
            return False
