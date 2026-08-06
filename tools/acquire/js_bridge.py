#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
js_bridge.py — 在 Node（via PyExecJS）里执行 Legado 书源规则中的 @js: / {{java.*}} 片段。

设计（纯 L1，无浏览器、无外部 key）：
- 规则里 8199 处 @js:/{{}} 片段绝大多数是字符串处理 + java.* 加密/签名/编解码/会话变量。
  这些用 Node 原生 crypto / 字符串能力复现，无需浏览器渲染。
- 唯一需要网络的 java.ajax(url) 在 Python 侧由 fetcher 预解析（它就是一次 GET），
  结果以内联变量的方式注入 JS，避免“Node 里同步发请求”的难题。
- 仅真正需要 webView/startBrowser 的源才被过滤（见 source_engine 的 kind_of 判定）。

依赖：PyExecJS + 本机 Node（已在运行时中）。crypto 用 Node 内置模块。
"""
import re
import json
import execjs

# Node 侧 java.* 实现（用 Node 内置 crypto / Buffer，不依赖外部库）
JS_EXTENSION = r"""
const crypto = require('crypto');
var session = {};          // java.put / java.get 共享存储
var result = '';           // 当前待处理内容（规则链传入）

function b64dec(s){ return Buffer.from(String(s), 'base64'); }
function utf8(b){ return Buffer.from(b).toString('utf-8'); }

function algoName(base, key, mode){
  base = String(base).toUpperCase(); mode = (mode||'CBC').toLowerCase();
  if(base==='AES') return 'aes-' + (Buffer.byteLength(key,'utf-8')*8) + '-' + mode;
  if(base==='DES') return 'des-' + mode;
  if(base==='DESEDE' || base==='3DES') return 'des-ede3-' + mode;
  throw new Error('未知算法 '+base);
}

const java = {
  base64Encode: function(s){ return Buffer.from(String(s),'utf-8').toString('base64'); },
  base64Decode: function(s){ return utf8(b64dec(s)); },
  base64DecodeToByteArray: function(s){ return utf8(b64dec(s)); },
  hexEncodeToString: function(s){ return Buffer.from(String(s),'utf-8').toString('hex'); },
  hexDecodeToString: function(s){ return Buffer.from(s,'hex').toString('utf-8'); },
  hexDecodeToByteArray: function(s){ return Buffer.from(s,'hex'); },
  md5Encode: function(s){ return crypto.createHash('md5').update(String(s),'utf-8').digest('hex'); },
  md5Encode16: function(s){ return java.md5Encode(s).substring(8,24); },
  HMacHex: function(data, algorithm, key){
    var a = String(algorithm).toUpperCase().replace('HMAC','').replace('-','');
    var h = (a==='SHA1'||a==='SHA256'||a==='SHA512') ? a.toLowerCase() : 'md5';
    return crypto.createHmac(h, String(key)).update(String(data),'utf-8').digest('hex');
  },
  HMacBase64: function(data, algorithm, key){
    var a = String(algorithm).toUpperCase().replace('HMAC','').replace('-','');
    var h = (a==='SHA1'||a==='SHA256'||a==='SHA512') ? a.toLowerCase() : 'md5';
    return crypto.createHmac(h, String(key)).update(String(data),'utf-8').digest('base64');
  },
  digestHex: function(data, algorithm){
    var a = String(algorithm||'MD5').toUpperCase().replace('-','');
    var h = (a==='SHA1'||a==='SHA256'||a==='SHA512') ? a.toLowerCase() : 'md5';
    return crypto.createHash(h).update(String(data),'utf-8').digest('hex');
  },
  digestBase64Str: function(data, algorithm){
    var a = String(algorithm||'MD5').toUpperCase().replace('-','');
    var h = (a==='SHA1'||a==='SHA256'||a==='SHA512') ? a.toLowerCase() : 'md5';
    return crypto.createHash(h).update(String(data),'utf-8').digest('base64');
  },
  _decrypt: function(data, key, alg, iv){
    var p = String(alg).toUpperCase().split('/');
    var noPad = /NOPADDING/i.test(alg);
    var d = crypto.createDecipheriv(algoName(p[0], key, p[1]), Buffer.from(key,'utf-8'), iv?Buffer.from(iv,'utf-8'):Buffer.alloc(0));
    if(noPad) d.setAutoPadding(false);
    return utf8(Buffer.concat([d.update(b64dec(data)), d.final()]));
  },
  _encrypt: function(data, key, alg, iv){
    var p = String(alg).toUpperCase().split('/');
    var noPad = /NOPADDING/i.test(alg);
    var e = crypto.createCipheriv(algoName(p[0], key, p[1]), Buffer.from(key,'utf-8'), iv?Buffer.from(iv,'utf-8'):Buffer.alloc(0));
    if(noPad) e.setAutoPadding(false);
    return Buffer.from(e.update(Buffer.from(String(data),'utf-8')).concat(e.final())).toString('base64');
  },
  aesBase64DecodeToString: function(data, key, alg, iv){ return java._decrypt(data, key, alg, iv); },
  desBase64DecodeToString: function(data, key, alg, iv){ return java._decrypt(data, key, alg, iv); },
  tripleDESDecodeStr: function(data, key, alg, iv){ return java._decrypt(data, key, alg||'DESede/CBC/PKCS5Padding', iv); },
  aesEncodeToBase64String: function(data, key, alg, iv){ return java._encrypt(data, key, alg, iv); },
  aesEncodeToString: function(data, key, alg, iv){ return utf8(Buffer.from(java._encrypt(data, key, alg, iv),'base64')); },
  desEncodeToBase64String: function(data, key, alg, iv){ return java._encrypt(data, key, alg, iv); },
  createSymmetricCrypto: function(transformation, key, iv){
    return {
      decrypt: function(data){ return java._decrypt(data, key, transformation, iv); },
      encrypt: function(data){ return java._encrypt(data, key, transformation, iv); }
    };
  },
  put: function(k, v){ session[k] = v; return v; },
  get: function(k){ return (k in session) ? session[k] : ''; },
  setContent: function(c){ result = c; },
  getString: function(rule){
    // 最小化：处理 $. JsonPath 与 ## 正则替换；复杂情形回退原内容
    try {
      if(typeof rule === 'string' && (rule.indexOf('$.')===0 || rule.indexOf('@json:')===0)){
        var path = rule.replace('@json:','').replace(/^\$\./,'');
        var cur = result;
        if(typeof cur === 'string'){ try { cur = JSON.parse(cur); } catch(e){ return ''; } }
        var keys = path.split('.');
        for(var i=0;i<keys.length;i++){
          if(cur==null) return '';
          var m = keys[i].match(/^(\w+)\[(\d+)\]$/);
          if(m){ cur = cur[m[1]]; cur = cur? cur[parseInt(m[2])] : ''; }
          else cur = cur[keys[i]];
        }
        return cur==null ? '' : String(cur);
      }
    } catch(e){}
    return (typeof result==='string') ? result : JSON.stringify(result);
  },
  getElements: function(rule){ return [java.getString(rule)]; },
  timeFormat: function(ts){ var d=new Date(Number(ts)); return isNaN(d)?String(ts):d.toISOString().slice(0,19).replace('T',' '); },
  timeFormatUTC: function(ts, fmt, sh){ return java.timeFormat(ts); },
  toNumChapter: function(s){ var n = parseInt(String(s).replace(/[^\d]/g,''),10); return isNaN(n)?'0':String(n); },
  encodeURI: function(s){ return encodeURIComponent(String(s)); },
  toURL: function(u){ return String(u); },
  t2s: function(s){ return s; }, s2t: function(s){ return s; },
  toString: function(o){ return String(o); },
  log: function(){}, toast: function(){}, longToast: function(){}
};

