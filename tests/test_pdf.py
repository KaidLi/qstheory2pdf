"""PDF 展示层的无 LaTeX 回归测试。"""

from __future__ import annotations

import unittest
import io
import subprocess
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
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
        "role": "body",
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


class PDFCompilationTest(unittest.TestCase):
    def test_failed_pass_never_replaces_existing_publication(self) -> None:
        for failed_pass in (1, 2):
            with self.subTest(failed_pass=failed_pass), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "publication.pdf"
                target.write_bytes(b"previous good publication")
                generator = PDFGenerator()
                generator.start()
                passes = []

                def compile_pass(*args, **kwargs):
                    passes.append(1)
                    Path(generator.workdir, "output.pdf").write_bytes(b"broken PDF")
                    Path(generator.workdir, "output.log").write_text("Missing figure diagnostic")
                    return subprocess.CompletedProcess(
                        args[0], 1 if len(passes) == failed_pass else 0, b"compiler output", b""
                    )

                try:
                    with (
                        patch.object(generator, "_find_xelatex", return_value="xelatex"),
                        patch("qstheory2pdf.gen_pdf.subprocess.run", side_effect=compile_pass),
                        patch("qstheory2pdf.gen_pdf.os.getcwd", return_value=directory),
                        redirect_stdout(io.StringIO()),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "exit 1"):
                            generator.gen_single({"title": "Article", "content": []}, str(target))
                finally:
                    generator.finish()
                self.assertEqual(failed_pass, len(passes))
                self.assertEqual(b"previous good publication", target.read_bytes())
                logs = list(Path(directory, "output", "build-logs").glob("*.log"))
                self.assertEqual(1, len(logs))
                self.assertIn("Missing figure diagnostic", logs[0].read_text())

    def test_missing_empty_and_stale_pdf_are_rejected(self) -> None:
        for stale, produced in ((False, None), (False, b""), (True, None)):
            with self.subTest(stale=stale, produced=produced), tempfile.TemporaryDirectory() as directory:
                generator = PDFGenerator()
                generator.start()
                if stale:
                    Path(generator.workdir, "output.pdf").write_bytes(b"old PDF")

                def compile_pass(*args, **kwargs):
                    if produced is not None:
                        Path(generator.workdir, "output.pdf").write_bytes(produced)
                    return subprocess.CompletedProcess(args[0], 0, b"", b"")

                try:
                    with (
                        patch.object(generator, "_find_xelatex", return_value="xelatex"),
                        patch("qstheory2pdf.gen_pdf.subprocess.run", side_effect=compile_pass),
                        patch("qstheory2pdf.gen_pdf.os.getcwd", return_value=directory),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "PDF"):
                            generator._compile("output", verbose=False)
                finally:
                    generator.finish()

    def test_timeout_preserves_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generator = PDFGenerator()
            generator.start()
            try:
                with (
                    patch.object(generator, "_find_xelatex", return_value="xelatex"),
                    patch("qstheory2pdf.gen_pdf.subprocess.run", side_effect=subprocess.TimeoutExpired(
                        "xelatex", 300, output=b"timeout details", stderr=b"stderr details"
                    )),
                    patch("qstheory2pdf.gen_pdf.os.getcwd", return_value=directory),
                ):
                    with self.assertRaisesRegex(RuntimeError, "timed out"):
                        generator._compile("output", verbose=False)
            finally:
                generator.finish()
            log = next(Path(directory, "output", "build-logs").glob("*.log"))
            self.assertIn("timeout details", log.read_text())
            self.assertIn("stderr details", log.read_text())

    def test_two_successful_passes_publish_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generator = PDFGenerator()
            generator.start()
            target = Path(directory, "publication.pdf")
            def compile_pass(*args, **kwargs):
                Path(generator.workdir, "output.pdf").write_bytes(b"generated PDF")
                return subprocess.CompletedProcess(args[0], 0, b"", b"")
            try:
                with (
                    patch.object(generator, "_find_xelatex", return_value="xelatex"),
                    patch("qstheory2pdf.gen_pdf.subprocess.run", side_effect=compile_pass) as run,
                    redirect_stdout(io.StringIO()),
                ):
                    generator.gen_single({"title": "Article", "content": []}, str(target))
                self.assertEqual(2, run.call_count)
                self.assertEqual(b"generated PDF", target.read_bytes())
            finally:
                generator.finish()


if __name__ == "__main__":
    unittest.main()
