"""Crawl article info from qstheory.cn (2026 redesign).

This module is the data-acquisition layer. It returns raw semantic data; all
LaTeX formatting is handled by gen_pdf.py.
"""

import hashlib
import json
import os
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

import qrcode
import requests
from lxml import etree

from qstheory2pdf.types import Article, ContentBlock, TextRole, TocEntry, TocResult

# Date pattern encoded in qstheory.cn article URLs: /YYYYMMDD/hash/c.html
_DATE_URL_RE = re.compile(r"/(\d{4})(\d{2})(\d{2})/")

# (connect, read) timeout for all HTTP requests — without this a stalled
# connection hangs the CLI forever.
_TIMEOUT = (10, 30)

# TOC section headings (栏目) are short standalone lines like 文化中国 /
# 深度调研 / 党员来信 / 统计图表 — no link, no punctuation, 2–8 chars.
_COLUMN_TEXT_RE = re.compile(r"^[一-鿿]{2,8}$")
# words that appear in short non-column lines (page furniture)
_COLUMN_BLACKLIST = ("编辑", "校对", "审核", "来源", "作者", "封面", "目录",
                     "上一篇", "下一篇", "分享", "打印", "返回", "相关", "推荐", "更多")


class QiuShiCrawler:
    """Crawl article metadata and content from qstheory.cn.

    The crawler writes images (article figures + QR code) into `image_dir` and
    returns paths relative to that directory in the emitted Article. The caller
    (typically PDFGenerator) owns the lifecycle of `image_dir`.
    """

    def __init__(self, image_dir: str = "./img") -> None:
        self.session = requests.Session()
        # Identify ourselves; some servers reject unidentified clients.
        self.session.headers.setdefault(
            "User-Agent", "qstheory2pdf/0.1 (+https://github.com/KaidLi/qstheory2pdf)"
        )
        self.image_dir = image_dir

    # ---- helpers -------------------------------------------------------------

    def _get(self, url: str) -> requests.Response:
        """GET with timeout; raise on HTTP error status."""
        resp = self.session.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp

    def _ensure_img_dir(self) -> None:
        os.makedirs(self.image_dir, exist_ok=True)

    def _download_img(self, url: str) -> str:
        """Download image into image_dir, return filename relative to it."""
        self._ensure_img_dir()
        parsed = urlsplit(url)
        original = PurePosixPath(unquote(parsed.path)).name
        stem, extension = os.path.splitext(original)
        extension = extension.lower()
        supported = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg")
        safe_stem = re.sub(r"[^\w\u4e00-\u9fff-]", "_", stem).strip("_")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        prefix = f"{safe_stem or 'image'}-{digest}"

        data: bytes | None = None
        if extension not in supported:
            for candidate in supported:
                cached = os.path.join(self.image_dir, prefix + candidate)
                if os.path.exists(cached):
                    return prefix + candidate
            response = self._get(url)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
            extension = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/svg+xml": ".svg",
            }.get(content_type, ".jpg")
            data = response.content

        fname = prefix + extension
        path = os.path.join(self.image_dir, fname)
        if not os.path.exists(path):
            if data is None:
                data = self._get(url).content
            with open(path, "wb") as f:
                f.write(data)
        return fname

    @staticmethod
    def _is_qr_img(src: str) -> bool:
        return "zxcode" in src.lower()

    @staticmethod
    def _detect_formatting(p_el) -> dict:
        """Detect formatting characteristics of a <p> element.

        *bold* is only True when <strong> wraps the ENTIRE paragraph text.
        Inline <strong> inside longer text is handled at the LaTeX layer and
        does NOT set the bold flag.
        """
        style = p_el.get("style", "").lower()
        # normalize whitespace so "text-align: right" and "text-align:right"
        # both match
        style_norm = re.sub(r"\s+", "", style)
        full_text = p_el.xpath("string(.)").strip()
        strong_text = "".join(p_el.xpath(".//strong//text()")).strip()
        is_entirely_bold = bool(strong_text) and strong_text == full_text

        # extract font-family from descendant <span> styles
        font_family = ""
        for span in p_el.xpath(".//span"):
            span_style = (span.get("style") or "").lower()
            if "楷体" in span_style or "kaiti" in span_style:
                font_family = "kai"
                break
            elif "黑体" in span_style or "heiti" in span_style or "simhei" in span_style:
                font_family = "hei"
                break
            elif "宋体" in span_style or "simsun" in span_style:
                font_family = "song"
                break
            elif "仿宋" in span_style or "fangsong" in span_style:
                font_family = "fang"
                break

        # extract numeric font-size from p style
        font_size = 0
        m = re.search(r"font-size:\s*(\d+)px", style)
        if m:
            font_size = int(m.group(1))

        return {
            "center": "text-align:center" in style_norm,
            # right/left alignment declared inline on the <p> (same mechanism
            # the site uses for centering); left also covers text-indent:0
            # (letter salutations like 编辑同志： are flush-left, no indent)
            "right": "text-align:right" in style_norm,
            "left": ("text-align:left" in style_norm
                     or re.search(r"text-indent:0(?:em|px|pt)?(?:;|$)", style_norm) is not None),
            "bold": is_entirely_bold,
            "italic": bool(p_el.xpath(".//em")),
            "large": bool(re.search(r"font-size:\s*(1[89]|2[0-9]|3[0-9])px", style)),
            "font_family": font_family,
            "font_size": font_size,
        }

    @staticmethod
    def _text_role(
        text: str,
        *,
        bold: bool,
        center: bool,
        large: bool,
        salutation: bool,
        signature: bool,
    ) -> TextRole:
        """Classify a paragraph by meaning instead of appearance alone."""
        if salutation:
            return "salutation"
        if signature:
            return "signature"
        numbered_heading = re.match(
            r"^(?:"
            r"[一二三四五六七八九十百]+[、．.]"
            r"|第[一二三四五六七八九十百\d]+[章节篇部分]"
            r"|[（(]?[一二三四五六七八九十百]+[）)]"
            r"|\d+[、．.]"
            r")",
            text,
        )
        if bold and (center or large or numbered_heading):
            return "section_heading"
        return "body"

    @staticmethod
    def _extract_date_from_url(url: str) -> str:
        """Extract YYYY-MM-DD from qstheory.cn article URL."""
        m = _DATE_URL_RE.search(url)
        if not m:
            return ""
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    @staticmethod
    def _extract_json_ld_metadata(html) -> dict[str, str]:
        """从 JSON-LD 中提取标题、作者和期号回退值。"""
        result = {"title": "", "author": "", "volume": ""}
        candidates: list[dict] = []
        for raw in html.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                value = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                graph = value.get("@graph")
                if isinstance(graph, list):
                    candidates.extend(item for item in graph if isinstance(item, dict))
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))

        for item in candidates:
            if not result["title"]:
                result["title"] = str(item.get("headline") or item.get("name") or "").strip()
            if not result["author"]:
                author = item.get("author")
                if isinstance(author, dict):
                    result["author"] = str(author.get("name") or "").strip()
                elif isinstance(author, list):
                    names = [
                        str(value.get("name") or "").strip()
                        for value in author
                        if isinstance(value, dict)
                    ]
                    result["author"] = "、".join(name for name in names if name)
                elif isinstance(author, str):
                    result["author"] = author.strip()
            if not result["volume"]:
                serialized = json.dumps(item, ensure_ascii=False)
                match = re.search(r"《求是》\d{4}/\d{1,2}", serialized)
                if match:
                    result["volume"] = match.group(0)
        return result

    # ---- public API ----------------------------------------------------------

    def download_toc_cover(self, url: str) -> str | None:
        """Download the best available cover image from the TOC page.

        Returns the filename (relative to image_dir), or None if no suitable
        image found.
        """
        resp = self._get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)
        imgs = html.xpath('//div[contains(@class,"content")]//img')
        for img in imgs:
            candidates = []
            srcset = img.get("srcset", "")
            if srcset:
                parsed_srcset = []
                for item in srcset.split(","):
                    parts = item.strip().split()
                    if not parts:
                        continue
                    descriptor = parts[1] if len(parts) > 1 else "1x"
                    match = re.match(r"(\d+(?:\.\d+)?)(?:w|x)?$", descriptor)
                    score = float(match.group(1)) if match else 0.0
                    parsed_srcset.append((score, parts[0]))
                if parsed_srcset:
                    candidates.append(max(parsed_srcset)[1])
            for attribute in ("data-original", "data-src", "src"):
                value = (img.get(attribute) or "").strip()
                if value:
                    candidates.append(value)
            for candidate in candidates:
                if not self._is_qr_img(candidate):
                    return self._download_img(urljoin(url, candidate))

        for candidate in html.xpath('//meta[@property="og:image"]/@content'):
            candidate = candidate.strip()
            if candidate and not self._is_qr_img(candidate):
                return self._download_img(urljoin(url, candidate))
        return None

    @classmethod
    def _looks_like_column_heading(cls, text: str) -> bool:
        """True if a link-less TOC line looks like a 栏目 heading.

        2026 TOC design: 栏目 names are short standalone lines (文化中国 /
        深度调研 / 学习问答 / 党员来信 / 党刊精选 / 统计图表 …) between the
        entry rows, not inline "栏目│标题" prefixes as in the old design.
        """
        norm = re.sub(r"\s+", "", text)
        if not _COLUMN_TEXT_RE.match(norm):
            return False
        return not any(w in norm for w in _COLUMN_BLACKLIST)

    def fetch_toc(self, url: str) -> TocResult:
        """Fetch a magazine issue TOC page in a single HTTP request.

        Walks block-level elements of the content area in document order:
        blocks containing article links become entries; short link-less
        lines in between are 栏目 headings and are attached to the entries
        that follow them (matching the printed magazine's section layout).

        Returns:
            {"urls": [list of article URLs in order],
             "entries": [parallel list of TocEntry dicts, may be shorter]}
        """
        resp = self._get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)

        # Block-level walk in document order. Entries are usually <p>, but
        # some sections (发现于 2026/14: 党员来信 等尾部栏目) sit in other
        # wrappers — include li/h2/h3/h4 and div-with-direct-link so no
        # section is skipped.
        blocks = html.xpath(
            '//div[contains(@class,"content")]'
            '//*[self::p or self::li or self::h2 or self::h3 or self::h4'
            ' or (self::div and a and not(.//p) and not(.//li))]'
        )

        seen_urls: set[str] = set()
        seen_entry_urls: set[str] = set()
        urls: list[str] = []
        entries: list[TocEntry] = []
        current_column = ""

        for b in blocks:
            hrefs = [urljoin(url, h) for h in b.xpath(".//a/@href")]
            art_hrefs = [h for h in hrefs if "/c.html" in h and h != url]

            if art_hrefs:
                for h in art_hrefs:
                    if h not in seen_urls:
                        seen_urls.add(h)
                        urls.append(h)
                entry = self._parse_toc_paragraph(b, url)
                if entry is not None and entry["url"] != url \
                        and entry["url"] not in seen_entry_urls:
                    if not entry["column"]:
                        entry["column"] = current_column
                    seen_entry_urls.add(entry["url"])
                    entries.append(entry)
            else:
                text = b.xpath("string(.)").strip()
                if text and self._looks_like_column_heading(text):
                    current_column = text

        # Safety net: catch article links living outside the walked block
        # types (unknown wrappers) so no article is silently dropped —
        # entry.py synthesizes a TOC row from the article page for these.
        for h in html.xpath('//div[contains(@class,"content")]//a/@href'):
            ab = urljoin(url, h)
            if "/c.html" in ab and ab != url and ab not in seen_urls:
                seen_urls.add(ab)
                urls.append(ab)

        return {"urls": urls, "entries": entries}

    @staticmethod
    def _parse_toc_paragraph(p, base_url: str) -> TocEntry | None:
        links = p.xpath(".//a")
        if not links:
            return None
        href = urljoin(base_url, links[0].get("href", ""))
        if "/c.html" not in href:
            return None

        # title from <strong>; fall back to the link's own text (some 2026
        # rows carry no <strong>)
        strongs = p.xpath(".//strong//text()")
        title = " ".join(t.strip() for t in strongs).strip()
        if not title:
            title = links[0].xpath("string(.)").strip()
        if not title:
            return None

        # legacy inline column (2025 design): 楷体 span followed by │ inside
        # the <a>. 2026 pages use standalone heading lines instead (handled
        # by fetch_toc); keep this for backward compatibility.
        column = ""
        kaishu_spans = p.xpath(
            './/span[contains(@style,"楷体") or contains(@style,"KaiTi")]'
        )
        for ks in kaishu_spans:
            ks_text = ks.xpath("string(.)").strip()
            if not ks_text:
                continue
            parent = ks.getparent()
            tail = (ks.tail or "").lstrip()
            if parent is not None and parent.tag == "a" and tail.startswith("│"):
                column = ks_text
                break

        # 2026 variant: parenthetical column suffix inside the <a> AFTER the
        # title, e.g. <a><strong>多一些“想法子办”</strong><span style="…楷体…">
        # （党员来信）</span></a> — observed on the real 2026/14 TOC page.
        # The title comes from <strong> only, so it stays clean.
        if not column:
            for ks in kaishu_spans:
                parent = ks.getparent()
                if parent is None or parent.tag != "a":
                    continue
                ks_text = ks.xpath("string(.)").strip()
                m = re.fullmatch(r"[（(]([^（）()]{2,8})[）)]", ks_text)
                if m:
                    column = m.group(1)
                    break

        # subtitle from second link after <br/> or ——
        subtitle = ""
        for a in links[1:]:
            a_text = a.xpath("string(.)").strip()
            if a_text and a_text != title:
                subtitle = a_text
                break

        if not subtitle:
            full_text = p.xpath("string(.)").strip()
            m = re.search(r"(——[^/]+?)(?:\s*/|$)", full_text)
            if m:
                subtitle = m.group(1).strip()

        # author / author_role from 楷体 span after /
        # The slash may sit outside the span (…</a> /<span>作者</span>) or
        # inside it (<span>/习近平</span>) — strip a leading slash from the
        # span text before matching.
        author = ""
        author_role = ""
        parent_text = p.xpath("string(.)").strip()
        slash_pos = parent_text.rfind("/")
        for ks in kaishu_spans:
            ks_text = ks.xpath("string(.)").strip().lstrip("/").strip()
            if not ks_text:
                continue
            if slash_pos >= 0:
                after_slash = parent_text[slash_pos + 1:].strip()
                if ks_text in after_slash:
                    if author:
                        author_role = author
                    author = ks_text

        # plain-text author fallback (2026 rows: "<strong>标题</strong> /作者"
        # with no 楷体 span): take the text after the last slash
        if not author and slash_pos >= 0:
            candidate = parent_text[slash_pos + 1:].strip()
            if candidate and len(candidate) <= 40 and "http" not in candidate:
                author = candidate

        return {
            "title": title,
            "column": column,
            "subtitle": subtitle,
            "author": author,
            "author_role": author_role,
            "url": href,
        }

    def fetch_info(self, url: str, *, with_qr: bool = False) -> Article:
        """Extract metadata and content from a single article page.

        Returns an Article TypedDict. Image paths inside `content` and the
        optional `qrcode` field are relative to `self.image_dir`.
        """
        resp = self._get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)

        json_ld = self._extract_json_ld_metadata(html)

        # ---- title -----------------------------------------------------------
        title_values = (
            html.xpath("//h1/text()")
            or html.xpath('//meta[@property="og:title"]/@content')
            or html.xpath('//meta[@name="title"]/@content')
        )
        title = (title_values or [json_ld["title"]])[0].strip()
        title = re.sub(r"\s+", " ", title)

        # ---- volume / author from appellation spans --------------------------
        app_els = html.xpath('//span[@class="appellation"]')
        volume = ""
        author = ""
        for el in app_els:
            text = el.xpath("string(.)").strip()
            if text.startswith("来源") and "求是" in text:
                volume = text[2:]
                m = re.search(r"《求是》\d{4}/\d{2}", volume)
                volume = m.group(0) if m else volume
            elif text.startswith("作者"):
                author = text[3:]

        if not author:
            author_values = (
                html.xpath('//meta[@name="author"]/@content')
                or html.xpath('//meta[@property="article:author"]/@content')
            )
            author = (author_values or [json_ld["author"]])[0].strip()
        if not volume:
            description_values = (
                html.xpath('//meta[@name="description"]/@content')
                or html.xpath('//meta[@property="og:description"]/@content')
            )
            description = (description_values or [""])[0]
            match = re.search(r"《求是》\d{4}/\d{1,2}", description)
            volume = match.group(0) if match else json_ld["volume"]

        # ---- content paragraphs ----------------------------------------------
        content_ps = html.xpath(
            '//div[contains(@class,"content")]//p'
        )

        # ---- subtitle / body_start detection in preamble --------------------
        # The first few <p>s repeat column/title/subtitle/author; the author
        # line marks the end of that preamble. Compare with ALL whitespace
        # stripped: two-char names are spaced out on the page ("文 平" vs
        # appellation "文平"). Scan only the first few paragraphs — letters
        # end with a spaced signature that would otherwise match and swallow
        # the whole body; articles without a preamble correctly keep 0.
        subtitle = ""
        body_start = 0
        norm_author = re.sub(r"\s+", "", author)
        for i, p in enumerate(content_ps[:5]):
            text = p.xpath("string(.)").strip()
            style = (p.get("style") or "").lower()

            if author and re.sub(r"\s+", "", text) == norm_author:
                body_start = i + 1
                break
            if not author and i >= 1:
                body_start = i
                break

            # detect subtitle: centered bold paragraph starting with ——
            if text.startswith("——") and "center" in style:
                subtitle = text

        result: Article = {
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "volume": volume,
            "date": self._extract_date_from_url(url),
            "url": url,
            "content": [],
        }

        first_text_block = True
        i = body_start
        while i < len(content_ps):
            p = content_ps[i]
            text = p.xpath("string(.)").strip()

            img_tags = p.xpath(".//img")
            if img_tags:
                # Collect non-QR images and look for a caption
                images: list[tuple[str, str]] = []
                for img in img_tags:
                    src = img.get("src", "")
                    if self._is_qr_img(src):
                        continue
                    img_url = urljoin(url, src)
                    local = self._download_img(img_url)
                    caption = img.get("alt", "").strip() or text
                    images.append((local, caption))

                # If no caption found, peek at next paragraph — on qstheory.cn,
                # image captions are often in a following FangSong/KaiTi <p>
                caption = images[0][1] if images else ""
                if not caption and i + 1 < len(content_ps):
                    next_p = content_ps[i + 1]
                    next_text = next_p.xpath("string(.)").strip()
                    next_fmt = self._detect_formatting(next_p)
                    if next_fmt["font_family"] in ("fang", "kai") and not next_p.xpath(".//strong"):
                        caption = next_text
                        i += 1  # consume the caption paragraph

                for local, img_caption in images:
                    block: ContentBlock = {
                        "img": local,
                        "caption": caption or img_caption,
                    }
                    result["content"].append(block)
            elif text:
                fmt = self._detect_formatting(p)
                # raw text content; gen_pdf.py applies LaTeX escaping
                # detect author attribution for right-alignment
                is_right = fmt["right"] or text.startswith("作者") or text.startswith("（作者")
                # letter salutation (信件抬头 "编辑同志："): short first body
                # line ending with a full-width colon — flush left, no indent
                is_left = fmt["left"]
                is_salutation = bool(
                    first_text_block
                    and re.fullmatch(r"[^：:，。；]{1,10}[：:]", text)
                )
                if is_salutation:
                    is_left = True

                if text:
                    role = self._text_role(
                        text,
                        bold=fmt["bold"],
                        center=fmt["center"],
                        large=fmt["large"],
                        salutation=is_salutation,
                        signature=is_right,
                    )
                    block: ContentBlock = {
                        "text": text,
                        "bold": fmt["bold"],
                        "italic": fmt["italic"],
                        "center": fmt["center"],
                        "large": fmt["large"],
                        "right": is_right,
                        "left": is_left,
                        "font_family": fmt["font_family"],  # type: ignore[typeddict-item]
                        "font_size": fmt["font_size"],
                        "role": role,
                    }
                    result["content"].append(block)
                    first_text_block = False
            i += 1

        # ---- letter signature (信件署名) ------------------------------------
        # Letters close with "单位名 作者名" as the LAST paragraph, right-
        # aligned on the page. If the final text block ends with the author
        # name and is short, right-align it (styles are not always inline).
        if author:
            for block in reversed(result["content"]):
                if "text" in block:
                    norm_text = re.sub(r"\s+", "", block["text"])
                    if (norm_text.endswith(norm_author)
                            and len(norm_text) <= 30
                            and not block.get("center")):
                        block["right"] = True
                        block["role"] = "signature"
                    break

        if with_qr:
            result["qrcode"] = self._gen_qr(url)

        return result

    # ---- QR code -------------------------------------------------------------

    def _gen_qr(self, url: str) -> str:
        """Generate QR PNG into image_dir, return filename relative to it."""
        self._ensure_img_dir()
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=2,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        fname = "qrcode.png"
        path = os.path.join(self.image_dir, fname)
        img.save(path)
        return fname
