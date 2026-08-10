"""书源引擎：内化开源阅读(Legado)的「搜索 / 详情 / 目录 / 正文」四大动作。

设计（对应 计划书 Phase 0）：
- 单源引擎：给定一本书源 dict，即可 searchBook / getBookInfo / getChapterList / getContent。
- 原始 HTTP 响应落盘到 data/debug/<源>/ 便于排错；下载到的「原书」落盘到 参考/<书名>/。
- 纯解析型书源（CSS/XPath/JSONPath/Regex）可端到端跑通；依赖 java.* 浏览器桥的书源在对应
  环节明确报错跳过，不假成功。

用法：
    from source_engine import SourceEngine, load_sources
    sources = load_sources("data/sources/src1.json")
    eng = SourceEngine(sources[15])          # 铅笔小说（纯解析源）
    books = eng.search("斗破苍穹")
    info  = eng.get_book_info(books[0]["bookUrl"])
    toc   = eng.get_toc(info.get("tocUrl") or books[0]["bookUrl"])
    txt   = eng.get_content(toc[0]["chapterUrl"])
"""
import re
import json
import time
import urllib.parse
from pathlib import Path

from fetcher import Fetcher
from rules import parse_object, set_js_bridge
from transforms import apply_java, TRANSFORMS  # JS桥源转纯L1：内容解密钩子（无浏览器、无外部key）
from js_bridge import JsBridge  # 纯 L1：在 Node 里求 @js:/{{java.*}} 片段（无浏览器、无外部key）
from url_option import UrlOption, BrowserRequired  # B-01：URL+option 统一解析，四大动作共用
from clean import clean_chapter_text  # B-22：正文清洗（落盘前过一遍）

ROOT = Path(__file__).resolve().parent.parent.parent  # 仓库根（由本文件位置推导，不硬编码绝对路径）
DEBUG_DIR = ROOT / "data" / "debug"
REF_DIR = ROOT / "参考"


def _safe(name):
    return re.sub(r"[\\/:*?\"<>|]", "_", str(name)).strip() or "untitled"


def _is_json_text(text):
    s = text.lstrip()
    return s.startswith("{") or s.startswith("[")


def _parse_response(text):
    if _is_json_text(text):
        try:
            return "json", json.loads(text)
        except Exception:
            pass
    from bs4 import BeautifulSoup
    return "html", BeautifulSoup(text, "html.parser")


def load_sources(path_or_url):
    """从本地文件或 URL 载入书源，统一返回 list[dict]。支持数组/单对象。"""
    text = None
    if str(path_or_url).startswith(("http://", "https://")):
        f = Fetcher()
        text = f.get(str(path_or_url))
    else:
        text = Path(path_or_url).read_text(encoding="utf-8")
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def write_robust(path, text, *, label="文件"):
    """容错写文本文件（主文件/旁路文件通用）。

    沙箱或编辑器占用会拦截对**已存在文件**的覆盖写（PermissionError）。
    首次写（文件不存在）正常成功；重跑（迭代调规则）被拦截时：
      先尝试写入同目录旁挂文件（<名>.retry<后缀>）避免丢数据，
      仍失败则警告并返回 False，绝不抛出中断整本/整步下载。
    """
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
    """二进制版 write_robust（漫画页 / 音频）。逻辑同 write_robust。"""
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


