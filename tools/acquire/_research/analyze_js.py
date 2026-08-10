#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [analysis-only] JS-bridge source analysis utilities, not part of the runtime path.
# Run manually for diagnosis: python tools/acquire/_research/<script>.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让同仓 tools/acquire 可达（source_engine/fetcher 等）
"""
analyze_js.py — 量化 js_candidates.json 里 JS 桥源实际用到的 java.* 方法与加密配置。
输出：各方法调用次数、加密 (alg,key,mode,iv) 去重清单、含 JS 的规则字段分布。
只读分析，不产生任何落盘改动。
"""
import json, re, sys
from collections import Counter, defaultdict

SRC = "data/sources/active/js_candidates.json"
JAVA_CALL = re.compile(r'java\.([A-Za-z0-9_]+)\s*\(')
JS_MARKER = re.compile(r'@js:|@onclick@js|\{\{.*?\}\}')
# crypto call arg capture: java.aesBase64DecodeToString(Data,"KEY","AES/CBC/PKCS5Padding","IV")
CRYPTO = re.compile(
    r'java\.(aesBase64DecodeToString|desBase64DecodeToString|aesEncodeToString|desEncodeToString|'
    r'aesDecodeToString|desDecodeToString)\s*\(\s*[^,]*,\s*"([^"]*)"\s*(?:,\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?)?'
)

def walk(obj, cb):
    """递归遍历所有字符串叶子，把 (path, value) 交给 cb。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            walk(v, cb)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, cb)
    elif isinstance(obj, str):
        cb(obj)

def main():
    with open(SRC, encoding="utf-8") as f:
        sources = json.load(f)
    print(f"总源数: {len(sources)}", flush=True)

    method_counter = Counter()
    crypto_cfgs = defaultdict(list)   # cfg_key -> [example source names]
    field_counter = Counter()         # 哪些规则字段含 JS
    js_source_count = 0
    crypto_source_count = 0
    ajax_source_count = 0

    def on_str(s):
        nonlocal js_source_count, crypto_source_count, ajax_source_count
        for m in JAVA_CALL.finditer(s):
            method_counter[m.group(1)] += 1
        for cm in CRYPTO.finditer(s):
            alg = cm.group(1)
            key = cm.group(2)
            mode = cm.group(3) or ""
            iv = cm.group(4) or ""
            cfg_key = f"{alg}|{key}|{mode}|{iv}"
            crypto_cfgs[cfg_key].append(alg)
            crypto_source_count += 1
        if 'java.ajax' in s or 'ajax(' in s:
            ajax_source_count += 1
        if JS_MARKER.search(s):
            js_source_count += 1

    # 记录含 JS 的字段
    for src in sources:
        name = src.get("bookSourceName", "?")
        def field_cb(s, _name=name):
            pass
        # 字段级统计：遍历 (field_name, value)
        def count_field(field, val):
            if isinstance(val, str) and JS_MARKER.search(val):
                field_counter[field] += 1
        for topk, topv in src.items():
            if isinstance(topv, str):
                count_field(topk, topv)
            elif isinstance(topv, dict):
                for subk, subv in topv.items():
                    if isinstance(subv, str):
                        count_field(f"{topk}.{subk}", subv)
        walk(src, on_str)

    print("\n=== java.* 方法调用总次数 (去重到调用点) ===")
    for meth, c in method_counter.most_common():
        print(f"  java.{meth:28s} {c}")

    print("\n含 JS 标记(@js:/{{}}) 的源: " + str(js_source_count))
    print(f"含 java.ajax 调用的源: {ajax_source_count}")
    print(f"含 crypto 调用的源(调用点计): {crypto_source_count}")

    print("\n=== 加密配置去重 (alg|key|mode|iv) — 每种覆盖的调用点数 ===")
    # crypto_cfgs[cfg_key] = list of alg; len = 调用点数
    for cfg_key, algs in sorted(crypto_cfgs.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{len(algs):3d}] {cfg_key}")

    print("\n=== 含 JS 的规则字段分布 (Top 30) ===")
    for field, c in field_counter.most_common(30):
        print(f"  {field:32s} {c}")

if __name__ == "__main__":
    main()
