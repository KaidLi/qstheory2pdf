"""将文章语义数据生成为适合墨水屏阅读的 EPUB。"""

from __future__ import annotations

import html
import mimetypes
import os
import re
import uuid
from io import BytesIO
from pathlib import Path

from ebooklib import epub
from PIL import Image, ImageOps

from qstheory2pdf.gen_pdf import _safe_name
from qstheory2pdf.types import Article, ContentBlock, ImageBlock, TextBlock, TocEntry

_EPUB_IMAGE_MAX_WIDTH = 800
_EPUB_IMAGE_QUALITY = 75
_EPUB_COVER_MAX_WIDTH = 1600
_EPUB_COVER_QUALITY = 82

_BOOK_CSS = """
html {
  color: #111;
  background: #fff;
}
body {
  font-family: "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC",
    SimSun, serif;
  line-height: 1.65;
  margin: 0;
  padding: 0 0.5em;
  text-align: justify;
}
h1, h2 {
  font-family: "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  text-align: center;
  line-height: 1.35;
  break-after: avoid;
  page-break-after: avoid;
}
h1 {
  font-size: 1.55em;
  margin: 1em 0 0.55em;
}
h2 {
  font-size: 1.15em;
  line-height: 1.5;
  margin: 1.25em 0 0.45em;
  text-align: left;
  text-indent: 0;
}
p {
  margin: 0.25em 0;
  text-indent: 2em;
}
.subtitle, .author, .volume, .column {
  text-align: center;
  text-indent: 0;
}
.subtitle, .author, .caption, .volume {
  color: #444;
}
.subtitle {
  font-family: "LXGW WenKai", KaiTi, STKaiti, cursive;
  font-size: 1.05em;
}
.author {
  font-family: FangSong, STFangsong, "FangSong GB2312", serif;
  margin: 0.5em 0 1.4em;
}
.volume, figcaption {
  font-family: "LXGW WenKai", KaiTi, STKaiti, cursive;
}
.column {
  font-family: "LXGW WenKai", KaiTi, STKaiti, cursive;
  font-size: 0.9em;
}
.center, .right, .left, .heading {
  text-indent: 0;
}
.center, .heading {
  text-align: center;
}
.right {
  text-align: right;
}
.left {
  text-align: left;
}
.bold, .heading, .hei {
  font-family: "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  font-weight: bold;
}
.italic, .kai {
  font-family: "LXGW WenKai", KaiTi, STKaiti, cursive;
}
.fang {
  font-family: FangSong, STFangsong, "FangSong GB2312", serif;
}
.song {
  font-family: "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC",
    SimSun, serif;
}
.large {
  font-size: 1.15em;
}
figure {
  break-inside: avoid;
  margin: 1em 0;
  page-break-inside: avoid;
  text-align: center;
}
figure img {
  display: block;
  height: auto;
  margin: 0 auto;
  max-width: 100%;
}
figcaption {
  color: #444;
  font-size: 0.82em;
  line-height: 1.45;
  margin: 0.45em 0.5em 0;
  text-align: justify;
  text-indent: 0;
}
""".strip()

_COVER_CSS = """
html, body {
  height: 100%;
  margin: 0;
  padding: 0;
}
.cover {
  height: 100%;
  margin: 0;
  padding: 0;
  text-align: center;
}
.cover svg, .cover img {
  display: block;
  height: 100%;
  margin: 0 auto;
  max-height: 100vh;
  max-width: 100%;
  width: 100%;
}
""".strip()


