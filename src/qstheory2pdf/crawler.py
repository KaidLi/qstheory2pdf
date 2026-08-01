"""Acquire and interpret qstheory.cn source documents.

The crawler emits domain data from :mod:`qstheory2pdf.types`; it never emits
LaTeX/EPUB fragments.  Source-document kind, publication identity, and
completeness diagnostics are established here from source semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

import qrcode
import requests
from lxml import etree

from qstheory2pdf.domain import reconstruction_status, validate_article
from qstheory2pdf.types import (
    Article,
    BodyElement,
    CatalogIssue,
    FigureBlock,
    FigureImage,
    InlineRun,
    Issue,
    IssueCatalog,
    IssueEntry,
    IssueId,
    ParagraphBlock,
    ReconstructionProblem,
    SourceDocument,
    TableCell,
    TextRole,
)

_TIMEOUT = (10, 30)
_SOURCE_ID_RE = re.compile(r"/([0-9a-fA-F]{32})/c\.html(?:$|[?#])")
_ISSUE_PATTERNS = (
    re.compile(r"《求是》\s*(\d{4})/(\d{1,2})"),
    re.compile(r"(?:《求是》)?\s*(\d{4})\s*年第\s*(\d{1,2})\s*期"),
)
_COLUMN_TEXT_RE = re.compile(r"^[一-鿿]{2,8}$")
_COLUMN_BLACKLIST = (
    "编辑", "校对", "审核", "来源", "作者", "封面", "目录", "上一篇", "下一篇",
    "分享", "打印", "返回", "相关", "推荐", "更多",
)
_SUPPORTED_BODY_TAGS = {
    "p", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol", "table", "figure", "picture",
}
_WRAPPER_TAGS = {"div", "section", "article", "main"}
_UNSUPPORTED_SUBSTANTIVE_TAGS = {
    "video", "audio", "iframe", "canvas", "svg", "object", "embed", "math", "pre", "dl",
}


class SourceClassificationError(ValueError):
    """Raised when a source page does not express one known domain kind."""


class QiuShiCrawler:
    def __init__(self, image_dir: str = "./img") -> None:
        self.session = requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "qstheory2pdf/0.3 (+https://github.com/KaidLi/qstheory2pdf)"
        )
        self.image_dir = image_dir

    # ---- network and resources ---------------------------------------------

    def _get(self, url: str) -> requests.Response:
        response = self.session.get(url, timeout=_TIMEOUT)
        response.raise_for_status()
        return response

    def _ensure_img_dir(self) -> None:
        os.makedirs(self.image_dir, exist_ok=True)

    def _download_img(self, url: str) -> str:
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

        filename = prefix + extension
        path = os.path.join(self.image_dir, filename)
        if not os.path.exists(path):
            if data is None:
                data = self._get(url).content
            with open(path, "wb") as stream:
                stream.write(data)
        return filename

    @staticmethod
    def _is_qr_img(src: str) -> bool:
        return "zxcode" in src.lower()

    def download_toc_cover(self, url: str) -> str | None:
        response = self._get(url)
        response.encoding = "utf-8"
        html = etree.HTML(response.text)
        for image in html.xpath('//div[contains(@class,"content")]//img'):
            candidates: list[str] = []
            srcset = image.get("srcset", "")
            if srcset:
                weighted: list[tuple[float, str]] = []
                for item in srcset.split(","):
                    parts = item.strip().split()
                    if not parts:
                        continue
                    descriptor = parts[1] if len(parts) > 1 else "1x"
                    match = re.match(r"(\d+(?:\.\d+)?)(?:w|x)?$", descriptor)
                    weighted.append((float(match.group(1)) if match else 0.0, parts[0]))
                if weighted:
                    candidates.append(max(weighted)[1])
            for attribute in ("data-original", "data-src", "src"):
                value = (image.get(attribute) or "").strip()
                if value:
                    candidates.append(value)
            for candidate in candidates:
                if not self._is_qr_img(candidate):
                    return self._download_img(urljoin(url, candidate))
        for candidate in html.xpath('//meta[@property="og:image"]/@content'):
            if candidate.strip() and not self._is_qr_img(candidate):
                return self._download_img(urljoin(url, candidate.strip()))
        return None

    # ---- source document classification -----------------------------------

    def fetch_document(self, url: str, *, with_qr: bool = False) -> SourceDocument:
        """Fetch a source exactly once and return its semantic document kind."""
        response = self._get(url)
        response.encoding = "utf-8"
        html = etree.HTML(response.text)
        if html is None:
            raise SourceClassificationError("来源没有可解析的 HTML")

        catalog = self._parse_catalog(html, url)
        if catalog is not None:
            return {"kind": "issue_catalog", "catalog": catalog}

        issue = self._parse_issue(html, url)
        if issue is not None:
            return {"kind": "issue_contents", "issue": issue}

        if self._looks_like_article(html):
            article = self._parse_article(html, url, with_qr=with_qr)
            return {"kind": "article", "article": article}

        raise SourceClassificationError("无法把来源识别为文章、官方期次目录或期次目录集")

    def fetch_info(self, url: str, *, with_qr: bool = False) -> Article:
        """Fetch one source that must semantically classify as an article."""
        document = self.fetch_document(url, with_qr=with_qr)
        if document["kind"] != "article":
            raise SourceClassificationError(
                f"来源不是文章，而是 {document['kind']}"
            )
        return document["article"]

    @classmethod
    def _looks_like_article(cls, html) -> bool:
        has_heading = bool(
            html.xpath("//h1")
            or html.xpath('//meta[@property="og:title"]/@content')
            or html.xpath('//meta[@name="title"]/@content')
            or cls._json_ld_metadata(html)["title"]
        )
        has_content = bool(html.xpath('//div[contains(@class,"content")]'))
        return has_heading and has_content

    # ---- common metadata ---------------------------------------------------

    @staticmethod
    def _normal_text(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @classmethod
    def _source_id(cls, url: str) -> str:
        match = _SOURCE_ID_RE.search(url)
        return match.group(1).lower() if match else ""

    @classmethod
    def _canonical_url(cls, html, base_url: str) -> str:
        values = (
            html.xpath('//link[contains(concat(" ", normalize-space(@rel), " "), " canonical ")]/@href')
            or html.xpath('//meta[@property="og:url"]/@content')
        )
        return urljoin(base_url, values[0].strip()) if values and values[0].strip() else base_url

    @classmethod
    def _issue_id_from_text(cls, text: str) -> IssueId | None:
        for pattern in _ISSUE_PATTERNS:
            match = pattern.search(text)
            if match:
                return {
                    "publication_year": int(match.group(1)),
                    "issue_number": int(match.group(2)),
                }
        return None

    @staticmethod
    def _date_from_text(value: str) -> str:
        match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value.strip())
        if not match:
            match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value.strip())
        if not match:
            return ""
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

    @classmethod
    def _declared_date(cls, html) -> str:
        values = (
            html.xpath('//meta[@property="article:published_time"]/@content')
            or html.xpath('//meta[@name="datePublished"]/@content')
            or html.xpath('//meta[@name="publishdate"]/@content')
        )
        values.extend(
            html.xpath(
                '//*[contains(concat(" ", normalize-space(@class), " "), " pubtime ")]/text()'
            )
        )
        for value in values:
            declared = cls._date_from_text(value)
            if declared:
                return declared

        for item in cls._json_ld_items(html):
            value = item.get("datePublished")
            if isinstance(value, str):
                declared = cls._date_from_text(value)
                if declared:
                    return declared
        return ""

    @classmethod
    def _declared_issue_date(cls, html) -> str:
        """Return only an explicitly labelled date for the issue itself."""
        meta_values = html.xpath(
            '//meta[@name="issue_publication_date" or @name="issue:publication_date" '
            'or @property="issue:publication_date"]/@content'
        )
        for value in meta_values:
            declared = cls._date_from_text(value)
            if declared:
                return declared

        for element in html.xpath("//span | //p | //time | //div[not(*)]"):
            text = cls._normal_text(element.xpath("string(.)"))
            if not re.search(r"(?:本期)?(?:出版|发行|刊行)日期", text):
                continue
            declared = cls._date_from_text(text)
            if declared:
                return declared
        return ""

    @staticmethod
    def _json_ld_items(html) -> list[dict]:
        items: list[dict] = []
        for raw in html.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                value = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            values = value if isinstance(value, list) else [value]
            for candidate in values:
                if not isinstance(candidate, dict):
                    continue
                graph = candidate.get("@graph")
                if isinstance(graph, list):
                    items.extend(item for item in graph if isinstance(item, dict))
                items.append(candidate)
        return items

    @classmethod
    def _json_ld_metadata(cls, html) -> dict[str, str]:
        result = {"title": "", "byline": "", "issue_label": ""}
        for item in cls._json_ld_items(html):
            if not result["title"]:
                result["title"] = cls._normal_text(str(item.get("headline") or item.get("name") or ""))
            if not result["byline"]:
                author = item.get("author")
                if isinstance(author, dict):
                    result["byline"] = cls._normal_text(str(author.get("name") or ""))
                elif isinstance(author, list):
                    names = [
                        cls._normal_text(str(value.get("name") or ""))
                        for value in author if isinstance(value, dict)
                    ]
                    result["byline"] = "、".join(name for name in names if name)
                elif isinstance(author, str):
                    result["byline"] = cls._normal_text(author)
            if not result["issue_label"]:
                serialized = json.dumps(item, ensure_ascii=False)
                match = re.search(r"《求是》\d{4}/\d{1,2}", serialized)
                if match:
                    result["issue_label"] = match.group(0)
        return result

    # ---- catalogs and issue contents --------------------------------------

    def _parse_catalog(self, html, url: str) -> IssueCatalog | None:
        found: dict[tuple[int, int], CatalogIssue] = {}
        for anchor in html.xpath("//a[@href]"):
            issue_id = self._issue_id_from_text(self._normal_text(anchor.xpath("string(.)")))
            if issue_id is None:
                continue
            source_url = urljoin(url, anchor.get("href", "").strip())
            key = (issue_id["publication_year"], issue_id["issue_number"])
            found[key] = {"id": issue_id, "source_url": source_url}
        headings = [
            self._normal_text(element.xpath("string(.)"))
            for element in html.xpath("//h1 | //title")
        ]
        explicit_catalog = (
            "mulu" in url.lower()
            or any(
                re.fullmatch(r"《?求是》?\s*\d{4}\s*年", heading)
                or "年度目录" in heading
                or "全年目录" in heading
                for heading in headings
            )
        )
        if not explicit_catalog:
            return None
        issues = [found[key] for key in sorted(found)]
        catalog: IssueCatalog = {"source_url": url, "issues": issues}
        years = {item["id"]["publication_year"] for item in issues}
        if len(years) == 1:
            catalog["publication_year"] = next(iter(years))
        return catalog

    @classmethod
    def _looks_like_column_heading(cls, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text)
        return bool(_COLUMN_TEXT_RE.match(normalized)) and not any(
            word in normalized for word in _COLUMN_BLACKLIST
        )

    def _parse_issue(self, html, url: str) -> Issue | None:
        identity_elements = html.xpath(
            "//h1 | //span[contains(concat(' ', normalize-space(@class), ' '), ' appellation ')]"
        )
        issue_id = None
        for element in identity_elements:
            issue_id = self._issue_id_from_text(
                self._normal_text(element.xpath("string(.)"))
            )
            if issue_id is not None:
                break
        if issue_id is None:
            return None
        containers = html.xpath('//div[contains(@class,"content")]')
        if not containers:
            return None

        entries: list[IssueEntry] = []
        problems: list[ReconstructionProblem] = []
        current_label = ""
        for block in self._content_blocks(containers[0], issue_mode=True):
            anchors = [anchor for anchor in block.xpath(".//a[@href]") if "/c.html" in anchor.get("href", "")]
            if not anchors:
                text = self._normal_text(block.xpath("string(.)"))
                if text and self._looks_like_column_heading(text):
                    current_label = text
                continue

            block_text = self._normal_text(block.xpath("string(.)"))
            if not block_text and block.xpath(".//img"):
                # Image-only links at the end of issue pages lead to archive
                # catalogs; official issue entries are textual rows.
                continue
            anchor = anchors[0]
            source_url = urljoin(url, anchor.get("href", "").strip())
            if source_url == url:
                continue
            source_id = self._source_id(source_url)
            title_values = block.xpath(".//strong//text()")
            directory_title = self._normal_text(" ".join(title_values))
            if not directory_title:
                directory_title = self._normal_text(anchor.xpath("string(.)"))
            inline_label = ""
            if "│" in directory_title:
                inline_label, directory_title = (
                    part.strip() for part in directory_title.split("│", 1)
                )
            if not inline_label:
                for span in anchor.xpath('.//span[contains(@style,"楷体") or contains(@style,"KaiTi")]'):
                    span_text = self._normal_text(span.xpath("string(.)"))
                    if (span.tail or "").lstrip().startswith("│") and span_text:
                        inline_label = span_text
                        break
                    match = re.fullmatch(r"[（(]([^（）()]{2,8})[）)]", span_text)
                    if match:
                        inline_label = match.group(1)
                        if directory_title.endswith(span_text):
                            directory_title = directory_title[:-len(span_text)].rstrip()
                        break
            full_text = self._normal_text(block.xpath("string(.)"))
            directory_subtitle = ""
            for extra_anchor in anchors[1:]:
                extra_text = self._normal_text(extra_anchor.xpath("string(.)"))
                if extra_text and extra_text != directory_title:
                    directory_subtitle = extra_text
                    break
            if not directory_subtitle:
                subtitle_match = re.search(r"(——[^/]+?)(?:\s*/|$)", full_text)
                if subtitle_match:
                    directory_subtitle = subtitle_match.group(1).strip()
            byline = ""
            slash = full_text.rfind("/")
            if slash >= 0:
                byline = full_text[slash + 1:].strip()
            entry: IssueEntry = {
                "ordinal": len(entries) + 1,
                "source_article_id": source_id,
                "source_url": source_url,
            }
            if directory_title:
                entry["directory_title"] = directory_title
            if directory_subtitle:
                entry["directory_subtitle"] = directory_subtitle
            if byline:
                entry["directory_byline"] = byline
            if inline_label or current_label:
                entry["section_label"] = inline_label or current_label
            current_label = ""
            if not source_id:
                problems.append({
                    "code": "missing_entry_article_id",
                    "message": "官方目录条目没有可识别的来源文章标识",
                    "location": f"entries[{entry['ordinal']}]",
                })
            entries.append(entry)

        heading_text = self._normal_text(" ".join(
            heading.xpath("string(.)") for heading in html.xpath("//h1")
        ))
        heading_issue_id = self._issue_id_from_text(heading_text)
        heading_declares_issue = bool(
            heading_issue_id
            and "求是" in heading_text
            and (
                "目录" in heading_text
                or re.fullmatch(
                    r"《?求是》?\s*\d{4}\s*年第\s*\d{1,2}\s*期",
                    heading_text,
                )
            )
        )
        has_visible_heading = bool(html.xpath("//h1"))
        if (
            (has_visible_heading and not heading_declares_issue)
            or (not has_visible_heading and len(entries) < 2)
        ):
            return None
        if not entries:
            problems.append({
                "code": "missing_issue_entries",
                "message": "官方期次目录中没有取得任何入刊条目",
            })
        issue: Issue = {
            "id": issue_id,
            "source_url": url,
            "entries": entries,
            "reconstruction": reconstruction_status(problems),
        }
        declared_date = self._declared_issue_date(html)
        if declared_date:
            issue["publication_date"] = declared_date
        return issue

    # ---- article extraction ------------------------------------------------

    def _parse_article(self, html, url: str, *, with_qr: bool) -> Article:
        canonical_url = self._canonical_url(html, url)
        json_ld = self._json_ld_metadata(html)
        headings = html.xpath("//h1")
        visible_title = self._normal_text(headings[0].xpath("string(.)")) if headings else ""
        fallback_titles = [
            *html.xpath('//meta[@property="og:title"]/@content'),
            *html.xpath('//meta[@name="title"]/@content'),
            json_ld["title"],
        ]
        title = visible_title or next(
            (self._normal_text(value) for value in fallback_titles if self._normal_text(value)),
            "",
        )

        issue_label = ""
        byline_parts: list[str] = []
        for element in html.xpath('//span[contains(concat(" ", normalize-space(@class), " "), " appellation ")]'):
            text = self._normal_text(element.xpath("string(.)"))
            if text.startswith("来源") and "求是" in text and not issue_label:
                match = re.search(r"《求是》\d{4}/\d{1,2}", text)
                issue_label = match.group(0) if match else text.removeprefix("来源：").removeprefix("来源")
            elif text.startswith("作者"):
                value = re.sub(r"^作者[：:]?", "", text).strip()
                if value:
                    byline_parts.append(value)
        byline = "、".join(byline_parts)
        if not byline:
            byline_values = [
                *html.xpath('//meta[@name="author"]/@content'),
                *html.xpath('//meta[@property="article:author"]/@content'),
                json_ld["byline"],
            ]
            byline = next(
                (self._normal_text(value) for value in byline_values if self._normal_text(value)),
                "",
            )
        if not issue_label:
            descriptions = [
                *html.xpath('//meta[@name="description"]/@content'),
                *html.xpath('//meta[@property="og:description"]/@content'),
                json_ld["issue_label"],
            ]
            for description in descriptions:
                match = re.search(r"《求是》\d{4}/\d{1,2}", description)
                if match:
                    issue_label = match.group(0)
                    break

        article: Article = {
            "source_id": self._source_id(canonical_url) or self._source_id(url),
            "source_url": canonical_url,
            "title": title,
            "body": [],
            "reconstruction": reconstruction_status(),
        }
        if byline:
            article["byline"] = byline
        if issue_label:
            article["issue_label"] = issue_label
        declared_date = self._declared_date(html)
        if declared_date:
            article["source_publication_date"] = declared_date

        containers = html.xpath('//div[contains(@class,"content")]')
        problems: list[ReconstructionProblem] = []
        if containers:
            candidates = list(self._content_blocks(containers[0], issue_mode=False))
            article["body"] = self._extract_body(
                candidates,
                canonical_url,
                title=title,
                byline=byline,
                issue_label=issue_label,
                article=article,
                problems=problems,
            )
        else:
            problems.append({"code": "missing_content_container", "message": "没有找到正文容器"})
        article["reconstruction"] = reconstruction_status(problems)
        article["reconstruction"] = validate_article(article)
        if with_qr:
            try:
                article["qrcode"] = self._gen_qr(canonical_url)
            except OSError:
                # QR codes are optional rendition resources, not source body.
                pass
        return article

    def _content_blocks(self, container, *, issue_mode: bool) -> Iterator:
        def walk(node) -> Iterator:
            for child in node:
                tag = str(child.tag).lower() if isinstance(child.tag, str) else ""
                if issue_mode and tag in {"ul", "ol"}:
                    for list_item in child.xpath("./li"):
                        yield list_item
                elif tag in _SUPPORTED_BODY_TAGS or (not issue_mode and tag == "img") or (issue_mode and tag in {"li", "h1"}):
                    yield child
                elif tag in {"script", "style", "noscript", "template"}:
                    continue
                elif tag in _WRAPPER_TAGS:
                    yielded = False
                    for descendant in walk(child):
                        yielded = True
                        yield descendant
                    if not yielded and self._normal_text(child.xpath("string(.)")):
                        yield child
                elif (
                    self._normal_text(child.xpath("string(.)"))
                    or child.xpath(".//img")
                    or tag in _UNSUPPORTED_SUBSTANTIVE_TAGS
                ):
                    yield child
        yield from walk(container)

    @staticmethod
    def _formatting(element) -> tuple[str, str, int, bool]:
        style = (element.get("style") or "").lower()
        normalized = re.sub(r"\s+", "", style)
        if "text-align:right" in normalized:
            alignment = "right"
        elif "text-align:center" in normalized:
            alignment = "center"
        elif "text-align:left" in normalized or "text-indent:0" in normalized:
            alignment = "left"
        else:
            alignment = "default"
        family = ""
        for descendant in [element, *element.xpath(".//*")]:
            value = (descendant.get("style") or "").lower()
            if "楷体" in value or "kaiti" in value:
                family = "kai"
                break
            if "黑体" in value or "heiti" in value or "simhei" in value:
                family = "hei"
                break
            if "仿宋" in value or "fangsong" in value:
                family = "fang"
                break
            if "宋体" in value or "simsun" in value:
                family = "song"
                break
        size_match = re.search(r"font-size:\s*(\d+)px", style)
        font_size = int(size_match.group(1)) if size_match else 0
        full_text = QiuShiCrawler._normal_text(element.xpath("string(.)"))
        strong_text = QiuShiCrawler._normal_text("".join(element.xpath(".//strong//text()")))
        return alignment, family, font_size, bool(strong_text and strong_text == full_text)

    def _inline_runs(self, element, base_url: str) -> list[InlineRun]:
        runs: list[InlineRun] = []

        def append(text: str | None, strong: bool, emphasis: bool, href: str) -> None:
            if not text:
                return
            normalized = re.sub(r"\s+", " ", text)
            if not normalized:
                return
            run: InlineRun = {"text": normalized, "strong": strong, "emphasis": emphasis}
            if href:
                run["href"] = href
            if runs and all(runs[-1].get(key) == run.get(key) for key in ("strong", "emphasis", "href")):
                runs[-1]["text"] = runs[-1].get("text", "") + normalized
            else:
                runs.append(run)

        def walk(node, strong: bool, emphasis: bool, href: str) -> None:
            append(node.text, strong, emphasis, href)
            for child in node:
                tag = str(child.tag).lower() if isinstance(child.tag, str) else ""
                style = re.sub(r"\s+", "", (child.get("style") or "").lower())
                child_strong = strong or tag in {"strong", "b"} or bool(
                    re.search(r"font-weight:(?:bold|[6-9]00)", style)
                )
                child_emphasis = (
                    emphasis
                    or tag in {"em", "i"}
                    or "font-style:italic" in style
                    or "font-style:oblique" in style
                )
                child_href = href
                if tag == "a":
                    raw_href = (child.get("href") or "").strip()
                    if raw_href and not raw_href.startswith(("javascript:", "#")):
                        child_href = urljoin(base_url, raw_href)
                if tag != "img":
                    walk(child, child_strong, child_emphasis, child_href)
                append(child.tail, strong, emphasis, href)

        root_tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        root_style = re.sub(r"\s+", "", (element.get("style") or "").lower())
        root_strong = root_tag in {"strong", "b"} or bool(
            re.search(r"font-weight:(?:bold|[6-9]00)", root_style)
        )
        root_emphasis = (
            root_tag in {"em", "i"}
            or "font-style:italic" in root_style
            or "font-style:oblique" in root_style
        )
        walk(element, root_strong, root_emphasis, "")
        while runs and not runs[0].get("text", "").strip():
            runs.pop(0)
        while runs and not runs[-1].get("text", "").strip():
            runs.pop()
        if runs:
            runs[0]["text"] = runs[0].get("text", "").lstrip()
            runs[-1]["text"] = runs[-1].get("text", "").rstrip()
        return [run for run in runs if run.get("text")]

    @staticmethod
    def _runs_text(runs: list[InlineRun]) -> str:
        return "".join(run.get("text", "") for run in runs).strip()

    def _paragraph(
        self,
        element,
        base_url: str,
        *,
        first_text: bool,
        byline: str,
    ) -> ParagraphBlock | None:
        runs = self._inline_runs(element, base_url)
        text = self._runs_text(runs)
        if not text:
            return None
        alignment, family, size, _visual_bold = self._formatting(element)
        textual_runs = [run for run in runs if run.get("text", "").strip()]
        fully_strong = bool(textual_runs) and all(
            run.get("strong", False) for run in textual_runs
        )
        tag = str(element.tag).lower()
        role: TextRole = "body"
        if first_text and re.fullmatch(r"[^：:，。；]{1,10}[：:]", text):
            role = "salutation"
            alignment = "left"
        elif (
            byline
            and re.sub(r"\s+", "", text).endswith(re.sub(r"\s+", "", byline))
            and len(text) <= 40
        ):
            role = "signature"
            alignment = "right"
        elif (
            tag in {"h2", "h3", "h4", "h5", "h6"}
            or (alignment == "center" and re.fullmatch(r"[一二三四五六七八九十百]+", text))
            or (
                fully_strong
                and len(text) <= 80
                and re.match(r"^(?:[一二三四五六七八九十百]+[、．.]|第.+[章节篇部分]|[（(][一二三四五六七八九十百]+[）)]|\d+[、．.])", text)
            )
        ):
            role = "section_heading"
        return {
            "kind": "paragraph",
            "role": role,
            "runs": runs,
            "alignment": alignment,  # type: ignore[typeddict-item]
            "font_family": family,
            "font_size": size,
        }

    def _has_substantive_image(self, element) -> bool:
        element_tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        image_nodes = [element] if element_tag == "img" else element.xpath(".//img")
        for image in image_nodes:
            values = [
                (image.get(attribute) or "").strip()
                for attribute in ("data-original", "data-src", "src")
            ]
            values.extend(
                part.strip().split()[0]
                for part in (image.get("srcset") or "").split(",")
                if part.strip()
            )
            if any(value and not self._is_qr_img(value) for value in values):
                return True
        return False

    def _unmodeled_nested_reason(self, element, container_kind: str) -> str:
        if self._has_substantive_image(element):
            return "容器内图像尚不能在原位置保真重建"

        disallowed = set(_UNSUPPORTED_SUBSTANTIVE_TAGS)
        disallowed.update({"figure", "picture"})
        if container_kind == "list":
            disallowed.update({"ul", "ol", "table", "blockquote"})
            for item in element.xpath(".//li"):
                if len(item.xpath("./p")) > 1:
                    return "多段列表项尚不能保真重建"
        elif container_kind == "table":
            disallowed.update({"ul", "ol", "table", "blockquote"})
        elif container_kind == "quote":
            disallowed.update({"ul", "ol", "table", "blockquote"})

        for descendant in element.xpath(".//*"):
            if not isinstance(descendant.tag, str):
                continue
            tag = str(descendant.tag).lower()
            if tag in disallowed:
                return f"{container_kind} 内嵌 {tag} 尚不能保真重建"
        return ""

    def _figure(
        self,
        element,
        base_url: str,
        problems: list[ReconstructionProblem],
        location: str,
    ) -> FigureBlock | None:
        images: list[FigureImage] = []
        element_tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
        image_nodes = [element] if element_tag == "img" else element.xpath(".//img")
        for image in image_nodes:
            raw_src = ""
            weighted_sources: list[tuple[float, str]] = []
            for item in (image.get("srcset") or "").split(","):
                parts = item.strip().split()
                if not parts:
                    continue
                descriptor = parts[1] if len(parts) > 1 else "1x"
                match = re.match(r"(\d+(?:\.\d+)?)(?:w|x)?$", descriptor)
                weighted_sources.append(
                    (float(match.group(1)) if match else 0.0, parts[0])
                )
            if weighted_sources:
                raw_src = max(weighted_sources)[1]
            if not raw_src:
                raw_src = next(
                    (
                        (image.get(attribute) or "").strip()
                        for attribute in ("data-original", "data-src", "src")
                        if (image.get(attribute) or "").strip()
                    ),
                    "",
                )
            if not raw_src or self._is_qr_img(raw_src):
                continue
            try:
                local = self._download_img(urljoin(base_url, raw_src))
            except (requests.RequestException, OSError) as error:
                problems.append({
                    "code": "image_download_failed",
                    "message": f"正文图像下载失败: {error}",
                    "location": location,
                })
                images.append({
                    "src": "",
                    "source_url": urljoin(base_url, raw_src),
                    "alt": self._normal_text(image.get("alt", "")),
                    "missing": True,
                })
                continue
            images.append({
                "src": local,
                "source_url": urljoin(base_url, raw_src),
                "alt": self._normal_text(image.get("alt", "")),
                "missing": False,
            })
        caption_nodes = element.xpath(".//figcaption")
        caption = self._inline_runs(caption_nodes[0], base_url) if caption_nodes else []
        if not caption:
            caption = self._inline_runs(element, base_url)
        if not images:
            return None
        return {"kind": "figure", "images": images, "caption": caption}

    def _extract_body(
        self,
        candidates: list,
        base_url: str,
        *,
        title: str,
        byline: str,
        issue_label: str,
        article: Article,
        problems: list[ReconstructionProblem],
    ) -> list[BodyElement]:
        body: list[BodyElement] = []
        skip_values = {value for value in (title, byline, issue_label) if value}
        first_text = True
        index = 0
        while index < len(candidates):
            element = candidates[index]
            tag = str(element.tag).lower() if isinstance(element.tag, str) else ""
            location = f"body-source[{index + 1}]"
            text = self._normal_text(element.xpath("string(.)"))
            css_class = (element.get("class") or "").lower()

            if (
                "扫描二维码分享到手机" in text
                or text.startswith("网站编辑")
                or "fs-text" in css_class
                or css_class in {"weibo", "qzone"}
                or text == "【网站声明】"
            ):
                break
            if index < 8 and (
                text in skip_values
                or text.rstrip("※*") in skip_values
                or "appellation" in css_class
                or "pubtime" in css_class
                or (tag in {"h1", "h2"} and not text)
            ):
                index += 1
                continue
            if index < 8 and text.startswith("——") and tag == "p":
                article["subtitle"] = text
                index += 1
                continue

            if tag in {"p", "figure", "picture", "img"} and (tag == "img" or element.xpath(".//img")):
                figure = self._figure(element, base_url, problems, location)
                if figure is not None:
                    if not figure["caption"] and index + 1 < len(candidates):
                        next_element = candidates[index + 1]
                        next_tag = str(next_element.tag).lower() if isinstance(next_element.tag, str) else ""
                        _alignment, family, _size, _bold = self._formatting(next_element)
                        if next_tag == "p" and family in {"fang", "kai"} and not next_element.xpath(".//img"):
                            figure["caption"] = self._inline_runs(next_element, base_url)
                            index += 1
                    body.append(figure)
                elif self._has_substantive_image(element):
                    body.append({
                        "kind": "unsupported",
                        "source_tag": tag,
                        "reason": "图版未能取得任何正文图像",
                    })
                index += 1
                continue

            if tag in {"p", "h2", "h3", "h4", "h5", "h6"}:
                paragraph = self._paragraph(element, base_url, first_text=first_text, byline=byline)
                if paragraph is not None:
                    body.append(paragraph)
                    first_text = False
                elif any(
                    str(descendant.tag).lower() in _UNSUPPORTED_SUBSTANTIVE_TAGS
                    for descendant in element.xpath(".//*")
                    if isinstance(descendant.tag, str)
                ):
                    body.append({
                        "kind": "unsupported",
                        "source_tag": tag,
                        "reason": "段落包含尚不能保真重建的嵌入正文",
                    })
            elif tag in {"ul", "ol"}:
                items = [self._inline_runs(item, base_url) for item in element.xpath("./li")]
                items = [item for item in items if self._runs_text(item)]
                if items:
                    body.append({"kind": "list", "ordered": tag == "ol", "items": items})
                reason = self._unmodeled_nested_reason(element, "list")
                if reason:
                    body.append({
                        "kind": "unsupported",
                        "source_tag": tag,
                        "reason": reason,
                    })
            elif tag == "table":
                rows: list[list[TableCell]] = []
                for row in element.xpath(".//tr"):
                    cells: list[TableCell] = []
                    for cell in row.xpath("./th|./td"):
                        cells.append({
                            "runs": self._inline_runs(cell, base_url),
                            "header": str(cell.tag).lower() == "th",
                            "rowspan": max(1, int(cell.get("rowspan", "1")))
                            if cell.get("rowspan", "1").isdigit() else 1,
                            "colspan": max(1, int(cell.get("colspan", "1")))
                            if cell.get("colspan", "1").isdigit() else 1,
                        })
                    if cells:
                        rows.append(cells)
                if rows:
                    body.append({"kind": "table", "rows": rows})
                reason = self._unmodeled_nested_reason(element, "table")
                if reason:
                    body.append({
                        "kind": "unsupported",
                        "source_tag": tag,
                        "reason": reason,
                    })
            elif tag == "blockquote":
                paragraph_elements = element.xpath(".//p")
                paragraphs = [
                    self._inline_runs(paragraph, base_url)
                    for paragraph in paragraph_elements
                ]
                paragraphs = [
                    paragraph for paragraph in paragraphs
                    if self._runs_text(paragraph)
                ]
                if not paragraphs:
                    runs = self._inline_runs(element, base_url)
                    if runs:
                        paragraphs = [runs]
                if paragraphs:
                    body.append({"kind": "quote", "paragraphs": paragraphs})
                reason = self._unmodeled_nested_reason(element, "quote")
                if reason:
                    body.append({
                        "kind": "unsupported",
                        "source_tag": tag,
                        "reason": reason,
                    })
            else:
                body.append({
                    "kind": "unsupported",
                    "source_tag": tag or "unknown",
                    "reason": f"尚不能保真重建正文结构 <{tag or 'unknown'}>",
                })
            index += 1
        return body

    # ---- QR presentation resource -----------------------------------------

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
        image = qr.make_image(fill_color="black", back_color="white")
        filename = "qrcode.png"
        image.save(os.path.join(self.image_dir, filename))
        return filename
