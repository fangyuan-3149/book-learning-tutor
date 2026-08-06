"""引擎侧变换原语：把 Legado 书源规则里的 java.* / @js 加密·签名·编解码
调用，用纯 Python 复现，使 JS 桥源可在无浏览器、无外部 key 下转成纯 L1。

设计（2026-08-06，用户定调"JS桥源走站点自身接口，纯 L1 无 key"）：
- 规则里常见 `java.aesBase64DecodeToString(Data,"key","AES/CBC/PKCS5Padding","iv")`
  之类调用；本模块提供同名函数，agent 把规则里的 java 调用原样改写成对 transforms
  的调用即可，无需浏览器渲染 JS。
- 仅实现真实书源中出现过的算法族（AES/DES 的 ECB/CBC + PKCS5/7，base64，md5/sha）。
  未出现的算法按需补，不臆造。

依赖：pycryptodome（已装入 venv）。
"""
import base64
import hashlib
import hmac

from Crypto.Cipher import AES, DES, DES3
from Crypto.Util.Padding import unpad as _c_unpad


def _b(s):
    return s.encode("utf-8") if isinstance(s, str) else s


def _s(b):
    return b.decode("utf-8", errors="replace") if isinstance(b, (bytes, bytearray)) else b


def base64_decode(s):
    return base64.b64decode(s)


def base64_encode(b):
    return base64.b64encode(_b(b) if isinstance(b, str) else b).decode("ascii")


def md5_hex(s):
    return hashlib.md5(_b(s)).hexdigest()


def md5(s):
    return md5_hex(s)


def sha1_hex(s):
    return hashlib.sha1(_b(s)).hexdigest()


_ALGO = {"AES": AES, "DES": DES, "DESEDE": DES3, "DESede": DES3, "3DES": DES3}


def _cipher(alg, key, iv):
    """alg 形如 AES/CBC/PKCS5Padding 或 DES/ECB/NoPadding。
    返回 (cipher_class, mode_obj, block_size)。"""
    parts = alg.upper().split("/")
    algo = parts[0]
    mode = parts[1] if len(parts) > 1 else "ECB"
    pad = parts[2] if len(parts) > 2 else "PKCS5PADDING"
    if algo not in _ALGO:
        raise ValueError(f"不支持的算法: {algo}")
    cls = _ALGO[algo]
    key_b = _b(key)
    if mode == "ECB":
        mode_obj = cls.MODE_ECB
    elif mode == "CBC":
        mode_obj = cls.MODE_CBC
    elif mode in ("CTR", "CFB"):
        mode_obj = getattr(cls, "MODE_" + mode)
    else:
        raise ValueError(f"不支持的模式: {mode}")
    block = cls.block_size  # 字节
    return cls, key_b, mode_obj, block, pad.upper()


def _decrypt(cls, key_b, mode_obj, iv_b, ct, pad_name, block):
    if mode_obj == cls.MODE_ECB:
        cipher = cls.new(key_b, mode_obj)
    else:
        cipher = cls.new(key_b, mode_obj, iv_b)
    pt = cipher.decrypt(ct)
    if "PKCS" in pad_name:
        pt = _c_unpad(pt, block)
    # NoPadding / 其他：保留原始明文（调用方按需截取）
    return pt


def aes_base64_decode_to_string(data_b64, key, alg, iv=""):
    """对应 java.aesBase64DecodeToString(Data, key, alg, iv)。"""
    cls, key_b, mode_obj, block, pad = _cipher(alg, key, iv)
    ct = base64.b64decode(data_b64)
    pt = _decrypt(cls, key_b, mode_obj, _b(iv), ct, pad, block)
    return _s(pt)


def des_base64_decode_to_string(data_b64, key, alg, iv=""):
    return aes_base64_decode_to_string(data_b64, key, alg, iv)  # DES / 3DES 走同一路径


# ---------- 哈希 / 签名（覆盖 2223 源里出现的 md5Encode / HMacHex / digestHex） ----------

def md5_encode16(s):
    """java.md5Encode16：取 32 位 md5 十六进制的中间 16 位（[8:24]）。"""
    return md5_hex(s)[8:24]


