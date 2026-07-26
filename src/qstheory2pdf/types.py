"""Typed contracts for qstheory2pdf.

These TypedDicts define the schema that QiuShiCrawler emits and PDFGenerator
consumes. They are the single source of truth for the data flow between the
data-acquisition layer and the presentation layer.
"""

from __future__ import annotations

from typing import List, Literal, TypedDict, Union

# Font family values emitted by QiuShiCrawler._detect_formatting. Empty string
# means "no explicit family; use body default".
FontFamily = Literal["fang", "kai", "hei", "song", ""]


class TextBlock(TypedDict):
    """A paragraph (or sub-paragraph) of article body text."""

    text: str  # raw text, no LaTeX escaping — gen_pdf.py handles that
    bold: bool
    italic: bool
    center: bool
    large: bool  # detected from font-size >= 18px
    right: bool  # right-aligned (e.g. author attribution, letter signature)
    left: bool  # flush left, no first-line indent (e.g. letter salutation 编辑同志：)
    font_family: FontFamily
    font_size: int  # pixels; 0 if not explicitly set


class ImageBlock(TypedDict):
    """An image (figure) embedded in the article body."""

    img: str  # path relative to image_dir, forward slashes
    caption: str  # raw text, no LaTeX escaping


ContentBlock = Union[TextBlock, ImageBlock]


class Article(TypedDict, total=False):
    """A single article from qstheory.cn.

    All fields are optional (total=False) because the crawler may not extract
    every one from a given page; gen_pdf.py must handle missing keys gracefully
    or surface an error.
    """

    title: str
    subtitle: str
    author: str
    volume: str  # e.g. "《求是》2026/08"
    date: str  # e.g. "2026-04-15" — first day of the issue
    content: List[ContentBlock]
    qrcode: str  # path to QR PNG, relative to image_dir; only in single mode


class TocEntry(TypedDict):
    """A single row from a magazine issue's table of contents page."""

    title: str
    column: str  # 栏目, e.g. "本刊特稿"
    subtitle: str
    author: str
    author_role: str  # e.g. "国家发改委副主任"
    url: str


class TocResult(TypedDict):
    """Result of fetching a magazine issue's table of contents page.

    `urls` is the flat list of article URLs (preserves order).
    `entries` carries full metadata for each article; `entries[i].url == urls[i]`
    when both lists are populated. `entries` may be a subset of `urls` if some
    TOC rows lacked metadata (e.g. empty sidebar).
    """

    urls: List[str]
    entries: List[TocEntry]
