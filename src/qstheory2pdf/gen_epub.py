"""Render domain reconstructions as reflowable EPUB 3."""

from __future__ import annotations

import html
import mimetypes
import os
import re
import uuid
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

from ebooklib import epub
from PIL import Image, ImageOps

from qstheory2pdf.domain import problem_summary, reconstruction_status
from qstheory2pdf.gen_pdf import _safe_name
from qstheory2pdf.types import (
    Article,
    BodyElement,
    FigureBlock,
    InlineRun,
    Issue,
    ReconstructionStatus,
)

_EPUB_COVER_MAX_WIDTH = 1600
_EPUB_COVER_QUALITY = 82

_BOOK_CSS = """
html { color: #111; background: #fff; }
body { font-family: "Noto Serif CJK SC", "Source Han Serif SC", SimSun, serif;
  line-height: 1.65; margin: 0; padding: 0 0.5em; text-align: justify; }
h1, h2 { font-family: "Noto Sans CJK SC", "Source Han Sans CJK SC", sans-serif;
  line-height: 1.35; break-after: avoid; page-break-after: avoid; }
h1 { font-size: 1.55em; text-align: center; margin: 1em 0 0.55em; }
h2 { font-size: 1.15em; margin: 1.25em 0 0.45em; }
p { margin: 0.25em 0; text-indent: 2em; }
.subtitle, .byline, .issue-label { text-align: center; text-indent: 0; }
.subtitle, .issue-label, figcaption { color: #444; font-family: "LXGW WenKai", KaiTi, cursive; }
.byline { color: #444; font-family: FangSong, STFangsong, serif; }
.left, .right, .center, .salutation, .signature { text-indent: 0; }
.left, .salutation { text-align: left; } .right, .signature { text-align: right; }
.center { text-align: center; }
figure { break-inside: avoid; margin: 1em 0; page-break-inside: avoid; text-align: center; }
figure img { display: block; height: auto; margin: 0.35em auto; max-width: 100%; }
figcaption { font-size: 0.82em; line-height: 1.45; text-align: justify; }
blockquote { border-left: 0.2em solid #999; margin: 0.8em 1em; padding-left: 0.8em; }
table { border-collapse: collapse; margin: 1em auto; max-width: 100%; }
th, td { border: 1px solid #777; padding: 0.3em; vertical-align: top; }
.partial-notice, .missing-content { border: 0.18em solid #b00020; color: #8b0018;
  font-family: "Noto Sans CJK SC", sans-serif; font-weight: bold; padding: 0.8em;
  text-align: center; text-indent: 0; }
""".strip()

_COVER_CSS = """
html, body { height: 100%; margin: 0; padding: 0; }
.cover { height: 100%; margin: 0; padding: 0; text-align: center; }
.cover svg, .cover img { display: block; height: 100%; margin: 0 auto;
  max-height: 100vh; max-width: 100%; width: 100%; }
""".strip()


def _issue_label(issue: Issue) -> str:
    issue_id = issue.get("id", {})
    year = issue_id.get("publication_year", 0)
    number = issue_id.get("issue_number", 0)
    return f"《求是》{year}/{number:02d}" if year and number else "《求是》"


def _render_runs_html(runs: list[InlineRun]) -> str:
    parts: list[str] = []
    for run in runs:
        rendered = html.escape(run.get("text", ""))
        if run.get("emphasis"):
            rendered = f"<em>{rendered}</em>"
        if run.get("strong"):
            rendered = f"<strong>{rendered}</strong>"
        href = run.get("href", "")
        if href:
            rendered = f'<a href="{html.escape(href, quote=True)}">{rendered}</a>'
        parts.append(rendered)
    return "".join(parts)