class EPUBGenerator:
    """使用 EbookLib 生成单篇文章或整期杂志 EPUB。"""

    def __init__(self, image_dir: str) -> None:
        self.image_dir = Path(image_dir)
        self._book: epub.EpubBook | None = None
        self._image_hrefs: dict[str, str] = {}
        self._image_index = 0

    def gen_single(self, info: Article, output_path: str | None = None) -> str:
        """生成单篇文章 EPUB，并返回输出路径。"""
        title = info.get("title", "") or "求是文章"
        volume = info.get("volume", "")
        date = info.get("date", "")
        # 署名允许缺省；不得为缺失的作者虚构责任者。
        author = info.get("author", "")
        description = f"{title}，来源：{volume}。" if volume else title
        book = self._new_book(
            title=title,
            # 身份来自来源文章标识（URL 承载），不来自标题/日期。
            identifier_seed=info.get("url") or title,
            creators=[author] if author else [],
            publication_date=date,
            source_url=info.get("url", ""),
            subjects=["求是"],
            description=description,
        )

        chapter = self._build_chapter(info, 1, column="", show_volume=True)
        book.add_item(chapter)
        book.toc = [chapter]
        book.spine = [chapter]

        output = output_path or self._default_output(title)
        return self._write(book, output)

    def gen_issue(
        self,
        articles: list[Article],
        issue_volume: str,
        issue_date: str = "",
        toc_entries: list[TocEntry] | None = None,
        cover_image: str | None = None,
        output_path: str | None = None,
        source_url: str = "",
    ) -> str:
        """生成整期杂志 EPUB，并返回输出路径。"""
        if not articles:
            raise ValueError("生成整期 EPUB 至少需要一篇文章")

        title = issue_volume or "求是"
        subjects = ["求是"]
        for entry in toc_entries or []:
            column = entry.get("column", "")
            if column and column not in subjects:
                subjects.append(column)
        book = self._new_book(
            title=title,
            # 期次身份为出版年份+期号（issue_volume 承载）；不掺入文章数或日期。
            identifier_seed=issue_volume or title,
            creators=[],
            publication_date=issue_date,
            source_url=source_url,
            subjects=subjects,
            description=f"{title}，收录 {len(articles)} 篇文章。",
        )

        spine: list[object] = []
        toc: list[object] = []
        if cover_image:
            cover = self._build_cover_page(cover_image, title)
            book.add_item(cover)
            spine.append(cover)
        spine.append("nav")

        # 入刊条目按刊内次序与文章一一对应（与 gen_pdf 的 manual TOC 一致），
        # 不用标题匹配身份。
        entries_iter = iter(toc_entries or [])
        for index, article in enumerate(articles, 1):
            entry = next(entries_iter, None) or {}
            column = entry.get("column", "")
            chapter = self._build_chapter(
                article,
                index,
                column=column,
                show_volume=False,
            )
            book.add_item(chapter)
            spine.append(chapter)
            label = article.get("title", "") or f"第 {index} 篇"
            if column:
                label = f"{column}｜{label}"
            toc.append(epub.Link(chapter.file_name, label, chapter.id))

        book.toc = toc
        book.spine = spine
        output = output_path or self._default_output(title)
        return self._write(book, output)

    def _new_book(
        self,
        title: str,
        identifier_seed: str,
        *,
        creators: list[str],
        publication_date: str = "",
        source_url: str = "",
        subjects: list[str] | None = None,
        description: str = "",
    ) -> epub.EpubBook:
        book = epub.EpubBook()
        identifier = uuid.uuid5(uuid.NAMESPACE_URL, identifier_seed)
        book.set_identifier(f"urn:uuid:{identifier}")
        book.set_title(title)
        book.set_language("zh-CN")
        for creator in creators:
            book.add_author(creator)
        if publication_date:
            book.add_metadata("DC", "date", publication_date)
        if source_url:
            book.add_metadata("DC", "source", source_url)
        for subject in subjects or []:
            book.add_metadata("DC", "subject", subject)
        if description:
            book.add_metadata("DC", "description", description)

        style = epub.EpubItem(
            uid="style_book",
            file_name="styles/book.css",
            media_type="text/css",
            content=_BOOK_CSS.encode("utf-8"),
        )
        book.add_item(style)
        cover_style = epub.EpubItem(
            uid="style_cover",
            file_name="styles/cover.css",
            media_type="text/css",
            content=_COVER_CSS.encode("utf-8"),
        )
        book.add_item(cover_style)
        book.add_item(epub.EpubNcx())
        nav = epub.EpubNav(title="目录")
        nav.add_link(href="styles/book.css", rel="stylesheet", type="text/css")
        book.add_item(nav)

        self._book = book
        self._image_hrefs = {}
        self._image_index = 0
        return book

    def _build_cover_page(self, source: str, title: str) -> epub.EpubHtml:
        href, width, height = self._add_cover_image(source)
        page = epub.EpubHtml(
            uid="cover_page",
            file_name="text/cover.xhtml",
            title="封面",
            lang="zh-CN",
        )
        page.add_link(href="../styles/cover.css", rel="stylesheet", type="text/css")
        image_href = html.escape(f"../{href}", quote=True)
        image_alt = html.escape(title, quote=True)
        if width and height:
            if self._book is None:
                raise RuntimeError("必须先初始化 EPUB 书籍")
            svg_href = "images/cover-wrapper.svg"
            svg = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="0 0 {width} {height}" '
                'preserveAspectRatio="xMidYMid meet" role="img">'
                f"<title>{html.escape(title)}</title>"
                f'<image href="{html.escape(Path(href).name, quote=True)}" '
                f'xlink:href="{html.escape(Path(href).name, quote=True)}" '
                f'width="{width}" height="{height}"/>'
                "</svg>"
            )
            self._book.add_item(
                epub.EpubItem(
                    uid="cover_wrapper",
                    file_name=svg_href,
                    media_type="image/svg+xml",
                    content=svg.encode("utf-8"),
                )
            )
            page.content = (
                '<section class="cover" epub:type="cover">'
                f'<img src="../{svg_href}" alt="{image_alt}"/>'
                "</section>"
            )
        else:
            page.content = (
                '<section class="cover" epub:type="cover">'
                f'<img src="{image_href}" alt="{image_alt}"/>'
                "</section>"
            )
        return page

    def _add_cover_image(self, relative_path: str) -> tuple[str, int, int]:
        normalized = relative_path.replace("\\", "/")
        if normalized in self._image_hrefs:
            href = self._image_hrefs[normalized]
            source = self.image_dir / normalized
            try:
                with Image.open(source) as opened:
                    return href, opened.width, opened.height
            except OSError:
                return href, 0, 0
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

    def _build_chapter(
        self,
        article: Article,
        index: int,
        *,
        column: str,
        show_volume: bool,
    ) -> epub.EpubHtml:
        title = article.get("title", "") or f"第 {index} 篇"
        chapter = epub.EpubHtml(
            uid=f"article_{index}",
            file_name=f"text/article_{index:03d}.xhtml",
            title=title,
            lang="zh-CN",
        )
        chapter.add_link(href="../styles/book.css", rel="stylesheet", type="text/css")

        parts = ['<article epub:type="chapter">']
        if column:
            parts.append(f'<p class="column">{html.escape(column)}</p>')
        parts.append(f"<h1>{html.escape(title)}</h1>")
        subtitle = article.get("subtitle", "")
        author = article.get("author", "")
        volume = article.get("volume", "")
        if subtitle:
            parts.append(f'<p class="subtitle">{html.escape(subtitle)}</p>')
        if author:
            parts.append(f'<p class="author">{html.escape(author)}</p>')
        if show_volume and volume:
            parts.append(f'<p class="volume">{html.escape(volume)}</p>')

        section_index = 0
        for block in article.get("content", []):
            heading_id = ""
            if "text" in block and block.get("role") == "section_heading":
                section_index += 1
                heading_id = f"section-{section_index:03d}"
            parts.append(self._render_block(block, heading_id=heading_id))

        qrcode = article.get("qrcode", "")
        if qrcode:
            qr_href = self._add_image(qrcode)
            parts.append(
                '<figure class="qrcode">'
                f'<img src="../{html.escape(qr_href, quote=True)}" alt="原文二维码"/>'
                "<figcaption>原文二维码</figcaption>"
                "</figure>"
            )
        parts.append("</article>")
        chapter.content = "\n".join(parts)
        return chapter

    def _render_block(self, block: ContentBlock, *, heading_id: str = "") -> str:
        if "img" in block:
            return self._render_image_block(block)
        return self._render_text_block(block, heading_id=heading_id)

    def _render_image_block(self, block: ImageBlock) -> str:
        href = self._add_image(block["img"])
        caption = block.get("caption", "")
        caption_html = (
            f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
        )
        alt = caption or "文章配图"
        return (
            "<figure>"
            f'<img src="../{html.escape(href, quote=True)}" alt="{html.escape(alt, quote=True)}"/>'
            f"{caption_html}</figure>"
        )

    @staticmethod
    def _render_text_block(block: TextBlock, *, heading_id: str = "") -> str:
        classes = []
        if block.get("right"):
            classes.append("right")
        elif block.get("center"):
            classes.append("center")
        elif block.get("left"):
            classes.append("left")
        if block.get("large"):
            classes.append("large")
        if block.get("bold"):
            classes.append("bold")
        if block.get("italic"):
            classes.append("italic")
        font_family = block.get("font_family", "")
        if font_family:
            classes.append(font_family)
        if block.get("large") and block.get("bold") and block.get("center"):
            classes.append("heading")

        if block.get("role") == "section_heading":
            heading_classes = [
                name for name in classes if name not in ("bold", "large", "heading")
            ]
            class_attr = (
                f' class="{" ".join(heading_classes)}"' if heading_classes else ""
            )
            id_attr = f' id="{html.escape(heading_id, quote=True)}"' if heading_id else ""
            return f"<h2{id_attr}{class_attr}>{html.escape(block['text'])}</h2>"

        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        return f"<p{class_attr}>{html.escape(block['text'])}</p>"

    def _add_image(self, relative_path: str) -> str:
        normalized = relative_path.replace("\\", "/")
        if normalized in self._image_hrefs:
            return self._image_hrefs[normalized]
        if self._book is None:
            raise RuntimeError("必须先初始化 EPUB 书籍")

        source = self.image_dir / normalized
        if not source.is_file():
            raise FileNotFoundError(f"EPUB 图片不存在: {source}")

        content, media_type, extension = self._prepare_content_image(source)
        stem = re.sub(r"[^a-zA-Z0-9_-]", "_", f"image_{self._image_index:04d}")
        href = f"images/{stem}{extension.lower()}"
        self._image_index += 1

        item = epub.EpubImage(
            uid=f"image_{self._image_index}",
            file_name=href,
            media_type=media_type,
            content=content,
        )
        self._book.add_item(item)
        self._image_hrefs[normalized] = href
        return href

    @staticmethod
    def _original_image(source: Path) -> tuple[bytes, str, str]:
        """Return the source bytes and a manifest-safe media type/extension."""
        content = source.read_bytes()
        media_type = mimetypes.guess_type(source.name)[0]
        if not media_type or not media_type.startswith("image/"):
            media_type = "image/jpeg"
        extension = mimetypes.guess_extension(media_type) or source.suffix or ".jpg"
        extension = ".jpg" if extension == ".jpe" else extension
        return content, media_type, extension.lower()

    @classmethod
    def _prepare_content_image(cls, source: Path) -> tuple[bytes, str, str]:
        """Optimize a raster image for EPUB without touching the source file.

        SVG and animated GIF resources are kept intact. Other raster formats
        are resized to the target reading width and encoded as lossy WebP.
        If decoding fails or WebP would be larger, the original resource is
        used as a safe fallback.
        """
        original, media_type, extension = cls._original_image(source)
        if media_type == "image/svg+xml":
            return original, media_type, extension

        try:
            with Image.open(BytesIO(original)) as opened:
                if getattr(opened, "is_animated", False):
                    return original, media_type, extension
                has_alpha = "A" in opened.getbands() or (
                    opened.mode == "P" and "transparency" in opened.info
                )
                image = ImageOps.exif_transpose(opened)
                image.load()

            if image.width > _EPUB_IMAGE_MAX_WIDTH:
                height = round(image.height * _EPUB_IMAGE_MAX_WIDTH / image.width)
                image = image.resize(
                    (_EPUB_IMAGE_MAX_WIDTH, height),
                    Image.Resampling.LANCZOS,
                )
            image = image.convert("RGBA" if has_alpha else "RGB")

            output = BytesIO()
            image.save(
                output,
                "WEBP",
                quality=_EPUB_IMAGE_QUALITY,
                method=6,
            )
            optimized = output.getvalue()
        except (OSError, ValueError):
            return original, media_type, extension

        if len(optimized) >= len(original):
            return original, media_type, extension
        return optimized, "image/webp", ".webp"

    @classmethod
    def _prepare_cover(cls, source: Path) -> tuple[bytes, str, int, int]:
        """Encode the EPUB cover as a broadly compatible RGB JPEG."""
        original, _media_type, extension = cls._original_image(source)
        try:
            with Image.open(BytesIO(original)) as opened:
                image = ImageOps.exif_transpose(opened)
                image.load()

            if image.width > _EPUB_COVER_MAX_WIDTH:
                height = round(image.height * _EPUB_COVER_MAX_WIDTH / image.width)
                image = image.resize(
                    (_EPUB_COVER_MAX_WIDTH, height),
                    Image.Resampling.LANCZOS,
                )
            if "A" in image.getbands() or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            output = BytesIO()
            image.save(
                output,
                "JPEG",
                quality=_EPUB_COVER_QUALITY,
                optimize=True,
            )
            return output.getvalue(), ".jpg", image.width, image.height
        except (OSError, ValueError):
            return original, extension, 0, 0

    @staticmethod
    def _default_output(name: str) -> str:
        output_dir = os.path.join(os.getcwd(), "output")
        return os.path.join(output_dir, _safe_name(name) + ".epub")

    @staticmethod
    def _write(book: epub.EpubBook, output_path: str) -> str:
        output = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output), exist_ok=True)
        epub.write_epub(output, book, {"epub3_pages": False})
        return output
