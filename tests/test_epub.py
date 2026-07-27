"""EPUB 生成与 CLI 输出路径测试。"""

from __future__ import annotations

import base64
import random
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

from qstheory2pdf.entry import (
    _build_parser,
    _issue_completeness_error,
    _output_paths,
)
from qstheory2pdf.gen_epub import EPUBGenerator
from qstheory2pdf.types import Article, TextBlock, TocEntry

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Wl2nLkAAAAASUVORK5CYII="
)


def _text(text: str, **overrides: object) -> TextBlock:
    block: TextBlock = {
        "text": text,
        "bold": False,
        "italic": False,
        "center": False,
        "large": False,
        "right": False,
        "left": False,
        "font_family": "",
        "font_size": 0,
        "role": "body",
    }
    block.update(overrides)  # type: ignore[typeddict-item]
    return block


def _png(width: int, height: int) -> bytes:
    pixels = random.Random(0).randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), pixels)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class EPUBGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images = self.root / "img"
        self.images.mkdir()
        (self.images / "figure.png").write_bytes(_PNG)
        (self.images / "cover.png").write_bytes(_PNG)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_gen_single_creates_valid_container_and_escaped_content(self) -> None:
        article: Article = {
            "title": "测试 & 标题",
            "subtitle": "副标题",
            "author": "作者",
            "volume": "《求是》2026/15",
            "date": "2026-08-01",
            "url": "https://example.com/article",
            "content": [
                _text("甲 < 乙 & 丙", bold=True, center=True),
                {"img": "figure.png", "caption": "图 & 说明"},
            ],
        }
        output = self.root / "single.epub"

        result = EPUBGenerator(str(self.images)).gen_single(article, str(output))

        self.assertTrue(Path(result).samefile(output))
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertEqual("mimetype", names[0])
            self.assertEqual(
                zipfile.ZIP_STORED,
                archive.getinfo("mimetype").compress_type,
            )
            self.assertEqual(
                b"application/epub+zip",
                archive.read("mimetype"),
            )
            self.assertIn("META-INF/container.xml", names)
            ElementTree.fromstring(archive.read("META-INF/container.xml"))
            opf = next(name for name in names if name.endswith(".opf"))
            opf_text = archive.read(opf).decode("utf-8")
            ElementTree.fromstring(opf_text)
            self.assertNotIn('<itemref idref="nav"', opf_text)
            self.assertIn(">作者</dc:creator>", opf_text)
            self.assertIn("<dc:date>2026-08-01</dc:date>", opf_text)
            self.assertIn(
                "<dc:source>https://example.com/article</dc:source>",
                opf_text,
            )
            self.assertIn("<dc:subject>求是</dc:subject>", opf_text)
            self.assertNotIn("<dc:publisher>", opf_text)
            chapter_name = next(
                name for name in names if name.endswith("article_001.xhtml")
            )
            chapter = archive.read(chapter_name).decode("utf-8")
            self.assertIn("测试 &amp; 标题", chapter)
            self.assertIn("甲 &lt; 乙 &amp; 丙", chapter)
            self.assertIn("《求是》2026/15", chapter)
            self.assertIn('class="center bold"', chapter)
            self.assertTrue(any(name.endswith("image_0000.webp") for name in names))
            css_name = next(name for name in names if name.endswith("book.css"))
            css = archive.read(css_name).decode("utf-8")
            self.assertIn('"Noto Serif CJK SC"', css)
            self.assertIn('"Noto Sans CJK SC"', css)
            self.assertIn('"LXGW WenKai"', css)
            self.assertIn("FangSong", css)
            self.assertIn("line-height: 1.65", css)
            self.assertIn("padding: 0 0.5em", css)
            self.assertIn("margin: 0.25em 0", css)
            self.assertIn("break-inside: avoid", css)
            self.assertIn("text-align: justify", css)

    def test_gen_issue_preserves_article_order_and_cover(self) -> None:
        articles: list[Article] = [
            {
                "title": "第一篇",
                "volume": "《求是》2026/15",
                "content": [_text("正文一")],
            },
            {
                "title": "第二篇",
                "volume": "《求是》2026/15",
                "content": [_text("正文二", right=True)],
            },
        ]
        entries: list[TocEntry] = [
            {
                "title": "第一篇",
                "column": "本刊特稿",
                "subtitle": "",
                "author": "",
                "author_role": "",
                "url": "https://example.com/1",
            },
            {
                "title": "第二篇",
                "column": "",
                "subtitle": "",
                "author": "",
                "author_role": "",
                "url": "https://example.com/2",
            },
        ]
        output = self.root / "issue.epub"

        EPUBGenerator(str(self.images)).gen_issue(
            articles,
            issue_volume="《求是》2026/15",
            issue_date="2026-08-01",
            toc_entries=entries,
            cover_image="cover.png",
            output_path=str(output),
            source_url="https://example.com/issue",
        )

        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            opf = archive.read(
                next(name for name in names if name.endswith(".opf"))
            ).decode("utf-8")
            first = archive.read(
                next(name for name in names if name.endswith("article_001.xhtml"))
            ).decode("utf-8")
            second = archive.read(
                next(name for name in names if name.endswith("article_002.xhtml"))
            ).decode("utf-8")
            nav = archive.read(
                next(name for name in names if name.endswith("nav.xhtml"))
            ).decode("utf-8")
            self.assertIn("本刊特稿", first)
            self.assertIn("正文一", first)
            self.assertNotIn("《求是》2026/15", first)
            self.assertIn('class="right"', second)
            self.assertNotIn("《求是》2026/15", second)
            self.assertLess(nav.index("第一篇"), nav.index("第二篇"))
            cover_name = next(name for name in names if name.endswith("cover.jpg"))
            self.assertTrue(archive.read(cover_name).startswith(b"\xff\xd8"))
            self.assertLess(
                opf.index('<itemref idref="cover_page"'),
                opf.index('<itemref idref="nav"'),
            )
            self.assertLess(
                opf.index('<itemref idref="nav"'),
                opf.index('<itemref idref="article_1"'),
            )
            self.assertIn("<dc:date>2026-08-01</dc:date>", opf)
            self.assertIn(
                "<dc:source>https://example.com/issue</dc:source>",
                opf,
            )
            self.assertIn("<dc:subject>求是</dc:subject>", opf)
            self.assertIn("<dc:subject>本刊特稿</dc:subject>", opf)
            self.assertIn("收录 2 篇文章", opf)
            self.assertNotIn("<dc:publisher>", opf)
            cover_page = archive.read(
                next(name for name in names if name.endswith("cover.xhtml"))
            ).decode("utf-8")
            self.assertIn('epub:type="cover"', cover_page)
            self.assertIn("../styles/cover.css", cover_page)
            self.assertIn("../images/cover-wrapper.svg", cover_page)
            cover_svg = archive.read(
                next(name for name in names if name.endswith("cover-wrapper.svg"))
            ).decode("utf-8")
            self.assertIn('viewBox="0 0 1 1"', cover_svg)
            self.assertIn('preserveAspectRatio="xMidYMid meet"', cover_svg)
            self.assertIn('href="cover.jpg"', cover_svg)
            cover_css = archive.read(
                next(name for name in names if name.endswith("cover.css"))
            ).decode("utf-8")
            self.assertIn("height: 100%", cover_css)
            self.assertIn("margin: 0", cover_css)

    def test_semantic_headings_use_h2_without_expanding_navigation(self) -> None:
        article: Article = {
            "title": "标题层级",
            "content": [
                _text(
                    "一、第一节",
                    bold=True,
                    role="section_heading",
                ),
                _text(
                    "居中小标题",
                    bold=True,
                    center=True,
                    role="section_heading",
                ),
                _text("同志们：", bold=True, left=True, role="salutation"),
                _text("普通粗体", bold=True),
            ],
        }
        output = self.root / "headings.epub"

        EPUBGenerator(str(self.images)).gen_single(article, str(output))

        with zipfile.ZipFile(output) as archive:
            chapter = archive.read(
                next(
                    name
                    for name in archive.namelist()
                    if name.endswith("article_001.xhtml")
                )
            ).decode("utf-8")
            nav = archive.read(
                next(name for name in archive.namelist() if name.endswith("nav.xhtml"))
            ).decode("utf-8")

        self.assertIn('<h2 id="section-001">一、第一节</h2>', chapter)
        self.assertIn(
            '<h2 id="section-002" class="center">居中小标题</h2>',
            chapter,
        )
        self.assertIn('<p class="left bold">同志们：</p>', chapter)
        self.assertIn("<p class=\"bold\">普通粗体</p>", chapter)
        self.assertNotIn("第一节", nav)

    def test_issue_without_cover_starts_at_navigation(self) -> None:
        output = self.root / "no-cover.epub"
        EPUBGenerator(str(self.images)).gen_issue(
            [{"title": "无封面期刊", "content": [_text("正文")]}],
            issue_volume="《求是》2026/15",
            output_path=str(output),
        )

        with zipfile.ZipFile(output) as archive:
            opf = archive.read(
                next(
                    name for name in archive.namelist() if name.endswith(".opf")
                )
            ).decode("utf-8")

        self.assertNotIn('<itemref idref="cover_page"', opf)
        self.assertLess(
            opf.index('<itemref idref="nav"'),
            opf.index('<itemref idref="article_1"'),
        )

    def test_static_raster_is_resized_and_encoded_as_webp(self) -> None:
        original = _png(1200, 600)
        source = self.images / "large.png"
        source.write_bytes(original)
        article: Article = {
            "title": "图片优化",
            "content": [{"img": "large.png", "caption": ""}],
        }
        output = self.root / "optimized.epub"

        EPUBGenerator(str(self.images)).gen_single(article, str(output))

        self.assertEqual(original, source.read_bytes())
        with zipfile.ZipFile(output) as archive:
            image_name = next(
                name for name in archive.namelist() if name.endswith("image_0000.webp")
            )
            optimized = archive.read(image_name)
            self.assertLess(len(optimized), len(original))
            with Image.open(BytesIO(optimized)) as image:
                self.assertEqual("WEBP", image.format)
                self.assertEqual((800, 400), image.size)
            opf_name = next(
                name for name in archive.namelist() if name.endswith(".opf")
            )
            self.assertIn(b'image/webp', archive.read(opf_name))

    def test_svg_and_animated_gif_are_not_transcoded(self) -> None:
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            b'<rect width="10" height="10"/></svg>'
        )
        (self.images / "vector.svg").write_bytes(svg)
        frames = [Image.new("RGB", (2, 2), color) for color in ("red", "blue")]
        gif_output = BytesIO()
        frames[0].save(
            gif_output,
            "GIF",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
        gif = gif_output.getvalue()
        (self.images / "animated.gif").write_bytes(gif)
        article: Article = {
            "title": "保留格式",
            "content": [
                {"img": "vector.svg", "caption": ""},
                {"img": "animated.gif", "caption": ""},
            ],
        }
        output = self.root / "preserved.epub"

        EPUBGenerator(str(self.images)).gen_single(article, str(output))

        with zipfile.ZipFile(output) as archive:
            images = {
                Path(name).suffix: archive.read(name)
                for name in archive.namelist()
                if name.startswith("EPUB/images/")
            }
            self.assertEqual(svg, images[".svg"])
            self.assertEqual(gif, images[".gif"])

    def test_missing_image_fails_with_clear_message(self) -> None:
        article: Article = {
            "title": "缺图",
            "content": [{"img": "missing.png", "caption": ""}],
        }

        with self.assertRaisesRegex(FileNotFoundError, "EPUB 图片不存在"):
            EPUBGenerator(str(self.images)).gen_single(
                article,
                str(self.root / "missing.epub"),
            )

    def test_empty_issue_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要一篇文章"):
            EPUBGenerator(str(self.images)).gen_issue([], "空刊")


class OutputPathTest(unittest.TestCase):
    def test_default_pdf_keeps_existing_semantics(self) -> None:
        self.assertEqual((None, None), _output_paths("pdf", None))
        self.assertEqual(("custom.pdf", None), _output_paths("pdf", "custom.pdf"))

    def test_both_uses_a_shared_base_name(self) -> None:
        self.assertEqual(
            ("output/issue.pdf", "output/issue.epub"),
            _output_paths("both", "output/issue.pdf"),
        )

    def test_strict_mode_is_available(self) -> None:
        args = _build_parser().parse_args(
            ["--format", "epub", "--strict", "https://example.com"]
        )
        self.assertTrue(args.strict)

    def test_incomplete_issue_message_lists_all_failure_types(self) -> None:
        message = _issue_completeness_error(
            ["https://example.com/failed"],
            ["https://example.com/empty"],
        )
        self.assertEqual(
            "整期内容不完整：1 篇下载失败，1 篇未提取到正文",
            message,
        )
        self.assertEqual("", _issue_completeness_error([], []))


if __name__ == "__main__":
    unittest.main()
