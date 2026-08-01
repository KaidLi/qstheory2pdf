"""EPUB generation and output-path regressions."""

from __future__ import annotations

import base64
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from qstheory2pdf.domain import reconstruction_status
from qstheory2pdf.entry import _build_parser, _output_paths
from qstheory2pdf.gen_epub import EPUBGenerator
from qstheory2pdf.types import Article, FigureBlock, ParagraphBlock

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Wl2nLkAAAAASUVORK5CYII="
)
_ID = "11111111111111111111111111111111"


def _paragraph(text: str, *, role: str = "body", alignment: str = "default") -> ParagraphBlock:
    return {
        "kind": "paragraph",
        "role": role,  # type: ignore[typeddict-item]
        "runs": [{"text": text, "strong": False, "emphasis": False}],
        "alignment": alignment,  # type: ignore[typeddict-item]
        "font_family": "",
        "font_size": 0,
    }


def _article(*, body=None, byline: str = "作者") -> Article:
    article: Article = {
        "source_id": _ID,
        "source_url": f"https://www.qstheory.cn/20260801/{_ID}/c.html",
        "title": "测试 & 标题",
        "source_publication_date": "2026-08-02",
        "issue_label": "《求是》2026/15",
        "body": body or [_paragraph("正文")],
        "reconstruction": reconstruction_status(),
    }
    if byline:
        article["byline"] = byline
    return article


