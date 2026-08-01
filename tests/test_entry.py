"""CLI issue-catalog behavior tests."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from qstheory2pdf.crawler import SourceClassificationError
from qstheory2pdf.domain import reconstruction_status
from qstheory2pdf.entry import main
from qstheory2pdf.types import Article, Issue


def _article(source_id: str) -> Article:
    return {
        "source_id": source_id,
        "source_url": f"https://www.qstheory.cn/20260801/{source_id}/c.html",
        "title": f"文章 {source_id[0]}",
        "body": [
            {
                "kind": "paragraph",
                "role": "body",
                "runs": [{"text": "正文", "strong": False, "emphasis": False}],
                "alignment": "default",
                "font_family": "",
                "font_size": 0,
            }
        ],
        "reconstruction": reconstruction_status(),
    }


def _issue(year: int, number: int, source_id: str, url: str) -> Issue:
    return {
        "id": {"publication_year": year, "issue_number": number},
        "source_url": url,
        "entries": [
            {
                "ordinal": 1,
                "source_article_id": source_id,
                "source_url": f"https://www.qstheory.cn/20260801/{source_id}/c.html",
                "directory_title": f"第 {number} 期文章",
            }
        ],
        "reconstruction": reconstruction_status(),
    }


def _catalog_documents():
    first_id = "11111111111111111111111111111111"
    second_id = "22222222222222222222222222222222"
    issue_urls = ["https://example.com/issue-1", "https://example.com/issue-2"]
    catalog = {
        "kind": "issue_catalog",
        "catalog": {
            "source_url": "https://example.com/catalog",
            "publication_year": 2026,
            "issues": [
                {"id": {"publication_year": 2026, "issue_number": 1}, "source_url": issue_urls[0]},
                {"id": {"publication_year": 2026, "issue_number": 2}, "source_url": issue_urls[1]},
            ],
        },
    }
    issues = [
        {"kind": "issue_contents", "issue": _issue(2026, 1, first_id, issue_urls[0])},
        {"kind": "issue_contents", "issue": _issue(2026, 2, second_id, issue_urls[1])},
    ]
    return first_id, second_id, catalog, issues


class IssueCatalogModeTest(unittest.TestCase):
    def _run(
        self,
        crawler,
        generator,
        output_dir: str,
        *,
        status_file: str | None = None,
        allow_partial: bool = False,
    ):
        argv = ["qstheory2pdf", "--format", "epub", "-o", output_dir]
        if allow_partial:
            argv.append("--allow-partial")
        if status_file:
            argv.extend(["--status-file", status_file])
        argv.append("https://example.com/catalog")
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator", return_value=generator),
            patch("sys.argv", argv),
            redirect_stdout(io.StringIO()) as output,
        ):
            main()
        return output.getvalue()

    def test_catalog_generates_one_publication_per_issue(self) -> None:
        first_id, second_id, catalog, issues = _catalog_documents()
        crawler = Mock()
        crawler.fetch_document.side_effect = [catalog, *issues]
        crawler.fetch_info.side_effect = [_article(first_id), _article(second_id)]
        crawler.download_toc_cover.return_value = None
        generator = Mock()
        generator.gen_issue.side_effect = lambda *args, **kwargs: kwargs["output_path"]

        with tempfile.TemporaryDirectory() as output_dir:
            output = self._run(crawler, generator, output_dir)
            paths = [call.kwargs["output_path"] for call in generator.gen_issue.call_args_list]
            self.assertEqual(
                [
                    str(Path(output_dir) / "求是_2026_01.epub"),
                    str(Path(output_dir) / "求是_2026_02.epub"),
                ],
                paths,
            )
            self.assertIn("期次目录集: 共 2 期", output)

    def test_catalog_continues_after_failure_but_exits_nonzero(self) -> None:
        first_id, second_id, catalog, issues = _catalog_documents()
        crawler = Mock()
        crawler.fetch_document.side_effect = [
            catalog,
            SourceClassificationError("期次来源失败"),
            issues[1],
        ]
        crawler.fetch_info.side_effect = [_article(second_id)]
        crawler.download_toc_cover.return_value = None
        generator = Mock()
        generator.gen_issue.side_effect = lambda *args, **kwargs: kwargs["output_path"]

        with tempfile.TemporaryDirectory() as output_dir:
            status_file = str(Path(output_dir) / "status.json")
            with self.assertRaises(SystemExit) as raised:
                self._run(
                    crawler,
                    generator,
                    output_dir,
                    status_file=status_file,
                    allow_partial=True,
                )
            self.assertEqual(1, raised.exception.code)
            self.assertEqual(1, generator.gen_issue.call_count)
            status = json.loads(Path(status_file).read_text(encoding="utf-8"))
            self.assertEqual("partial", status["state"])
            self.assertEqual(1, len(status["outputs"]))
            self.assertIn("求是_2026_02.epub", status["outputs"][0]["path"])
            self.assertEqual(first_id, issues[0]["issue"]["entries"][0]["source_article_id"])


if __name__ == "__main__":
    unittest.main()
