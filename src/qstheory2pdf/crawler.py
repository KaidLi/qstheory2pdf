"""Crawl article info from qstheory.cn (2026 redesign)."""

import os
import re
from urllib.parse import urljoin

import qrcode
import requests
from lxml import etree


def add_backslash4space(string: str) -> str:
    """Add a backslash before each space for LaTeX compatibility."""
    return string.replace(" ", r"\ ")


_STRONG_RE = re.compile(r"<strong>(.*?)</strong>", re.S)
_EM_RE = re.compile(r"<em>(.*?)</em>", re.S)
_KAI_SPAN_RE = re.compile(
    r'<span[^>]*font-family:\s*["\x27]?(?:楷体|KaiTi|kaiti)[^>]*>(.*?)</span>',
    re.S,
)
_HEI_SPAN_RE = re.compile(
    r'<span[^>]*font-family:\s*["\x27]?(?:黑体|SimHei|simhei)[^>]*>(.*?)</span>',
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITIES = {"&emsp;": "", "&ensp;": "", "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">"}


def _strip_tags(raw_html: str) -> str:
    """Extract plain text from HTML, discarding all tags."""
    m = re.search(r"<p[^>]*>(.*)</p>", raw_html, re.S)
    if not m:
        return ""
    inner = _TAG_RE.sub("", m.group(1))
    for ent, repl in _ENTITIES.items():
        inner = inner.replace(ent, repl)
    return re.sub(r"\s+", " ", inner).strip()


def _inner_html_to_latex(raw_html: str) -> str:
    """Convert inner HTML of a <p> to LaTeX-formatted text.

    Preserves: <strong> → \\heiti (CJK bold convention), <em> → \\kaishu (CJK emphasis),
               <span font-family:楷体> → \\kaishu,
               <span font-family:黑体> → \\heiti.
    Discards: <span>, <br>, style attributes.
    """
    # extract content inside <p>…</p>
    m = re.search(r"<p[^>]*>(.*)</p>", raw_html, re.S)
    if not m:
        return ""
    inner = m.group(1)

    # <strong> → \heiti (CJK convention: bold = 黑体, \textbf won't affect CJK)
    inner = _STRONG_RE.sub(r"{\\heiti \1}", inner)
    # <em> → \kaishu (CJK emphasis convention: kaishu, not italic)
    inner = _EM_RE.sub(r"{\\kaishu \1}", inner)
    # font-family spans → CJK font commands (before rest of tags stripped)
    inner = _KAI_SPAN_RE.sub(r"{\\kaishu \1}", inner)
    inner = _HEI_SPAN_RE.sub(r"{\\heiti \1}", inner)
    # strip remaining HTML tags
    inner = _TAG_RE.sub("", inner)
    # decode entities
    for ent, repl in _ENTITIES.items():
        inner = inner.replace(ent, repl)
    # normalize whitespace
    inner = re.sub(r"\s+", " ", inner).strip()
    return inner


class QiuShiCrawler:
    """Crawl article metadata and content from qstheory.cn."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.img_folder = "img"

    # ---- helpers -------------------------------------------------------------

    def _ensure_img_dir(self) -> None:
        os.makedirs(self.img_folder, exist_ok=True)

    def _download_img(self, url: str) -> str:
        self._ensure_img_dir()
        fname = url.rsplit("/", 1)[-1]
        path = os.path.join(self.img_folder, fname)
        if not os.path.exists(path):
            data = self.session.get(url).content
            with open(path, "wb") as f:
                f.write(data)
        return path.replace("\\", "/")

    @staticmethod
    def _is_qr_img(src: str) -> bool:
        return "zxcode" in src.lower()

    @staticmethod
    def _detect_formatting(p_el) -> dict:
        """Detect formatting characteristics of a <p> element.

        *bold* is only True when <strong> wraps the ENTIRE paragraph text.
        Inline <strong> inside longer text is handled by _inner_html_to_latex
        and does NOT set the bold flag.
        """
        style = p_el.get("style", "").lower()
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
        font_size = None
        m = re.search(r"font-size:\s*(\d+)px", style)
        if m:
            font_size = int(m.group(1))

        # extract color from inline style
        color = ""
        m = re.search(r"color:\s*(#[0-9a-fA-F]{6})", style)
        if m:
            color = m.group(1)

        return {
            "center": "text-align: center" in style,
            "bold": is_entirely_bold,
            "em": bool(p_el.xpath(".//em")),
            "large": bool(re.search(r"font-size:\s*(1[89]|2[0-9]|3[0-9])px", style)),
            "font_family": font_family,
            "font_size": font_size,
            "color": color,
        }

    # ---- public API ----------------------------------------------------------

    def download_toc_cover(self, url: str) -> str | None:
        """Download the first content image from the TOC page.

        Returns the local path, or None if no suitable image found.
        """
        resp = self.session.get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)
        imgs = html.xpath('//div[contains(@class,"content")]//img')
        for img in imgs:
            src = img.get("src", "")
            if self._is_qr_img(src):
                continue
            img_url = urljoin(url, src)
            return self._download_img(img_url)
        return None

    def fetch_urls(self, url: str) -> list[str]:
        """Extract article URLs from a magazine issue TOC page."""
        resp = self.session.get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)

        hrefs = html.xpath(
            '//div[contains(@class,"content")]//p//a/@href'
        )
        seen = set()
        articles = []
        for href in hrefs:
            abs_url = urljoin(url, href)
            if abs_url not in seen and "/c.html" in abs_url:
                seen.add(abs_url)
                articles.append(abs_url)
        return articles

    def fetch_toc_entries(self, url: str) -> list[dict]:
        """Extract TOC entries preserving original design formatting.

        Each entry is a dict:
          {'title': ..., 'column': ..., 'subtitle': ...,
           'author': ..., 'author_role': ..., 'url': ...}

        Original design patterns:
          Simple:  <a><strong>Title</strong></a> /<kaishu>Author</kaishu>
          Column:  <a><kaishu>Column</kaishu>│<strong>Title</strong></a>
                   /<kaishu>Author</kaishu>
          Complex: <a>...<strong>Title</strong></a><br/>
                   <a>Subtitle</a> /<kaishu>Author</kaishu>
        """
        resp = self.session.get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)
        ps = html.xpath('//div[contains(@class,"content")]//p[.//a]')

        entries = []
        for p in ps:
            links = p.xpath(".//a")
            if not links:
                continue
            href = urljoin(url, links[0].get("href", ""))
            if "/c.html" not in href:
                continue

            # title from <strong>
            strongs = p.xpath(".//strong//text()")
            title = " ".join(t.strip() for t in strongs).strip()

            # column from 楷体 span before │
            column = ""
            kaishu_spans = p.xpath(
                './/span[contains(@style,"楷体") or contains(@style,"KaiTi")]'
            )
            for ks in kaishu_spans:
                ks_text = ks.xpath("string(.)").strip()
                if ks_text and ks.getparent().tag == "a":
                    # 楷体 text before │ is column name
                    parent_html = etree.tostring(ks.getparent(), encoding="unicode")
                    if "│" in parent_html:
                        idx_ks = parent_html.find(
                            f'<span style="font-family: 楷体;">{ks_text}'
                        )
                        idx_pipe = parent_html.find("│")
                        if idx_ks >= 0 and idx_pipe >= 0 and idx_ks < idx_pipe:
                            column = ks_text
                            break

            # subtitle from second link after <br/> or —
            subtitle = ""
            for a in links[1:]:
                a_text = a.xpath("string(.)").strip()
                if a_text and a_text != title:
                    subtitle = a_text
                    break

            # find subtitle starting with —— if not found
            if not subtitle:
                full_text = p.xpath("string(.)").strip()
                m = re.search(r"(——[^/]+?)(?:\s*/|$)", full_text)
                if m:
                    subtitle = m.group(1).strip()

            # author from 楷体 span after /
            author = ""
            author_role = ""
            for ks in kaishu_spans:
                ks_text = ks.xpath("string(.)").strip()
                if not ks_text:
                    continue
                parent_text = p.xpath("string(.)").strip()
                # find position in full text — author is after /
                slash_pos = parent_text.rfind("/")
                if slash_pos >= 0:
                    after_slash = parent_text[slash_pos + 1:].strip()
                    if ks_text in after_slash:
                        if author:
                            author_role = author
                        author = ks_text

            if title:  # skip empty entries (e.g. sidebar images)
                entries.append({
                    "title": title,
                    "column": column,
                    "subtitle": subtitle,
                    "author": author,
                    "author_role": author_role,
                    "url": href,
                })
        return entries

    def fetch_info(self, url: str, *, with_qr: bool = False) -> dict:
        """Extract metadata and content from a single article page.

        Content blocks are dicts:
          {'text': ..., 'bold': bool, 'center': bool, 'large': bool}
          {'img': path, 'caption': ...}
        """
        resp = self.session.get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)

        # ---- title -----------------------------------------------------------
        title = (html.xpath("//h1/text()") or [""])[0].strip()
        title = re.sub(r"\s+", " ", title)

        # ---- volume / author from appellation spans --------------------------
        app_els = html.xpath('//span[@class="appellation"]')
        volume = ""
        author = ""
        for el in app_els:
            text = el.text.strip() if el.text else ""
            if text.startswith("来源") and "求是" in text:
                volume = text[2:]
                m = re.search(r"《求是》\d{4}/\d{2}", volume)
                volume = m.group(0) if m else volume
            elif text.startswith("作者"):
                author = text[3:]

        # ---- content paragraphs ----------------------------------------------
        content_ps = html.xpath(
            '//div[contains(@class,"content")]//p'
        )

        # ---- subtitle detection in preamble ----------------------------------
        subtitle = ""
        body_start = 0
        for i, p in enumerate(content_ps):
            text = p.xpath("string(.)").strip()
            style = (p.get("style") or "").lower()

            if author and text == author:
                body_start = i + 1
                break
            if not author and i >= 1:
                body_start = i
                break

            # detect subtitle: centered bold paragraph starting with ——
            if text.startswith("——") and "center" in style:
                subtitle = text

        result = {
            "title": add_backslash4space(title),
            "subtitle": add_backslash4space(subtitle),
            "author": add_backslash4space(author),
            "volume": add_backslash4space(volume),
            "content": [],
        }

        i = body_start
        while i < len(content_ps):
            p = content_ps[i]
            text = p.xpath("string(.)").strip()

            img_tags = p.xpath(".//img")
            if img_tags:
                # Collect non-QR images and look for a caption
                images = []
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
                    result["content"].append(
                        {"img": local, "caption": add_backslash4space(caption or img_caption)}
                    )
            elif text:
                fmt = self._detect_formatting(p)
                raw = etree.tostring(p, encoding="unicode")
                if fmt["bold"]:
                    latex_text = _strip_tags(raw)
                else:
                    latex_text = _inner_html_to_latex(raw)

                # detect author attribution for right-alignment
                is_right = text.startswith("作者") or text.startswith("（作者")

                if latex_text:
                    result["content"].append(
                        {
                            "text": add_backslash4space(latex_text),
                            "bold": fmt["bold"],
                            "center": fmt["center"],
                            "large": fmt["large"],
                            "right": is_right,
                            "font_family": fmt["font_family"],
                            "font_size": fmt["font_size"],
                            "color": fmt["color"],
                        }
                    )
            i += 1

        if with_qr:
            result["qrcode"] = self._gen_qr(url)

        return result

    # ---- QR code -------------------------------------------------------------

    def _gen_qr(self, url: str) -> str:
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
        path = os.path.join(self.img_folder, "qrcode.png")
        img.save(path)
        return path