class EPUBGenerator:
    def __init__(self, image_dir: str) -> None:
        self.image_dir = Path(image_dir)
        self._book: epub.EpubBook | None = None
        self._image_hrefs: dict[str, str] = {}
        self._image_index = 0

    def gen_single(
        self,
        article: Article,
        output_path: str | None = None,
        status: ReconstructionStatus | None = None,
        *,
        allow_partial: bool = False,
    ) -> str:
        status = status or article.get("reconstruction") or reconstruction_status()
        if status["state"] == "partial" and not allow_partial:
            raise ValueError("部分文章重建必须显式设置 allow_partial=True")
        title = article.get("title", "") or article.get("source_id", "求是文章")
        creators = [article["byline"]] if article.get("byline") else []
        source_id = article.get("source_id", "")
        identifier = (
            f"qstheory:article:{source_id}"
            if source_id
            else f"qstheory:partial-artifact:{uuid.uuid4()}"
        )
        book = self._new_book(
            title=title,
            identifier=identifier,
            creators=creators,
            publication_date=article.get("source_publication_date", ""),
            source_url=article.get("source_url", ""),
            description=title,
        )
        chapter = self._build_chapter(article, 1, status=status, show_issue=True)
        book.add_item(chapter)
        book.toc = [chapter]
        book.spine = [chapter]
        output = output_path or self._default_output(title, status)
        return self._write(book, output)

    def gen_issue(
        self,
        issue: Issue,
        articles: Mapping[str, Article],
        *,
        cover_image: str | None = None,
        output_path: str | None = None,
        status: ReconstructionStatus | None = None,
        allow_partial: bool = False,
    ) -> str:
        if not issue.get("entries"):
            raise ValueError("生成整期 EPUB 至少需要一个入刊条目")
        status = status or issue.get("reconstruction") or reconstruction_status()
        if status["state"] == "partial" and not allow_partial:
            raise ValueError("部分期次重建必须显式设置 allow_partial=True")
        label = _issue_label(issue)
        issue_id = issue.get("id", {})
        if issue_id.get("publication_year") and issue_id.get("issue_number"):
            identifier = (
                f"qstheory:issue:{issue_id['publication_year']}:{issue_id['issue_number']}"
            )
        else:
            identifier = f"qstheory:partial-artifact:{uuid.uuid4()}"
        book = self._new_book(
            title=label,
            identifier=identifier,
            creators=[],
            publication_date=issue.get("publication_date", ""),
            source_url=issue.get("source_url", ""),
            description=f"{label}，共 {len(issue.get('entries', []))} 个入刊条目。",
        )

        spine: list[object] = []
        if cover_image:
            cover = self._build_cover_page(cover_image, label)
            book.add_item(cover)
            spine.append(cover)
        spine.append("nav")

        chapter_by_id: dict[str, epub.EpubHtml] = {}
        chapter_by_ordinal: dict[int, epub.EpubHtml] = {}
        chapter_index = 0
        for entry in issue.get("entries", []):
            source_id = entry.get("source_article_id", "")
            ordinal = entry.get("ordinal", len(chapter_by_ordinal) + 1)
            chapter = chapter_by_id.get(source_id)
            if chapter is None and source_id in articles:
                chapter_index += 1
                chapter = self._build_chapter(
                    articles[source_id],
                    chapter_index,
                    status=status if chapter_index == 1 else reconstruction_status(),
                    show_issue=False,
                )
                chapter_by_id[source_id] = chapter
                book.add_item(chapter)
                spine.append(chapter)
            elif chapter is None:
                chapter_index += 1
                chapter = self._build_missing_chapter(
                    entry,
                    chapter_index,
                    status if chapter_index == 1 else reconstruction_status(),
                )
                book.add_item(chapter)
                spine.append(chapter)
            chapter_by_ordinal[ordinal] = chapter

        toc: list[object] = []
        for entry in issue.get("entries", []):
            source_id = entry.get("source_article_id", "")
            ordinal = entry.get("ordinal", len(toc) + 1)
            chapter = chapter_by_ordinal[ordinal]
            article = articles.get(source_id, {})
            directory_title = entry.get("directory_title", "")
            fallback_title = article.get("title", "")
            title = directory_title or (
                fallback_title + "（文章页题）" if fallback_title else "未取得的入刊文章"
            )
            subtitle = entry.get("directory_subtitle", "")
            if subtitle:
                title = f"{title} {subtitle}"
            section = entry.get("section_label", "")
            label_text = f"{section}｜{title}" if section else title
            if source_id not in articles:
                label_text += " [缺失]"
            toc.append(
                epub.Link(
                    chapter.file_name,
                    label_text,
                    f"entry_{ordinal}",
                )
            )
        book.toc = toc
        book.spine = spine
        output = output_path or self._default_output(label, status)
        return self._write(book, output)

    def _new_book(
        self,
        *,
        title: str,
        identifier: str,
        creators: list[str],
        publication_date: str,
        source_url: str,
        description: str,
    ) -> epub.EpubBook:
        book = epub.EpubBook()
        stable_identifier = uuid.uuid5(uuid.NAMESPACE_URL, identifier)
        book.set_identifier(f"urn:uuid:{stable_identifier}")
        book.set_title(title)
        book.set_language("zh-CN")
        for creator in creators:
            book.add_author(creator)
        if publication_date:
            book.add_metadata("DC", "date", publication_date)
        if source_url:
            book.add_metadata("DC", "source", source_url)
        book.add_metadata("DC", "subject", "求是")
        book.add_metadata("DC", "description", description)
        book.add_item(
            epub.EpubItem(
                uid="style_book",
                file_name="styles/book.css",
                media_type="text/css",
                content=_BOOK_CSS.encode("utf-8"),
            )
        )
        book.add_item(
            epub.EpubItem(
                uid="style_cover",
                file_name="styles/cover.css",
                media_type="text/css",
                content=_COVER_CSS.encode("utf-8"),
            )
        )
        book.add_item(epub.EpubNcx())
        nav = epub.EpubNav(title="目录")
        nav.add_link(href="styles/book.css", rel="stylesheet", type="text/css")
        book.add_item(nav)
        self._book = book
        self._image_hrefs = {}
        self._image_index = 0
        return book

    @staticmethod
    def _partial_html(status: ReconstructionStatus) -> str:
        if status["state"] != "partial":
            return ""
        return f'<aside class="partial-notice">部分重建：{html.escape(problem_summary(status))}</aside>'

    def _build_missing_chapter(
        self,
        entry,
        index: int,
        status: ReconstructionStatus,
    ) -> epub.EpubHtml:
        title = entry.get("directory_title", "") or "未取得的入刊文章"
        chapter = epub.EpubHtml(
            uid=f"article_{index}",
            file_name=f"text/article_{index:03d}.xhtml",
            title=title,
            lang="zh-CN",
        )
        chapter.add_link(href="../styles/book.css", rel="stylesheet", type="text/css")
        notice = self._partial_html(status)
        chapter.content = (
            '<article epub:type="chapter">'
            + notice
            + f"<h1>{html.escape(title)}</h1>"
            + '<aside class="missing-content">此入刊条目的文章未能取得</aside>'
            + "</article>"
        )
        return chapter

    def _build_chapter(
        self,
        article: Article,
        index: int,
        *,
        status: ReconstructionStatus,
        show_issue: bool,
    ) -> epub.EpubHtml:
        title = article.get("title", "") or article.get("source_id", f"第 {index} 篇")
        chapter = epub.EpubHtml(
            uid=f"article_{index}",
            file_name=f"text/article_{index:03d}.xhtml",
            title=title,
            lang="zh-CN",
        )
        chapter.add_link(href="../styles/book.css", rel="stylesheet", type="text/css")
        parts = ['<article epub:type="chapter">', self._partial_html(status), f"<h1>{html.escape(title)}</h1>"]
        if article.get("subtitle"):
            parts.append(f'<p class="subtitle">{html.escape(article["subtitle"])}</p>')
        if article.get("byline"):
            parts.append(f'<p class="byline">{html.escape(article["byline"])}</p>')
        if show_issue and article.get("issue_label"):
            parts.append(f'<p class="issue-label">{html.escape(article["issue_label"])}</p>')

        section_index = 0
        for element in article.get("body", []):
            if element.get("kind") == "paragraph" and element.get("role") == "section_heading":
                section_index += 1
            parts.append(self._render_block(element, section_index=section_index))
        if article.get("qrcode"):
            href = self._add_image(article["qrcode"])
            parts.append(
                '<figure class="qrcode">'
                f'<img src="../{html.escape(href, quote=True)}" alt="原文二维码"/>'
                "<figcaption>原文二维码</figcaption></figure>"
            )
        parts.append("</article>")
        chapter.content = "\n".join(part for part in parts if part)
        return chapter

    def _render_block(self, element: BodyElement, *, section_index: int) -> str:
        kind = element.get("kind")
        if kind == "paragraph":
            content = _render_runs_html(element.get("runs", []))
            role = element.get("role", "body")
            if role == "section_heading":
                return f'<h2 id="section-{section_index:03d}">{content}</h2>'
            classes: list[str] = []
            if role in {"salutation", "signature"}:
                classes.append(role)
            alignment = element.get("alignment", "default")
            if alignment != "default":
                classes.append(alignment)
            class_attribute = f' class="{" ".join(classes)}"' if classes else ""
            return f"<p{class_attribute}>{content}</p>"
        if kind == "figure":
            return self._render_figure(element)
        if kind == "list":
            tag = "ol" if element.get("ordered") else "ul"
            items = "".join(f"<li>{_render_runs_html(item)}</li>" for item in element.get("items", []))
            return f"<{tag}>{items}</{tag}>"
        if kind == "table":
            rendered_rows: list[str] = []
            for row in element.get("rows", []):
                cells: list[str] = []
                for cell in row:
                    tag = "th" if cell.get("header") else "td"
                    attributes = ""
                    if cell.get("rowspan", 1) > 1:
                        attributes += f' rowspan="{cell["rowspan"]}"'
                    if cell.get("colspan", 1) > 1:
                        attributes += f' colspan="{cell["colspan"]}"'
                    cells.append(
                        f"<{tag}{attributes}>"
                        + _render_runs_html(cell.get("runs", []))
                        + f"</{tag}>"
                    )
                rendered_rows.append("<tr>" + "".join(cells) + "</tr>")
            return "<table><tbody>" + "".join(rendered_rows) + "</tbody></table>"
        if kind == "quote":
            paragraphs = "".join(
                f"<p>{_render_runs_html(paragraph)}</p>"
                for paragraph in element.get("paragraphs", [])
            )
            return f"<blockquote>{paragraphs}</blockquote>"
        return '<aside class="missing-content">此处正文无法完整重建</aside>'

    def _render_figure(self, figure: FigureBlock) -> str:
        images: list[str] = []
        caption = _render_runs_html(figure.get("caption", []))
        for image in figure.get("images", []):
            alt = image.get("alt", "") or re.sub("<[^>]+>", "", caption) or "文章配图"
            if image.get("missing") or not image.get("src"):
                images.append(
                    '<div class="missing-content">正文图像未能取得'
                    + ("：" + html.escape(alt) if alt else "")
                    + "</div>"
                )
                continue
            href = self._add_image(image.get("src", ""))
            images.append(
                f'<img src="../{html.escape(href, quote=True)}" alt="{html.escape(alt, quote=True)}"/>'
            )
        caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
        return "<figure>" + "".join(images) + caption_html + "</figure>"

    def _add_image(self, relative_path: str) -> str:
        normalized = relative_path.replace("\\", "/")
        if normalized in self._image_hrefs:
            return self._image_hrefs[normalized]
        if self._book is None:
            raise RuntimeError("必须先初始化 EPUB 书籍")
        source = self.image_dir / normalized
        if not source.is_file():
            raise FileNotFoundError(f"EPUB 图片不存在: {source}")
        content, media_type, extension = self._original_image(source)
        href = f"images/image_{self._image_index:04d}{extension}"
        self._image_index += 1
        self._book.add_item(
            epub.EpubImage(
                uid=f"image_{self._image_index}",
                file_name=href,
                media_type=media_type,
                content=content,
            )
        )
        self._image_hrefs[normalized] = href
        return href

    @staticmethod
    def _original_image(source: Path) -> tuple[bytes, str, str]:
        content = source.read_bytes()
        media_type = mimetypes.guess_type(source.name)[0]
        if not media_type or not media_type.startswith("image/"):
            media_type = "image/jpeg"
        extension = mimetypes.guess_extension(media_type) or source.suffix or ".jpg"
        if extension == ".jpe":
            extension = ".jpg"
        return content, media_type, extension.lower()

    def _build_cover_page(self, source: str, title: str) -> epub.EpubHtml:
        href, width, height = self._add_cover_image(source)
        page = epub.EpubHtml(uid="cover_page", file_name="text/cover.xhtml", title="封面", lang="zh-CN")
        page.add_link(href="../styles/cover.css", rel="stylesheet", type="text/css")
        image_alt = html.escape(title, quote=True)
        if width and height:
            if self._book is None:
                raise RuntimeError("必须先初始化 EPUB 书籍")
            svg_href = "images/cover-wrapper.svg"
            svg = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" role="img">'
                f"<title>{html.escape(title)}</title>"
                f'<image href="{html.escape(Path(href).name, quote=True)}" '
                f'xlink:href="{html.escape(Path(href).name, quote=True)}" width="{width}" height="{height}"/>'
                "</svg>"
            )
            self._book.add_item(
                epub.EpubItem(uid="cover_wrapper", file_name=svg_href, media_type="image/svg+xml", content=svg.encode())
            )
            page.content = f'<section class="cover" epub:type="cover"><img src="../{svg_href}" alt="{image_alt}"/></section>'
        else:
            page.content = f'<section class="cover" epub:type="cover"><img src="../{href}" alt="{image_alt}"/></section>'
        return page

    def _add_cover_image(self, relative_path: str) -> tuple[str, int, int]:
        normalized = relative_path.replace("\\", "/")
        if self._book is None:
            raise RuntimeError("必须先初始化 EPUB 书籍")
        source = self.image_dir / normalized
        if not source.is_file():
            raise FileNotFoundError(f"EPUB 图片不存在: {source}")
        content, extension, width, height = self._prepare_cover(source)
        href = f"images/cover{extension}"
        self._book.set_cover(href, content, create_page=False)
        self._image_hrefs[normalized] = href
        return href, width, height

    @classmethod
    def _prepare_cover(cls, source: Path) -> tuple[bytes, str, int, int]:
        original, _media_type, extension = cls._original_image(source)
        try:
            with Image.open(BytesIO(original)) as opened:
                image = ImageOps.exif_transpose(opened)
                image.load()
            if image.width > _EPUB_COVER_MAX_WIDTH:
                height = round(image.height * _EPUB_COVER_MAX_WIDTH / image.width)
                image = image.resize((_EPUB_COVER_MAX_WIDTH, height), Image.Resampling.LANCZOS)
            if "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, "JPEG", quality=_EPUB_COVER_QUALITY, optimize=True)
            return output.getvalue(), ".jpg", image.width, image.height
        except (OSError, ValueError):
            return original, extension, 0, 0

    @staticmethod
    def _default_output(name: str, status: ReconstructionStatus) -> str:
        suffix = "-partial" if status["state"] == "partial" else ""
        return os.path.join(os.getcwd(), "output", _safe_name(name) + suffix + ".epub")

    @staticmethod
    def _write(book: epub.EpubBook, output_path: str) -> str:
        output = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output), exist_ok=True)
        epub.write_epub(output, book, {"epub3_pages": False})
        return output