def hmac_hex(s, key, alg="MD5"):
    """java.HMacHex(data, algorithm, key)。algorithm 形如 MD5/SHA256/HmacSHA256。"""
    import hmac
    algo = alg.upper().replace("HMAC", "").replace("-", "")
    algo = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}.get(algo, "md5")
    return hmac.new(_b(key), _b(s), getattr(hashlib, algo)).hexdigest()


def hmac_base64(s, key, alg="MD5"):
    import hmac
    algo = alg.upper().replace("HMAC", "").replace("-", "")
    algo = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}.get(algo, "md5")
    return base64.b64encode(hmac.new(_b(key), _b(s), getattr(hashlib, algo)).digest()).decode("ascii")


def digest_hex(s, alg="MD5"):
    """java.digestHex(data, algorithm)。algorithm 形如 MD5/SHA-1/SHA-256。"""
    algo = alg.upper().replace("-", "")
    algo = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}.get(algo, "md5")
    return hashlib.new(algo, _b(s)).hexdigest()


def digest_base64(s, alg="MD5"):
    algo = alg.upper().replace("-", "")
    algo = {"SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}.get(algo, "md5")
    return base64.b64encode(hashlib.new(algo, _b(s)).digest()).decode("ascii")


def hex_encode(s):
    """java.hexEncodeToString(utf8) -> 十六进制串。"""
    return _b(s).hex()


def hex_decode(s):
    """java.hexDecodeToString(hex) -> utf8 串。"""
    return bytes.fromhex(s).decode("utf-8", errors="replace")


def base64_decode_to_bytes(s):
    """java.base64DecodeToByteArray(s) -> 字节（转 str 回传，规则端多作中间量）。"""
    return base64.b64decode(s).decode("utf-8", errors="replace")


def aes_encode_to_base64(data, key, alg, iv=""):
    """java.aesEncodeToBase64String：明文 -> AES -> base64。"""
    cls, key_b, mode_obj, block, pad = _cipher(alg, key, iv)
    pt = _b(data)
    if "PKCS" in pad:
        from Crypto.Util.Padding import pad as _pad
        pt = _pad(pt, block)
    if mode_obj == cls.MODE_ECB:
        ct = cls.new(key_b, mode_obj).encrypt(pt)
    else:
        ct = cls.new(key_b, mode_obj, _b(iv)).encrypt(pt)
    return base64.b64encode(ct).decode("ascii")


def des_encode_to_base64(data, key, alg, iv=""):
    return aes_encode_to_base64(data, key, alg, iv)


def decode_marker_des(str_val, key="6CB1E21E", iv="1F0FB845", marker="JP2/W5V"):
    """kpkpo/qwezxc4 等家族的响应解密：若含标记则去头3尾4字符后 DES 解密，否则原样返回。
    对应规则里 bookSourceComment 定义的 decode() 函数。"""
    s = str_val
    if marker in s:
        data = s[3:len(s) - 4]
        s = aes_base64_decode_to_string(data, key, "DES/CBC/PKCS5Padding", iv)
    return s


# 命名变换分发表：rule{X}Decrypt 可写 "decode_marker_des" 直接引用
TRANSFORMS = {
    "decode_marker_des": decode_marker_des,
}


def parse_java_call(call):
    """解析 `java.method(a, b, c)` 字符串 → (method, [args])，供 agent 改写规则用。"""
    call = call.strip()
    if not call.startswith("java."):
        raise ValueError("非 java.* 调用")
    body = call[len("java."):]
    name, rest = body.split("(", 1)
    args_str = rest.rstrip(")")
    args, buf, q, depth = [], "", None, 0
    for ch in args_str:
        if q:
            buf += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            buf += ch
        elif ch == "," and depth == 0:
            args.append(_unquote(buf))
            buf = ""
        else:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            buf += ch
    if buf.strip():
        args.append(_unquote(buf))
    return name, args


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def apply_java(call, **ctx):
    """执行一个 java.* 调用；ctx 提供变量（如 Data=...）。返回结果字符串。"""
    name, args = parse_java_call(call)
    if name in ("aesBase64DecodeToString", "desBase64DecodeToString"):
        data = ctx.get("Data", args[0])
        return aes_base64_decode_to_string(data, *args[1:])
    if name in ("aesEncodeToBase64String", "desEncodeToBase64String"):
        data = ctx.get("Data", args[0])
        return aes_encode_to_base64(data, *args[1:])
    if name == "base64Decode":
        return _s(base64.b64decode(args[0]))
    if name == "base64Encode":
        return base64_encode(args[0])
    if name == "base64DecodeToByteArray":
        return base64_decode_to_bytes(args[0])
    if name in ("md5", "md5Hex"):
        return md5_hex(args[0])
    if name == "md5Encode16":
        return md5_encode16(args[0])
    if name == "HMacHex":
        return hmac_hex(args[0], args[2], args[1] if len(args) > 1 else "MD5")
    if name == "HMacBase64":
        return hmac_base64(args[0], args[2], args[1] if len(args) > 1 else "MD5")
    if name == "digestHex":
        return digest_hex(args[0], args[1] if len(args) > 1 else "MD5")
    if name == "digestBase64Str":
        return digest_base64(args[0], args[1] if len(args) > 1 else "MD5")
    if name in ("hexEncodeToString", "hexEncodeToByteArray"):
        return hex_encode(args[0])
    if name == "hexDecodeToString":
        return hex_decode(args[0])
    raise ValueError(f"未实现的 java.* 方法: {name}")


if __name__ == "__main__":
    # 冒烟自测：覆盖 2223 源里出现的真实加密配置（见 analyze_js.py 输出）
    from Crypto.Util.Padding import pad
    key, iv = "6CB1E21E", "1F0FB845"
    pt = "许南歌立刻拿出手机"
    enc = DES.new(_b(key), DES.MODE_CBC, _b(iv))
    ct = enc.encrypt(pad(pt.encode("utf-8"), DES.block_size))
    b64 = base64.b64encode(ct).decode()
    out = des_base64_decode_to_string(b64, key, "DES/CBC/PKCS5Padding", iv)
    assert out == pt, f"DES 失败 {out}"
    print("DES/CBC 往返 OK")

    # AES/CBC/PKCS5 真实配置 #1
    cfg1 = ("f041c49714d39908", "AES/CBC/PKCS5Padding", "0123456789abcdef")
    akey, aalg, aiv = cfg1
    aenc = AES.new(_b(akey), AES.MODE_CBC, _b(aiv))
    act = aenc.encrypt(pad(b"{\"code\":0,\"data\":\"ok\"}", AES.block_size))
    ab64 = base64.b64encode(act).decode()
    aout = aes_base64_decode_to_string(ab64, *cfg1)
    assert aout == '{"code":0,"data":"ok"}', f"AES#1 失败 {aout}"
    print("AES/CBC#1 往返 OK")

    # 3DES 真实配置 #5 (DESede/CBC/PKCS5Padding)
    cfg5 = ("OW84U8Eerdb99rtsTXWSILDO", "DESede/CBC/PKCS5Padding", "SK8bncVu")
    tkey, talg, tiv = cfg5
    tenc = DES3.new(_b(tkey), DES3.MODE_CBC, _b(tiv))
    tct = tenc.encrypt(pad(b"secret-content-3des!!", DES3.block_size))
    tb64 = base64.b64encode(tct).decode()
    tout = aes_base64_decode_to_string(tb64, *cfg5)
    assert tout == "secret-content-3des!!", f"3DES 失败 {tout}"
    print("DESede/CBC 往返 OK")

    # 签名 / 哈希
    assert md5_hex("abc") == "900150983cd24fb0d6963f7d28e17f72"
    assert md5_encode16("abc") == md5_hex("abc")[8:24]
    assert hmac_hex("data", "key", "MD5") == hmac.new(b"key", b"data", hashlib.md5).hexdigest()
    assert hex_encode("AB") == "4142"
    assert hex_decode("4142") == "AB"
    print("md5/HMac/hex OK")

    # 解析样例规则
    call = 'java.aesBase64DecodeToString(Data,"6CB1E21E","DES/CBC/PKCS5Padding","1F0FB845")'
    nm, ag = parse_java_call(call)
    assert nm == "aesBase64DecodeToString" and ag[0] == "Data"
    print("解析样例:", nm, ag)
    print("transforms 自测全部通过")
