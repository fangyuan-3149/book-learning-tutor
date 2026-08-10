/*
 * js_runtime.js —— Legado 书源 `java.*` 的纯 Node 实现（无浏览器、无第三方包）。
 *
 * 该文件同时服务两条路径，是 java.* 语义的单一事实来源：
 *   1) 常驻 worker（js_bridge.NodeWorker，默认路径）：本文件 + 附加的 worker 循环
 *   2) PyExecJS 兜底（Node 常驻失败时）：只加载本文件
 *
 * 约定：所有对外可见的东西都挂在 globalThis 上，
 * 这样 vm.Script(...).runInThisContext() 里的书源代码才能直接引用。
 *
 * 变量作用域分三层：source / book / chapter。
 * java.put 写入当前最内层；java.get 依 chapter → book → source 顺序回溯。
 * 三个作用域对象**身份恒定**（清空用 delete 键，不重新赋值），
 * 以保证 session 别名一直有效。
 */
'use strict';
const crypto = require('crypto');

const __src = {};
const __book = {};
const __chap = {};
let __cur = __chap;                 // 当前写入层

globalThis.session = __book;        // 向后兼容：老代码里直接引用 session
globalThis.result = '';
globalThis.__ajaxMap = {};          // java.ajax 的预取结果（Python 侧填充）

function __clear(o) {
  for (const k in o) {
    if (Object.prototype.hasOwnProperty.call(o, k)) delete o[k];
  }
}

/** level: 'source' 清空全部；'book' 清空 book+chapter；其它清空 chapter */
globalThis.__reset = function (level) {
  if (level === 'source') { __clear(__src); __clear(__book); __clear(__chap); }
  else if (level === 'book') { __clear(__book); __clear(__chap); }
  else { __clear(__chap); }
};

globalThis.__setScope = function (level) {
  __cur = level === 'source' ? __src : (level === 'book' ? __book : __chap);
};

globalThis.__putVars = function (obj, level) {
  const target = level === 'source' ? __src : (level === 'chapter' ? __chap : __book);
  for (const k in obj) {
    if (!Object.prototype.hasOwnProperty.call(obj, k)) continue;
    target[k] = obj[k];
    // 裸名可用：{{java.md5Encode(key)}} 里的 key
    if (/^[A-Za-z_$][\w$]*$/.test(k)) globalThis[k] = obj[k];
  }
};

function b64dec(s) { return Buffer.from(String(s), 'base64'); }
function utf8(b) { return Buffer.from(b).toString('utf-8'); }

function algoName(base, key, mode) {
  base = String(base).toUpperCase();
  mode = (mode || 'CBC').toLowerCase();
  if (base === 'AES') return 'aes-' + (Buffer.byteLength(key, 'utf-8') * 8) + '-' + mode;
  if (base === 'DES') return 'des-' + mode;
  if (base === 'DESEDE' || base === '3DES') return 'des-ede3-' + mode;
  throw new Error('未知算法 ' + base);
}

function hashName(algorithm, dflt) {
  const a = String(algorithm || dflt || 'MD5').toUpperCase().replace('HMAC', '').replace(/-/g, '');
  return (a === 'SHA1' || a === 'SHA256' || a === 'SHA512') ? a.toLowerCase() : 'md5';
}

