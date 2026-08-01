"""PDF presentation regressions that do not require XeLaTeX."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from qstheory2pdf.domain import reconstruction_status
from qstheory2pdf.gen_pdf import PDFGenerator, _escape_latex, format_text_to_latex
from qstheory2pdf.types import Article, ParagraphBlock

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


class PDFRenderingTest(unittest.TestCase):
    def test_latex_escaping_covers_control_characters(self) -> None:
        escaped = _escape_latex(r"\{甲&乙}_$~^")
        self.assertIn(r"\textbackslash{}", escaped)
        self.assertIn(r"\&", escaped)
        self.assertIn(r"\textasciitilde{}", escaped)
        self.assertIn(r"\textasciicircum{}", escaped)

    def test_plain_text_compatibility_helper_and_semantic_alignment(self) -> None:
        self.assertEqual(r"{\kaishu 甲\ 乙}", format_text_to_latex("甲 乙", font_family="kai"))
        rendered = PDFGenerator._render_text_block(_paragraph("署名", role="signature"))
        self.assertEqual(r"\begin{flushright}署名\end{flushright}", rendered)

    def test_issue_tex_uses_issue_identity_and_article_bookmark(self) -> None:
        article: Article = {
            "source_id": _ID,
            "source_url": "https://example.com/article",
            "title": "文章页题",
            "body": [_paragraph("正文")],
            "reconstruction": reconstruction_status(),
        }
        issue = {
            "id": {"publication_year": 2026, "issue_number": 15},
            "source_url": "https://example.com/issue",
            "entries": [
                {
                    "ordinal": 1,
                    "source_article_id": _ID,
                    "source_url": "https://example.com/article",
                    "directory_title": "目录题",
                    "section_label": "本刊特稿",
                }
            ],
            "reconstruction": reconstruction_status(),
        }
        tex = PDFGenerator(device="scribe")._build_issue_tex(
            issue,
            {_ID: article},
            reconstruction_status(),
        )
        self.assertIn(r"\documentclass[scribe, black]{qiushi}", tex)
        self.assertIn("本刊特稿", tex)
        self.assertIn("目录题", tex)
        self.assertIn(r"\qstitle{文章页题}", tex)
        self.assertIn(r"\pdfbookmark[0]{文章页题}{art:0}", tex)

    def test_partial_article_requires_explicit_generator_opt_in(self) -> None:
        article: Article = {
            "source_id": _ID,
            "source_url": "https://example.com/article",
            "title": "部分文章",
            "body": [_paragraph("正文")],
            "reconstruction": reconstruction_status(
                [{"code": "missing", "message": "缺失"}]
            ),
        }
        with self.assertRaisesRegex(ValueError, "allow_partial=True"):
            PDFGenerator().gen_single(article)

    def test_missing_xelatex_has_clear_error(self) -> None:
        with (
            patch("qstheory2pdf.gen_pdf.shutil.which", return_value=None),
            patch("qstheory2pdf.gen_pdf.os.path.exists", return_value=False),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "xelatex not found"):
                PDFGenerator._find_xelatex()


if __name__ == "__main__":
    unittest.main()
