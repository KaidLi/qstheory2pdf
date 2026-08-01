"""Faithful-rendition tests at the PDF/EPUB public seams."""

from __future__ import annotations

import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

from qstheory2pdf.domain import reconstruction_status
from qstheory2pdf.gen_epub import EPUBGenerator
from qstheory2pdf.gen_pdf import PDFGenerator
from qstheory2pdf.types import Article, Issue

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Wl2nLkAAAAASUVORK5CYII="
)
_ID = "eb2be76d239d4fa4a0ef3a9a9d82b970"


def _article() -> Article:
    return {
        "source_id": _ID,
        "source_url": f"https://www.qstheory.cn/20260415/{_ID}/c.html",
        "title": "文章页题",
        "body": [
            {
                "kind": "paragraph",
                "role": "section_heading",
                "runs": [
                    {"text": "第一节", "strong": False, "emphasis": False},
                    {
                        "text": "规定",
                        "strong": True,
                        "emphasis": False,
                        "href": "https://example.com/rule",
                    },
                ],
                "alignment": "default",
                "font_family": "",
                "font_size": 0,
            }
        ],
        "reconstruction": reconstruction_status(),
    }


def _structured_article() -> Article:
    article = _article()
    article["body"] = [
        {
            "kind": "list",
            "ordered": True,
            "items": [[{"text": "重点", "strong": True, "emphasis": False}]],
        },
        {
            "kind": "table",
            "rows": [[
                {
                    "runs": [{"text": "项目", "strong": False, "emphasis": False}],
                    "header": True,
                    "rowspan": 1,
                    "colspan": 2,
                }
            ]],
        },
        {
            "kind": "quote",
            "paragraphs": [
                [{"text": "引文", "strong": False, "emphasis": True, "href": "https://example.com/citation"}],
                [{"text": "第二段", "strong": False, "emphasis": False}],
            ],
        },
    ]
    return article


def _issue() -> Issue:
    return {
        "id": {"publication_year": 2026, "issue_number": 8},
        "source_url": "https://example.com/issue",
        "entries": [
            {
                "ordinal": 1,
                "source_article_id": _ID,
                "source_url": "https://example.com/article",
                "directory_title": "目录题一",
                "directory_subtitle": "——目录副题",
                "section_label": "本刊特稿",
            },
            {
                "ordinal": 2,
                "source_article_id": _ID,
                "source_url": "https://example.com/article",
                "directory_title": "目录题二",
            },
        ],
        "reconstruction": reconstruction_status(),
    }


class PDFDomainRenderingTest(unittest.TestCase):
    def test_semantic_role_inline_emphasis_and_link_drive_rendering(self) -> None:
        rendered = PDFGenerator()._build_body(_article()["body"])
        self.assertIn(r"\qsheading{", rendered)
        self.assertIn(r"\href{https://example.com/rule}", rendered)
        self.assertIn(r"{\heiti 规定}", rendered)

    def test_lists_tables_and_quotes_use_semantic_latex(self) -> None:
        rendered = PDFGenerator()._build_body(_structured_article()["body"])
        self.assertIn(r"\begin{enumerate}", rendered)
        self.assertIn(r"\begin{tabular}", rendered)
        self.assertIn(r"\multicolumn{2}", rendered)
        self.assertIn(r"\begin{quote}", rendered)
        self.assertIn(r"\href{https://example.com/citation}", rendered)

    def test_missing_figure_position_is_visibly_marked(self) -> None:
        rendered = PDFGenerator()._build_body([
            {"kind": "figure", "images": [{"src": "", "alt": "关键图表", "missing": True}], "caption": []}
        ])
        self.assertIn("正文图像未能取得", rendered)
        self.assertIn("关键图表", rendered)

    def test_missing_directory_title_uses_marked_article_heading_fallback(self) -> None:
        issue = _issue()
        del issue["entries"][0]["directory_title"]
        tex = PDFGenerator()._build_issue_tex(
            issue,
            {_ID: _article()},
            reconstruction_status(),
        )
        self.assertIn("文章页题（文章页题）", tex)
        self.assertNotIn("directory_title", issue["entries"][0])

    def test_directory_context_does_not_overwrite_article_heading(self) -> None:
        tex = PDFGenerator()._build_issue_tex(
            _issue(),
            {_ID: _article()},
            reconstruction_status(),
        )
        self.assertIn("目录题一", tex)
        self.assertIn("目录题二", tex)
        self.assertIn("——目录副题", tex)
        self.assertIn(r"\qstitle{文章页题}", tex)
        self.assertNotIn(r"\qscolumn{本刊特稿}", tex)


class EPUBDomainRenderingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        (self.images / "figure.png").write_bytes(_PNG)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_byline_does_not_invent_creator(self) -> None:
        output = self.root / "article.epub"
        EPUBGenerator(str(self.images)).gen_single(_article(), str(output))
        with zipfile.ZipFile(output) as archive:
            opf = archive.read(next(name for name in archive.namelist() if name.endswith(".opf"))).decode()
            chapter = archive.read(next(name for name in archive.namelist() if name.endswith("article_001.xhtml"))).decode()
        self.assertNotIn("dc:creator", opf)
        self.assertIn('<h2 id="section-001">', chapter)
        self.assertIn('<a href="https://example.com/rule"><strong>规定</strong></a>', chapter)

    def test_lists_tables_and_quotes_use_semantic_xhtml(self) -> None:
        output = self.root / "structured.epub"
        EPUBGenerator(str(self.images)).gen_single(_structured_article(), str(output))
        with zipfile.ZipFile(output) as archive:
            chapter = archive.read(next(name for name in archive.namelist() if name.endswith("article_001.xhtml"))).decode()
        self.assertIn("<ol>", chapter)
        self.assertIn("<table>", chapter)
        self.assertIn('<th colspan="2">', chapter)
        self.assertIn("<blockquote>", chapter)
        self.assertIn('href="https://example.com/citation"', chapter)

    def test_missing_figure_position_is_visibly_marked(self) -> None:
        article = _article()
        article["body"] = [
            {"kind": "figure", "images": [{"src": "", "alt": "关键图表", "missing": True}], "caption": []}
        ]
        output = self.root / "missing-figure.epub"
        EPUBGenerator(str(self.images)).gen_single(article, str(output))
        with zipfile.ZipFile(output) as archive:
            chapter = archive.read(next(name for name in archive.namelist() if name.endswith("article_001.xhtml"))).decode()
        self.assertIn("正文图像未能取得：关键图表", chapter)

    def test_duplicate_entries_share_one_chapter_and_keep_two_toc_positions(self) -> None:
        output = self.root / "issue.epub"
        EPUBGenerator(str(self.images)).gen_issue(
            _issue(),
            {_ID: _article()},
            output_path=str(output),
        )
        with zipfile.ZipFile(output) as archive:
            article_names = [name for name in archive.namelist() if name.endswith("article_001.xhtml")]
            nav = archive.read(next(name for name in archive.namelist() if name.endswith("nav.xhtml"))).decode()
            chapter = archive.read(article_names[0]).decode()
            opf = archive.read(next(name for name in archive.namelist() if name.endswith(".opf"))).decode()
        self.assertEqual(1, len(article_names))
        self.assertIn("目录题一", nav)
        self.assertIn("目录题二", nav)
        self.assertIn("本刊特稿", nav)
        self.assertIn("——目录副题", nav)
        self.assertNotIn("本刊特稿", chapter)
        self.assertNotIn("——目录副题", chapter)
        self.assertIn("文章页题", chapter)
        self.assertNotIn("dc:creator", opf)
        self.assertEqual(1, opf.count('idref="article_1"'))


if __name__ == "__main__":
    unittest.main()
