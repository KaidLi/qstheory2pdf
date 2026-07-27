"""PDF 展示层的无 LaTeX 回归测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from qstheory2pdf.gen_pdf import PDFGenerator, _escape_latex, format_text_to_latex
from qstheory2pdf.types import Article, TextBlock, TocEntry


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


class PDFRenderingTest(unittest.TestCase):
    def test_latex_escaping_covers_control_characters(self) -> None:
        escaped = _escape_latex(r"\{甲&乙}_$~^")

        self.assertIn(r"\textbackslash{}", escaped)
        self.assertIn(r"\&", escaped)
        self.assertIn(r"\textasciitilde{}", escaped)
        self.assertIn(r"\textasciicircum{}", escaped)

    def test_font_family_and_alignment_rendering(self) -> None:
        self.assertEqual(r"{\kaishu 甲\ 乙}", format_text_to_latex("甲 乙", font_family="kai"))
        rendered = PDFGenerator._render_text_block(
            _text("署名", right=True, bold=True)
        )
        self.assertEqual(
            r"\begin{flushright}署名\end{flushright}",
            rendered,
        )

    def test_issue_tex_contains_toc_and_article_bookmark(self) -> None:
        generator = PDFGenerator(device="scribe")
        articles: list[Article] = [
            {"title": "测试文章", "author": "作者", "content": [_text("正文")]}
        ]
        entries: list[TocEntry] = [
            {
                "title": "测试文章",
                "column": "本刊特稿",
                "subtitle": "",
                "author": "作者",
                "author_role": "",
                "url": "https://example.com",
            }
        ]

        tex = generator._build_issue_tex(
            articles,
            "《求是》2026/15",
            "2026-08-01",
            entries,
        )

        self.assertIn(r"\documentclass[scribe, black]{qiushi}", tex)
        self.assertIn(r"\qscolumn{本刊特稿}", tex)
        self.assertIn(r"\pdfbookmark[0]{测试文章}{art:0}", tex)

    def test_missing_xelatex_has_clear_error(self) -> None:
        with (
            patch("qstheory2pdf.gen_pdf.shutil.which", return_value=None),
            patch("qstheory2pdf.gen_pdf.os.path.exists", return_value=False),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "xelatex not found"):
                PDFGenerator._find_xelatex()


if __name__ == "__main__":
    unittest.main()
