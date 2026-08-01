"""CLI completeness and source-kind policy tests."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from qstheory2pdf.domain import reconstruction_status
from qstheory2pdf.entry import _build_parser, main
from qstheory2pdf.types import Article, Issue

_ID1 = "11111111111111111111111111111111"
_ID2 = "22222222222222222222222222222222"
_URL = "https://example.com/issue"


def _article(source_id: str) -> Article:
    return {
        "source_id": source_id,
        "source_url": f"https://www.qstheory.cn/20260801/{source_id}/c.html",
        "title": f"文章{source_id[0]}",
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


def _issue(*source_ids: str) -> Issue:
    return {
        "id": {"publication_year": 2026, "issue_number": 15},
        "source_url": _URL,
        "entries": [
            {
                "ordinal": index,
                "source_article_id": source_id,
                "source_url": f"https://www.qstheory.cn/20260801/{source_id}/c.html",
                "directory_title": f"目录{index}",
            }
            for index, source_id in enumerate(source_ids, 1)
        ],
        "reconstruction": reconstruction_status(),
    }


class ParserPolicyTest(unittest.TestCase):
    def test_default_is_complete_only_and_partial_requires_explicit_flag(self) -> None:
        default = _build_parser().parse_args([_URL])
        partial = _build_parser().parse_args(["--allow-partial", _URL])
        strict = _build_parser().parse_args(["--strict", _URL])
        self.assertFalse(default.allow_partial)
        self.assertTrue(partial.allow_partial)
        self.assertTrue(strict.strict)
        with self.assertRaises(SystemExit):
            _build_parser().parse_args(["--strict", "--allow-partial", _URL])


class CompletenessPolicyTest(unittest.TestCase):
    def _crawler(self) -> Mock:
        crawler = Mock()
        crawler.fetch_document.return_value = {"kind": "issue_contents", "issue": _issue(_ID1, _ID2)}
        crawler.fetch_info.side_effect = [_article(_ID1), requests.Timeout("超时")]
        crawler.download_toc_cover.return_value = None
        return crawler

    def test_partial_issue_is_rejected_by_default_and_status_is_machine_readable(self) -> None:
        crawler = self._crawler()
        with tempfile.TemporaryDirectory() as root:
            status_path = Path(root) / "status.json"
            with (
                patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
                patch("qstheory2pdf.entry.EPUBGenerator") as generator,
                patch(
                    "sys.argv",
                    ["qstheory2pdf", "--format", "epub", "--status-file", str(status_path), _URL],
                ),
                redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as error:
                    main()
            self.assertEqual(1, error.exception.code)
            self.assertEqual("partial", json.loads(status_path.read_text(encoding="utf-8"))["state"])
            generator.assert_not_called()

    def test_allow_partial_marks_output_and_duplicate_entries_fetch_once(self) -> None:
        issue = _issue(_ID1, _ID1)
        crawler = Mock()
        crawler.fetch_document.return_value = {"kind": "issue_contents", "issue": issue}
        partial_article = _article(_ID1)
        partial_article["reconstruction"] = reconstruction_status(
            [{"code": "known_omission", "message": "已知正文遗漏"}]
        )
        crawler.fetch_info.return_value = partial_article
        crawler.download_toc_cover.return_value = None
        generator = Mock()
        generator.gen_issue.return_value = "out-partial.epub"
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator", return_value=generator),
            patch(
                "sys.argv",
                [
                    "qstheory2pdf",
                    "--format",
                    "epub",
                    "--allow-partial",
                    "-o",
                    "out.epub",
                    _URL,
                ],
            ),
            redirect_stdout(io.StringIO()),
        ):
            main()
        crawler.fetch_info.assert_called_once()
        self.assertEqual("out-partial.epub", generator.gen_issue.call_args.kwargs["output_path"])

    def test_identity_mismatch_never_places_wrong_article_in_entry(self) -> None:
        crawler = Mock()
        crawler.fetch_document.return_value = {
            "kind": "issue_contents",
            "issue": _issue(_ID1),
        }
        crawler.fetch_info.return_value = _article(_ID2)
        crawler.download_toc_cover.return_value = None
        generator = Mock()
        generator.gen_issue.return_value = "out-partial.epub"
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator", return_value=generator),
            patch(
                "sys.argv",
                [
                    "qstheory2pdf",
                    "--format",
                    "epub",
                    "--allow-partial",
                    "-o",
                    "out.epub",
                    _URL,
                ],
            ),
            redirect_stdout(io.StringIO()),
        ):
            main()
        self.assertEqual({}, generator.gen_issue.call_args.args[1])
        status = generator.gen_issue.call_args.kwargs["status"]
        self.assertIn(
            "article_identity_mismatch",
            [problem["code"] for problem in status["problems"]],
        )

    def test_single_is_an_expectation_and_rejects_issue_source(self) -> None:
        crawler = Mock()
        crawler.fetch_document.return_value = {"kind": "issue_contents", "issue": _issue(_ID1)}
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("sys.argv", ["qstheory2pdf", "--format", "epub", "--single", _URL]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(1, error.exception.code)


if __name__ == "__main__":
    unittest.main()