class SourceEngine:
    def __init__(self, source, fetcher=None, debug=True):
        # debug=False：不落盘 HTTP 原始响应。批量校验（import_source 扫上千源）时必须关，
        # 否则每次搜索都写一份 HTML，很快堆出上百 MB 垃圾。单源排错时保持 True。
        self.debug = debug
        self.src = source
        self.base = (source.get("bookSourceUrl") or "").split("#")[0].rstrip("/")
        self.f = fetcher or Fetcher()
        self.name = source.get("bookSourceName", "unknown")
        self.headers = self.f.parse_header(source.get("header")) if hasattr(self.f, "parse_header") else {}
        # 纯 L1 JS 桥：searchUrl 里的 {{java.*}} 与 @js: 字段规则在此求值（无浏览器）
        self.js = JsBridge(fetcher=self.f)
        self.js.reset("source")   # B-07：引擎创建即清空三层作用域，从源级开始
        self.js.variables = {}    # 兼容旧接口（注入到 book 层的会话变量）
        self.js.headers = self.headers
        set_js_bridge(self.js)
        # 调试落盘（HTTP 原始响应）
        self.debug_dir = DEBUG_DIR / _safe(self.name)
        if self.debug:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
        # 下载到的「原书」落盘目录（Step 2 产物，供人类对照）
        self.book_dir = None  # 在 download_book 时按书名确定

    # ---- 落盘 ----
    def _save_debug(self, kind, url, text):
        if not self.debug:
            return ""
        fn = f"{kind}_{int(time.time()*1000)}.{'json' if _is_json_text(text) else 'html'}"
        p = self.debug_dir / fn
        p.write_text(text, encoding="utf-8")
        return str(p)

    # ---- URL 构造 ----
    _URL_BRACE_RE = re.compile(r"\{\{(.*?)\}\}")

    def _expand_url(self, tmpl, keyword="", page=1):
        """展开 searchUrl 里的 {{key}}/{{page}}/{{java.*}}。
        - {{key}}/{{page}} 直接替换（原逻辑）
        - 其它 {{...}} 当作 JS 片段求值（含 java.ajax/java.md5Encode 等），由 Node 桥执行
        """
        def _repl(m):
            inner = m.group(1).strip()
            if inner == "key":
                return urllib.parse.quote(str(keyword))
            if inner == "page":
                return str(page)
            try:
                return self.js.eval(inner, variables={"key": keyword, "page": str(page)}, headers=self.headers)
            except Exception:
                return ""
        return self._URL_BRACE_RE.sub(_repl, tmpl)

    def _build_action_url(self, tmpl, **vars):
        url = tmpl
        for k, v in vars.items():
            url = url.replace("{{" + k + "}}", urllib.parse.quote(str(v)))
        if not url.startswith("http"):
            url = self.base + url
        return url

    # ---- 统一请求入口（B-01）：四大动作共用，站点差异只留在书源 JSON ----
    def _request(self, raw_url, keyword="", page=1):
        """解析 `<url>,{option}` → 展开 {{...}} → 执行 JS 钩子 → 发请求。

        返回 (最终URL, 响应文本)。webView 类源在此明确抛 BrowserRequired，不假成功。
        """
        opt = UrlOption.parse(raw_url)
        opt = opt.expanded(lambda s: self._expand_url(s, keyword, page))
        if opt.js or opt.body_js:
            opt = opt.apply_js(self.js)
        return opt.fetch(self.f, self.base, default_headers=self.headers)

    # ---- 解密钩子（JS桥源转纯L1）----
    def _apply_decrypt(self, text, stage):
        """若源带 rule{Stage}Decrypt，对抓取文本解密后再解析。
        stage ∈ {Search,BookInfo,Toc,Content}。支持两种写法：
        - java.* 调用（如 java.aesBase64DecodeToString(Data,"K","ALG","IV")）→ apply_java
        - 命名变换（如 "decode_marker_des"）→ TRANSFORMS 分发表
        Data=抓取到的密文。"""
        spec = self.src.get(f"rule{stage}Decrypt")
        if not spec:
            return text
        try:
            if spec.startswith("java."):
                return apply_java(spec, Data=text)
            if spec in TRANSFORMS:
                return TRANSFORMS[spec](text)
        except Exception as e:
            self._save_debug(f"{stage}_decrypt_err", "", str(e))
        return text

    # ---- 四大动作 ----
    def search(self, keyword, page=1):
        tmpl = self.src.get("searchUrl", "")
        if not tmpl:
            return []
        self.js.reset("book")    # B-07：换书清 book+chapter 层，保留 source 层
        self.js.variables = {}   # 兼容旧接口（会话变量随书重置）
        url, text = self._search_fetch(tmpl, keyword, page)
        self._save_debug("search", url, text)
        text = self._apply_decrypt(text, "Search")
        _, root = _parse_response(text)
        recs = parse_object(self.src.get("ruleSearch", {}), root, base=self.base)
        for r in recs:
            r["_source"] = self.name
            r["_base"] = self.base
        return recs

    def _search_fetch(self, tmpl, keyword, page):
        """构造并执行搜索请求，全部委托给统一的 UrlOption（B-01）。

        自动覆盖：普通 GET、`url,{"method":"POST","body":...,"charset":...}`、
        `{{java.ajax(...)}}` 整体内联（不再二次请求）、相对路径拼站点根。
        """
        return self._request(tmpl, keyword, page)

    def get_book_info(self, book_url):
        url, text = self._request(book_url)
        self._save_debug("bookinfo", url, text)
        text = self._apply_decrypt(text, "BookInfo")
        _, root = _parse_response(text)
        recs = parse_object(self.src.get("ruleBookInfo", {}), root, base=self.base)
        info = recs[0] if recs else {}
        # 相对 tocUrl 按"当前书籍页 URL"解析（书源 bookSourceUrl 常带 #标签碎片）
        if info.get("tocUrl") and not info["tocUrl"].startswith("http"):
            info["tocUrl"] = urllib.parse.urljoin(book_url, info["tocUrl"])
        return info

    def get_toc(self, book_url):
        url, text = self._request(book_url)
        self._save_debug("toc", url, text)
        text = self._apply_decrypt(text, "Toc")
        _, root = _parse_response(text)
        recs = parse_object(self.src.get("ruleToc", {}), root, base=self.base)
        # 相对章节 URL 按"当前目录页 URL"解析，而非站点根
        for r in recs:
            cu = r.get("chapterUrl", "")
            if cu and not cu.startswith("http"):
                r["chapterUrl"] = urllib.parse.urljoin(url, cu)
        return recs

    def get_content(self, chapter_url):
        self.js.reset("chapter")  # B-07：每章清 chapter 层，逐章不串变量
        url, text = self._request(chapter_url)
        self._save_debug("content", url, text)
        text = self._apply_decrypt(text, "Content")
        _, root = _parse_response(text)
        recs = parse_object(self.src.get("ruleContent", {}), root, base=self.base)
        content = recs[0].get("content", "") if recs else ""
        if not content or not content.strip():
            # B-20 兜底：规则抠不出正文时（站改版/规则过期/写错），用通用 HTML
            # 正文抽取救场，避免返回空正文假成功。仅作最后兜底，不影响正常路径。
            try:
                from extract import extract_main_text
                fb = extract_main_text(text)
                if fb and fb.strip():
                    content = fb
            except Exception:
                pass
        return content

    def get_content_images(self, chapter_url):
        """漫画模式：返回本章所有图片页的绝对 URL 列表（纯 L1，img src 经 CSS/XPath 取）。"""
        self.js.reset("chapter")
        url, text = self._request(chapter_url)
        self._save_debug("content", url, text)
        text = self._apply_decrypt(text, "Content")
        _, root = _parse_response(text)
        recs = parse_object(self.src.get("ruleContent", {}), root, base=self.base)
        if not recs:
            return []
        val = recs[0].get("content", "")
        if isinstance(val, list):
            urls = [u for u in val if isinstance(u, str)]
        elif isinstance(val, str):
            # 常见分隔：换行 / 逗号 / | / @
            urls = [u.strip() for u in re.split(r"[\n,|@]", val) if u.strip()]
        else:
            urls = []
        out = []
        for u in urls:
            if u and not u.startswith("http"):
                u = urllib.parse.urljoin(url, u)
            out.append(u)
        return out

    # ---- Step 2：下载整本原书到 参考/<书名>/ ----
    def _load_progress(self):
        """断点续爬（B-21）：读已下载章节序号集合。"""
        p = self.book_dir / "_progress.json"
        if p.exists():
            try:
                return set(json.loads(p.read_text(encoding="utf-8")).get("downloaded", []))
            except Exception:
                return set()
        return set()

    @staticmethod
    def _write_aux(path, text):
        """写辅助文件（元数据/进度）。失败只警告不抛。路由到 write_robust。"""
        return write_robust(path, text, label="辅助文件")

    def _save_progress(self, done):
        self._write_aux(self.book_dir / "_progress.json",
                        json.dumps({"downloaded": sorted(done), "updated": time.time()},
                                   ensure_ascii=False, indent=2))

    def download_book(self, book_url, book_name=None, max_chapters=None, resume=True):
        self.js.reset("book")    # B-07：进入一本新书，重置 book+chapter 层
        self.js.variables = {}   # 兼容旧接口（会话变量随书重置）
        info = self.get_book_info(book_url)
        name = book_name or info.get("name") or "untitled"
        self.book_dir = REF_DIR / _safe(name)
        self.book_dir.mkdir(parents=True, exist_ok=True)
        toc_url = info.get("tocUrl") or book_url
        toc = self.get_toc(toc_url)
        is_comic = str(self.src.get("bookSourceType")) == "1"   # 1=漫画：每章=图序列
        # 保存元数据
        meta = {"name": name, "author": info.get("author", ""), "intro": info.get("intro", ""),
                "source": self.name, "bookUrl": book_url, "tocUrl": toc_url,
                "bookType": "comic" if is_comic else "novel",
                "chapterCount": len(toc)}
        self._write_aux(self.book_dir / "_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        # 逐章下载（B-21 断点续爬 + B-22 正文清洗）
        done = self._load_progress() if resume else set()
        count = 0
        try:
            for i, ch in enumerate(toc, 1):
                if max_chapters and count >= max_chapters:
                    break
                curl = ch.get("chapterUrl", "")
                if not curl:
                    continue
                ch_name = _safe(ch.get("chapterName", f"第{i}章"))
                # 断点续爬：进度记录 或 已落盘（小说 .txt / 漫画 pages/）
                if resume:
                    ch_done = (i in done) or list(self.book_dir.glob(f"{i:04d}_*.txt"))
                    if is_comic:
                        pages = self.book_dir / f"{i:04d}_{ch_name}" / "pages"
                        ch_done = ch_done or (pages.exists() and any(pages.iterdir()))
                    if ch_done:
                        count += 1
                        continue
                if is_comic:
                    # 漫画模式：每章 = 一个文件夹，内含 pages/(原图) + transcript.md
                    img_urls = self.get_content_images(curl)
                    ch_dir = self.book_dir / f"{i:04d}_{ch_name}"
                    pages = ch_dir / "pages"
                    pages.mkdir(parents=True, exist_ok=True)
                    n_img = 0
                    for j, iu in enumerate(img_urls, 1):
                        try:
                            data = self.f.get_bytes(iu)
                        except Exception as e:
                            print(f"[warn] 漫画页下载失败 {iu}: {e}")
                            continue
                        ext = Path(iu.split("?")[0]).suffix or ".jpg"
                        write_robust_bytes(pages / f"{j:03d}{ext}", data, label="漫画页")
                        n_img += 1
                    if n_img:
                        # 对白/旁白见原图（用户确认漫画已含文字，不另 OCR）
                        write_robust(ch_dir / "transcript.md",
                                     f"# {ch.get('chapterName', f'第{i}章')}\n\n"
                                     f"本话共 {n_img} 页，原图见 `pages/`。\n"
                                     f"对白/旁白见原图，待 OCR 文字层（可选）。\n",
                                     label="transcript")
                        count += 1
                        done.add(i)
                        self._save_progress(done)
                    continue
                # 小说模式（默认）：正文落盘为 .txt
                try:
                    body = self.get_content(curl)
                except BrowserRequired as e:
                    # 该源正文动作要求 webView（L3 越界）：整本都不可能成功，早停而非逐章失败
                    self._save_progress(done)
                    return {"name": name, "dir": str(self.book_dir), "chapters": count,
                            "aborted": "browser_required", "detail": str(e)}
                except Exception as e:
                    body = f"[ERROR] {e}"
                body = clean_chapter_text(body)   # B-22：落盘前清洗（去广告/章末噪声/折叠空行）
                fn = f"{i:04d}_{ch_name}.txt"
                # 主文件写入也走容错：沙箱拦截覆盖写时 warn+跳过，不崩整本（B-23）
                write_robust(self.book_dir / fn, body, label="章节")
                count += 1
                done.add(i)
                self._save_progress(done)         # 每章落盘即记进度（断点续爬核心）
        except Exception:
            self._save_progress(done)             # 中断也保活进度
            raise
        self._save_progress(done)
        return {"name": name, "dir": str(self.book_dir), "chapters": count}
