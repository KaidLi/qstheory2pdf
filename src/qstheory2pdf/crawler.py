"""Crawl article info from qstheory.cn (2026 redesign).

This module is the data-acquisition layer. It returns raw semantic data; all
LaTeX formatting is handled by gen_pdf.py.
"""

import os
import re
from urllib.parse import urljoin

import qrcode
import requests
from lxml import etree

from qstheory2pdf.types import Article, ContentBlock, TocEntry, TocResult

# Date pattern encoded in qstheory.cn article URLs: /YYYYMMDD/hash/c.html
_DATE_URL_RE = re.compile(r"/(\d{4})(\d{2})(\d{2})/")


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

    def _ensure_img_dir(self) -> None:
        os.makedirs(self.image_dir, exist_ok=True)

    def _download_img(self, url: str) -> str:
        """Download image into image_dir, return filename relative to it."""
        self._ensure_img_dir()
        fname = url.rsplit("/", 1)[-1]
        path = os.path.join(self.image_dir, fname)
        if not os.path.exists(path):
            data = self.session.get(url).content
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
            "center": "text-align: center" in style,
            "bold": is_entirely_bold,
            "italic": bool(p_el.xpath(".//em")),
            "large": bool(re.search(r"font-size:\s*(1[89]|2[0-9]|3[0-9])px", style)),
            "font_family": font_family,
            "font_size": font_size,
        }

    @staticmethod
    def _extract_date_from_url(url: str) -> str:
        """Extract YYYY-MM-DD from qstheory.cn article URL."""
        m = _DATE_URL_RE.search(url)
        if not m:
            return ""
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # ---- public API ----------------------------------------------------------

    def download_toc_cover(self, url: str) -> str | None:
        """Download the first content image from the TOC page.

        Returns the filename (relative to image_dir), or None if no suitable
        image found.
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

    def fetch_toc(self, url: str) -> TocResult:
        """Fetch a magazine issue TOC page in a single HTTP request.

        Returns:
            {"urls": [list of article URLs in order],
             "entries": [parallel list of TocEntry dicts, may be shorter]}
        """
        resp = self.session.get(url)
        resp.encoding = "utf-8"
        html = etree.HTML(resp.text)

        # Collect article URLs from <a> tags inside content paragraphs.
        hrefs = html.xpath(
            '//div[contains(@class,"content")]//p//a/@href'
        )
        seen: set[str] = set()
        urls: list[str] = []
        for href in hrefs:
            abs_url = urljoin(url, href)
            if abs_url not in seen and "/c.html" in abs_url:
                seen.add(abs_url)
                urls.append(abs_url)

        # Parse TOC entries preserving original design formatting.
        # Original design patterns:
        #   Simple:  <a><strong>Title</strong></a> /<kaishu>Author</kaishu>
        #   Column:  <a><kaishu>Column</kaishu>│<strong>Title</strong></a>
        #            /<kaishu>Author</kaishu>
        #   Complex: <a>...<strong>Title</strong></a><br/>
        #            <a>Subtitle</a> /<kaishu>Author</kaishu>
        ps = html.xpath('//div[contains(@class,"content")]//p[.//a]')
        entries: list[TocEntry] = []
        for p in ps:
            entry = self._parse_toc_paragraph(p, url)
            if entry is not None:
                entries.append(entry)

        return {"urls": urls, "entries": entries}

    @staticmethod
    def _parse_toc_paragraph(p, base_url: str) -> TocEntry | None:
        links = p.xpath(".//a")
        if not links:
            return None
        href = urljoin(base_url, links[0].get("href", ""))
        if "/c.html" not in href:
            return None

        # title from <strong>
        strongs = p.xpath(".//strong//text()")
        title = " ".join(t.strip() for t in strongs).strip()
        if not title:
            return None

        # column from 楷体 span before │
        column = ""
        kaishu_spans = p.xpath(
            './/span[contains(@style,"楷体") or contains(@style,"KaiTi")]'
        )
        for ks in kaishu_spans:
            ks_text = ks.xpath("string(.)").strip()
            if ks_text and ks.getparent().tag == "a":
                parent_html = etree.tostring(ks.getparent(), encoding="unicode")
                if "│" in parent_html:
                    idx_ks = parent_html.find(
                        f'<span style="font-family: 楷体;">{ks_text}'
                    )
                    idx_pipe = parent_html.find("│")
                    if idx_ks >= 0 and idx_pipe >= 0 and idx_ks < idx_pipe:
                        column = ks_text
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
        author = ""
        author_role = ""
        for ks in kaishu_spans:
            ks_text = ks.xpath("string(.)").strip()
            if not ks_text:
                continue
            parent_text = p.xpath("string(.)").strip()
            slash_pos = parent_text.rfind("/")
            if slash_pos >= 0:
                after_slash = parent_text[slash_pos + 1:].strip()
                if ks_text in after_slash:
                    if author:
                        author_role = author
                    author = ks_text

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

        # ---- subtitle / body_start detection in preamble --------------------
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

        result: Article = {
            "title": title,
            "subtitle": subtitle,
            "author": author,
            "volume": volume,
            "date": self._extract_date_from_url(url),
            "content": [],
        }

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
                is_right = text.startswith("作者") or text.startswith("（作者")

                if text:
                    block: ContentBlock = {
                        "text": text,
                        "bold": fmt["bold"],
                        "italic": fmt["italic"],
                        "center": fmt["center"],
                        "large": fmt["large"],
                        "right": is_right,
                        "font_family": fmt["font_family"],  # type: ignore[typeddict-item]
                        "font_size": fmt["font_size"],
                    }
                    result["content"].append(block)
            i += 1

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