def _issue():
    return {
        "id": {"publication_year": 2026, "issue_number": 15},
        "source_url": "https://example.com/issue",
        "publication_date": "2026-08-01",
        "entries": [
            {
                "ordinal": 1,
                "source_article_id": _ID,
                "source_url": "https://example.com/article",
                "directory_title": "目录标题",
                "section_label": "本刊特稿",
            }
        ],
        "reconstruction": reconstruction_status(),
    }


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

    def test_single_creates_valid_container_and_semantic_content(self) -> None:
        paragraph = _paragraph("甲 < 乙 & 丙")
        paragraph["runs"] = [
            {"text": "甲 < ", "strong": False, "emphasis": False},
            {
                "text": "乙 & 丙",
                "strong": True,
                "emphasis": False,
                "href": "https://example.com/rule?a=1&b=2",
            },
        ]
        figure: FigureBlock = {
            "kind": "figure",
            "images": [{"src": "figure.png", "alt": "图"}],
            "caption": [{"text": "图 & 说明", "strong": False, "emphasis": False}],
        }
        output = self.root / "single.epub"
        EPUBGenerator(str(self.images)).gen_single(_article(body=[paragraph, figure]), str(output))

        with zipfile.ZipFile(output) as archive:
            self.assertEqual("mimetype", archive.namelist()[0])
            self.assertEqual(zipfile.ZIP_STORED, archive.getinfo("mimetype").compress_type)
            self.assertEqual(b"application/epub+zip", archive.read("mimetype"))
            ElementTree.fromstring(archive.read("META-INF/container.xml"))
            opf_name = next(name for name in archive.namelist() if name.endswith(".opf"))
            opf = archive.read(opf_name).decode()
            ElementTree.fromstring(opf)
            chapter = archive.read(next(name for name in archive.namelist() if name.endswith("article_001.xhtml"))).decode()
            self.assertIn(">作者</dc:creator>", opf)
            self.assertIn("<dc:date>2026-08-02</dc:date>", opf)
            self.assertIn("<dc:source>https://www.qstheory.cn", opf)
            self.assertIn("甲 &lt; ", chapter)
            self.assertIn('<a href="https://example.com/rule?a=1&amp;b=2"><strong>乙 &amp; 丙</strong></a>', chapter)
            self.assertIn("图 &amp; 说明", chapter)
            image_name = next(name for name in archive.namelist() if name.endswith("image_0000.png"))
            self.assertEqual(_PNG, archive.read(image_name))

    def test_article_identifier_depends_on_source_identity_not_title(self) -> None:
        first = _article()
        second = _article()
        second["title"] = "改过的标题"
        paths = [self.root / "first.epub", self.root / "second.epub"]
        generator = EPUBGenerator(str(self.images))
        generator.gen_single(first, str(paths[0]))
        generator.gen_single(second, str(paths[1]))

        identifiers = []
        for path in paths:
            with zipfile.ZipFile(path) as archive:
                opf = archive.read(next(name for name in archive.namelist() if name.endswith(".opf")))
            root = ElementTree.fromstring(opf)
            identifier = root.find(".//{http://purl.org/dc/elements/1.1/}identifier")
            identifiers.append(identifier.text)
        self.assertEqual(identifiers[0], identifiers[1])

    def test_issue_keeps_directory_context_in_navigation_only_and_uses_cover(self) -> None:
        output = self.root / "issue.epub"
        EPUBGenerator(str(self.images)).gen_issue(
            _issue(),
            {_ID: _article()},
            cover_image="cover.png",
            output_path=str(output),
        )
        with zipfile.ZipFile(output) as archive:
            opf = archive.read(next(name for name in archive.namelist() if name.endswith(".opf"))).decode()
            nav = archive.read(next(name for name in archive.namelist() if name.endswith("nav.xhtml"))).decode()
            chapter = archive.read(next(name for name in archive.namelist() if name.endswith("article_001.xhtml"))).decode()
            self.assertIn("目录标题", nav)
            self.assertIn("本刊特稿", nav)
            self.assertNotIn("本刊特稿", chapter)
            self.assertNotIn("<dc:subject>本刊特稿</dc:subject>", opf)
            self.assertIn("<dc:date>2026-08-01</dc:date>", opf)
            self.assertIn("<dc:source>https://example.com/issue</dc:source>", opf)
            self.assertTrue(archive.read(next(name for name in archive.namelist() if name.endswith("cover.jpg"))).startswith(b"\xff\xd8"))

    def test_semantic_heading_uses_h2_even_without_visual_heading_flags(self) -> None:
        article = _article(body=[_paragraph("一、第一节", role="section_heading")])
        output = self.root / "headings.epub"
        EPUBGenerator(str(self.images)).gen_single(article, str(output))
        with zipfile.ZipFile(output) as archive:
            chapter = archive.read(next(name for name in archive.namelist() if name.endswith("article_001.xhtml"))).decode()
        self.assertIn('<h2 id="section-001">一、第一节</h2>', chapter)

    def test_missing_image_fails_with_clear_message(self) -> None:
        figure: FigureBlock = {
            "kind": "figure",
            "images": [{"src": "missing.png", "alt": ""}],
            "caption": [],
        }
        with self.assertRaisesRegex(FileNotFoundError, "EPUB 图片不存在"):
            EPUBGenerator(str(self.images)).gen_single(
                _article(body=[figure]),
                str(self.root / "missing.epub"),
            )

    def test_partial_issue_keeps_missing_entry_as_marked_placeholder(self) -> None:
        issue = _issue()
        missing_id = "22222222222222222222222222222222"
        issue["entries"].append(
            {
                "ordinal": 2,
                "source_article_id": missing_id,
                "source_url": "https://example.com/missing",
                "directory_title": "缺失文章",
            }
        )
        status = reconstruction_status(
            [{"code": "missing_entry_article", "message": "入刊文章缺失"}]
        )
        output = self.root / "partial.epub"
        EPUBGenerator(str(self.images)).gen_issue(
            issue,
            {_ID: _article()},
            output_path=str(output),
            status=status,
            allow_partial=True,
        )
        with zipfile.ZipFile(output) as archive:
            nav = archive.read(next(name for name in archive.namelist() if name.endswith("nav.xhtml"))).decode()
            missing = archive.read(next(name for name in archive.namelist() if name.endswith("article_002.xhtml"))).decode()
        self.assertIn("缺失文章 [缺失]", nav)
        self.assertIn("此入刊条目的文章未能取得", missing)

    def test_partial_article_requires_explicit_generator_opt_in(self) -> None:
        article = _article()
        article["reconstruction"] = reconstruction_status(
            [{"code": "missing", "message": "缺失"}]
        )
        with self.assertRaisesRegex(ValueError, "allow_partial=True"):
            EPUBGenerator(str(self.images)).gen_single(article, str(self.root / "partial.epub"))

    def test_empty_issue_is_rejected(self) -> None:
        empty = {
            "id": {"publication_year": 2026, "issue_number": 15},
            "source_url": "https://example.com/issue",
            "entries": [],
            "reconstruction": reconstruction_status(),
        }
        with self.assertRaisesRegex(ValueError, "至少需要一个入刊条目"):
            EPUBGenerator(str(self.images)).gen_issue(empty, {})


class OutputPathTest(unittest.TestCase):
    def test_default_pdf_keeps_existing_semantics(self) -> None:
        self.assertEqual((None, None), _output_paths("pdf", None))
        self.assertEqual(("custom.pdf", None), _output_paths("pdf", "custom.pdf"))

    def test_both_uses_a_shared_base_name(self) -> None:
        self.assertEqual(
            ("output/issue.pdf", "output/issue.epub"),
            _output_paths("both", "output/issue.pdf"),
        )

    def test_strict_alias_and_allow_partial_are_available(self) -> None:
        self.assertTrue(_build_parser().parse_args(["--strict", "https://example.com"]).strict)
        self.assertTrue(
            _build_parser().parse_args(["--allow-partial", "https://example.com"]).allow_partial
        )


if __name__ == "__main__":
    unittest.main()