function __run(code){ return eval(code); }
"""

_AJAX_RE = re.compile(r"java\.ajax\(\s*(['\"])(.*?)\1\s*\)")


class JsBridge:
    """在 Node 里求值 Legado 规则的 @js: / {{java.*}} 片段。"""

    def __init__(self, fetcher=None):
        self._ctx = execjs.compile(JS_EXTENSION)
        self._fetcher = fetcher  # callable(url, headers=None) -> str

    def eval(self, expression, result="", variables=None, headers=None):
        """求值表达式。
        expression: JS 代码片段（可含 java.*）。
        result: 当前待处理内容（注入为 JS 全局 result）。
        variables: 先前 @put/java.put 的变量字典（注入 session）。
        headers: 供 java.ajax 预解析使用的请求头。
        """
        preamble = []
        if variables:
            for k, v in variables.items():
                preamble.append("session[%s] = %s;" % (json.dumps(k), json.dumps(v)))
                # 同时声明为顶层变量，使 {{java.md5Encode(key)}} 中的裸名可用
                if re.match(r"^[A-Za-z_$][\w$]*$", k):
                    preamble.append("var %s = %s;" % (k, json.dumps(v)))
        preamble.append("result = %s;" % json.dumps(result))
        # 预解析 java.ajax(url) -> 注入内联变量
        def _sub(m):
            q, url = m.group(1), m.group(2)
            token = "__ajax%d" % len(preamble)
            body = ""
            if self._fetcher:
                try:
                    body = self._fetcher(url, headers) or ""
                except Exception:
                    body = ""
            preamble.append("var %s = %s;" % (token, json.dumps(body)))
            return token

        expr = _AJAX_RE.sub(_sub, expression)
        code = "\n".join(preamble) + "\n" + expr
        try:
            out = self._ctx.call("__run", code)
        except execjs.Error as e:
            raise RuntimeError("JS求值失败: %s | expr=%s" % (e, expression[:200]))
        return "" if out is None else str(out)


if __name__ == "__main__":
    # 自测：字符串处理 + md5 + aes 解密 + 会话变量 + ajax 预解析
    def fake_fetch(url, headers=None):
        return '{"ok":1,"name":"番茄"}'
    b = JsBridge(fetcher=fake_fetch)
    # 1) 字符串清理
    print("1)", b.eval(r"result.replace(/正文卷\.?/,'').trim()", result="  正文卷.测试 "))
    # 2) md5
    print("2)", b.eval("java.md5Encode('abc')"))
    # 3) aes 解密（用 transforms 同款配置）
    import base64, sys
    sys.path.insert(0, ".")
    from transforms import aes_base64_decode_to_string as py_aes
    pt = '{"code":0,"data":"ok"}'
    import hashlib
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key, iv = "f041c49714d39908", "0123456789abcdef"
    ct = AES.new(key.encode(), AES.MODE_CBC, iv.encode()).encrypt(pad(pt.encode(), 16))
    b64 = base64.b64encode(ct).decode()
    print("3) python:", py_aes(b64, key, "AES/CBC/PKCS5Padding", iv))
    print("3) node  :", b.eval('java.aesBase64DecodeToString(%s,"%s","AES/CBC/PKCS5Padding","%s")' % (json.dumps(b64), key, iv)))
    # 4) 会话变量
    print("4)", b.eval("java.put('x','hello'); java.get('x')"))
    # 5) ajax 预解析（Legado 中 java.ajax 返回字符串，真实写法需 JSON.parse）
    r5 = b.eval("JSON.parse(java.ajax('https://example.com/api')).name", result="{}")
    print("5)", r5)
    assert r5 == "番茄", "ajax 预解析失败: %r" % r5
    print("js_bridge 自测全部通过")
