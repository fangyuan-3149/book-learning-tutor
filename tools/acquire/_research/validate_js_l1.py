#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [analysis-only] JS-bridge source analysis utilities, not part of the runtime path.
# Run manually for diagnosis: python tools/acquire/_research/<script>.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让同仓 tools/acquire 可达（source_engine/fetcher 等）
"""离线验证：JS 桥源转纯 L1 的端到端链路（无需浏览器、无需真实域名）。
用一个 mock fetcher 返回 AES 加密的 JSON，验证：
  (1) searchUrl 的 {{java.md5Encode(key)}} 签名展开
  (2) ruleSearchDecrypt 用 transforms.py 解密
  (3) ruleSearch 的 @js: 字段规则经 Node 桥求值
  (4) 会话变量 java.put/java.get 跨字段传递
"""
import base64, json
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from fetcher import Fetcher
from source_engine import SourceEngine

# ---- 构造一条真实风格的 JS 桥源 ----
KEY, IV = "f041c49714d39908", "0123456789abcdef"

def _enc(pt):
    ct = AES.new(KEY.encode(), AES.MODE_CBC, IV.encode()).encrypt(pad(pt.encode(), 16))
    return base64.b64encode(ct).decode()

# mock 响应（AES 加密后的搜索结果 JSON）
raw_search = json.dumps({
    "data": [
        {"book_id": "123", "title": "斗破苍穹", "author_name": "天蚕土豆",
         "cover_url": "http://x/c.jpg", "category_name": "玄幻", "status": "30"},
    ]
}, ensure_ascii=False)
enc_search = _enc(raw_search)

SRC = {
    "bookSourceName": "L1验证源",
    "bookSourceUrl": "https://api.test.com",
    "searchUrl": "https://api.test.com/s?q={{key}}&sign={{java.md5Encode(key)}}",
    "ruleSearch": {
        "bookList": "$.data",
        "name": "$.title",
        "author": "$.author_name",
        "bookUrl": "/novels/api/book/{{$.book_id}}",
        "coverUrl": "$.cover_url",
        # @js: 字段规则（前缀形式，经 Node 桥求值 + 会话变量）
        "kind": "@js:java.put('st','L1'); java.get('st')",
    },
    "ruleSearchDecrypt": 'java.aesBase64DecodeToString(Data,"%s","AES/CBC/PKCS5Padding","%s")' % (KEY, IV),
}


class MockFetcher(Fetcher):
    def get(self, url, headers=None):
        # 命中搜索 URL 时返回加密内容；否则返回空
        if "api.test.com/s" in url:
            print("  [mock] GET", url)
            return enc_search
        return ""
    def post(self, url, headers=None, data=None):
        return self.get(url, headers)


def main():
    eng = SourceEngine(SRC, fetcher=MockFetcher())
    print("== 搜索 '斗破' ==")
    recs = eng.search("斗破")
    import pprint
    pprint.pprint(recs)
    assert recs, "搜索无结果"
    r = recs[0]
    assert r["name"] == "斗破苍穹", r["name"]
    assert r["author"] == "天蚕土豆"
    assert r["kind"] == "L1", "kind 应为 L1, 实际=%r" % r.get("kind")
    assert r["bookUrl"].startswith("https://api.test.com/novels/api/book/123"), r["bookUrl"]
    print("\n✅ 纯 L1 端到端验证通过：searchUrl 签名展开 + AES 解密 + @js:字段 + 会话变量 + URL模板插值 全部生效")


if __name__ == "__main__":
    main()
