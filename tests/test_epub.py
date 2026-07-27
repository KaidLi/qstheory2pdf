"""EPUB 生成与 CLI 输出路径测试。"""

from __future__ import annotations

import base64
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

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
    }
    block.update(overrides)  # type: ignore[typeddict-item]
    return block


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
            ElementTree.fromstring(archive.read(opf))
            chapter_name = next(
                name for name in names if name.endswith("article_001.xhtml")
            )
            chapter = archive.read(chapter_name).decode("utf-8")
            self.assertIn("测试 &amp; 标题", chapter)
            self.assertIn("甲 &lt; 乙 &amp; 丙", chapter)
            self.assertIn('class="center bold"', chapter)
            self.assertTrue(any(name.endswith("image_0000.png") for name in names))

    def test_gen_issue_preserves_article_order_and_cover(self) -> None:
        articles: list[Article] = [
            {"title": "第一篇", "content": [_text("正文一")]},
            {"title": "第二篇", "content": [_text("正文二", right=True)]},
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
        )

        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
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
            self.assertIn('class="right"', second)
            self.assertLess(nav.index("第一篇"), nav.index("第二篇"))
            self.assertTrue(any(name.endswith("cover.png") for name in names))

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