const java = {
  base64Encode: function (s) { return Buffer.from(String(s), 'utf-8').toString('base64'); },
  base64Decode: function (s) { return utf8(b64dec(s)); },
  base64DecodeToByteArray: function (s) { return utf8(b64dec(s)); },
  hexEncodeToString: function (s) { return Buffer.from(String(s), 'utf-8').toString('hex'); },
  hexDecodeToString: function (s) { return Buffer.from(s, 'hex').toString('utf-8'); },
  hexDecodeToByteArray: function (s) { return Buffer.from(s, 'hex'); },
  md5Encode: function (s) { return crypto.createHash('md5').update(String(s), 'utf-8').digest('hex'); },
  md5Encode16: function (s) { return java.md5Encode(s).substring(8, 24); },
  HMacHex: function (data, algorithm, key) {
    return crypto.createHmac(hashName(algorithm), String(key)).update(String(data), 'utf-8').digest('hex');
  },
  HMacBase64: function (data, algorithm, key) {
    return crypto.createHmac(hashName(algorithm), String(key)).update(String(data), 'utf-8').digest('base64');
  },
  digestHex: function (data, algorithm) {
    return crypto.createHash(hashName(algorithm)).update(String(data), 'utf-8').digest('hex');
  },
  digestBase64Str: function (data, algorithm) {
    return crypto.createHash(hashName(algorithm)).update(String(data), 'utf-8').digest('base64');
  },
  _decrypt: function (data, key, alg, iv) {
    const p = String(alg).toUpperCase().split('/');
    const noPad = /NOPADDING/i.test(alg);
    const d = crypto.createDecipheriv(algoName(p[0], key, p[1]), Buffer.from(key, 'utf-8'),
      iv ? Buffer.from(iv, 'utf-8') : Buffer.alloc(0));
    if (noPad) d.setAutoPadding(false);
    return utf8(Buffer.concat([d.update(b64dec(data)), d.final()]));
  },
  _encrypt: function (data, key, alg, iv) {
    const p = String(alg).toUpperCase().split('/');
    const noPad = /NOPADDING/i.test(alg);
    const e = crypto.createCipheriv(algoName(p[0], key, p[1]), Buffer.from(key, 'utf-8'),
      iv ? Buffer.from(iv, 'utf-8') : Buffer.alloc(0));
    if (noPad) e.setAutoPadding(false);
    return Buffer.concat([e.update(Buffer.from(String(data), 'utf-8')), e.final()]).toString('base64');
  },
  aesBase64DecodeToString: function (d, k, a, i) { return java._decrypt(d, k, a, i); },
  desBase64DecodeToString: function (d, k, a, i) { return java._decrypt(d, k, a, i); },
  tripleDESDecodeStr: function (d, k, a, i) { return java._decrypt(d, k, a || 'DESede/CBC/PKCS5Padding', i); },
  aesEncodeToBase64String: function (d, k, a, i) { return java._encrypt(d, k, a, i); },
  aesEncodeToString: function (d, k, a, i) { return utf8(Buffer.from(java._encrypt(d, k, a, i), 'base64')); },
  desEncodeToBase64String: function (d, k, a, i) { return java._encrypt(d, k, a, i); },
  createSymmetricCrypto: function (transformation, key, iv) {
    return {
      decrypt: function (data) { return java._decrypt(data, key, transformation, iv); },
      encrypt: function (data) { return java._encrypt(data, key, transformation, iv); }
    };
  },

  // ---- 分层会话变量（B-07）----
  put: function (k, v) { __cur[k] = v; return v; },
  get: function (k) {
    if (Object.prototype.hasOwnProperty.call(__chap, k)) return __chap[k];
    if (Object.prototype.hasOwnProperty.call(__book, k)) return __book[k];
    if (Object.prototype.hasOwnProperty.call(__src, k)) return __src[k];
    return '';
  },

  // ---- 网络：由 Python 侧预取，这里只查表（纯 L1，Node 内不发请求）----
  ajax: function (u) {
    const k = String(u);
    return Object.prototype.hasOwnProperty.call(globalThis.__ajaxMap, k) ? globalThis.__ajaxMap[k] : '';
  },

  setContent: function (c) { globalThis.result = c; },
  getString: function (rule) {
    try {
      if (typeof rule === 'string' && (rule.indexOf('$.') === 0 || rule.indexOf('@json:') === 0)) {
        const path = rule.replace('@json:', '').replace(/^\$\./, '');
        let cur = globalThis.result;
        if (typeof cur === 'string') { try { cur = JSON.parse(cur); } catch (e) { return ''; } }
        const keys = path.split('.');
        for (let i = 0; i < keys.length; i++) {
          if (cur == null) return '';
          const m = keys[i].match(/^(\w+)\[(\d+)\]$/);
          if (m) { cur = cur[m[1]]; cur = cur ? cur[parseInt(m[2], 10)] : ''; }
          else cur = cur[keys[i]];
        }
        return cur == null ? '' : String(cur);
      }
    } catch (e) { /* 回退原内容 */ }
    return (typeof globalThis.result === 'string') ? globalThis.result : JSON.stringify(globalThis.result);
  },
  getElements: function (rule) { return [java.getString(rule)]; },
  timeFormat: function (ts) {
    const d = new Date(Number(ts));
    return isNaN(d) ? String(ts) : d.toISOString().slice(0, 19).replace('T', ' ');
  },
  timeFormatUTC: function (ts) { return java.timeFormat(ts); },
  toNumChapter: function (s) {
    const n = parseInt(String(s).replace(/[^\d]/g, ''), 10);
    return isNaN(n) ? '0' : String(n);
  },
  encodeURI: function (s) { return encodeURIComponent(String(s)); },
  toURL: function (u) { return String(u); },
  t2s: function (s) { return s; },
  s2t: function (s) { return s; },
  toString: function (o) { return String(o); },
  log: function () {}, toast: function () {}, longToast: function () {}
};

globalThis.java = java;

// PyExecJS 兜底路径用：把一段代码当表达式求值
globalThis.__run = function (code) { return eval(code); };
