"""CLI 整期完整性策略测试。"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from qstheory2pdf.entry import _year_issue_links, main
from qstheory2pdf.types import Article

_URL = "https://www.qstheory.cn/20260801/toc/c.html"
_ARTICLE_URLS = [
    "https://www.qstheory.cn/20260801/11111111111111111111111111111111/c.html",
    "https://www.qstheory.cn/20260801/22222222222222222222222222222222/c.html",
]
_ARTICLE: Article = {
    "title": "完整文章",
    "volume": "《求是》2026/15",
    "date": "2026-08-01",
    "source_id": "a" * 32,
    "url": _ARTICLE_URLS[0],
    "content": [],
}
_ARTICLE["content"] = [
    {
        "text": "正文",
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
]


def _crawler() -> Mock:
    crawler = Mock()
    crawler.fetch_toc.return_value = {"urls": _ARTICLE_URLS, "entries": []}
    crawler.fetch_info.side_effect = [_ARTICLE, requests.Timeout("超时")]
    crawler.download_toc_cover.return_value = None
    return crawler


class EntryCompletenessTest(unittest.TestCase):
    def test_strict_mode_stops_before_generation(self) -> None:
        crawler = _crawler()
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator") as generator,
            patch(
                "sys.argv",
                ["qstheory2pdf", "--format", "epub", "--strict", _URL],
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            with self.assertRaises(SystemExit) as error:
                main()

        self.assertEqual(1, error.exception.code)
        self.assertIn("整期内容不完整", output.getvalue())
        generator.assert_not_called()

    def test_default_mode_rejects_partial_issue(self) -> None:
        """默认行为即拒绝部分重建（与 --strict 一致）。"""
        crawler = _crawler()
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator") as generator,
            patch("sys.argv", ["qstheory2pdf", "--format", "epub", _URL]),
            redirect_stdout(io.StringIO()) as output,
        ):
            with self.assertRaises(SystemExit) as error:
                main()

        self.assertEqual(1, error.exception.code)
        self.assertIn("整期内容不完整", output.getvalue())
        generator.assert_not_called()

    def test_allow_partial_generates_marked_issue(self) -> None:
        """--allow-partial 生成带 -partial 标记的产物。"""
        crawler = _crawler()
        generator = Mock()
        generator.gen_issue.return_value = "/tmp/marked.epub"
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator", return_value=generator),
            patch(
                "sys.argv",
                ["qstheory2pdf", "--format", "epub", "--allow-partial", _URL],
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            main()

        generated_articles = generator.gen_issue.call_args.args[0]
        self.assertEqual(1, len(generated_articles))
        self.assertEqual(_URL, generator.gen_issue.call_args.kwargs["source_url"])
        self.assertTrue(
            generator.gen_issue.call_args.kwargs["output_path"].endswith(
                "-partial.epub"
            )
        )
        self.assertIn("部分重建", output.getvalue())

    def test_single_flag_rejects_issue_source(self) -> None:
        """--single 期望文章页；期次目录应报类型冲突。"""
        crawler = _crawler()
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator"),
            patch(
                "sys.argv",
                ["qstheory2pdf", "--format", "epub", "--single", _URL],
            ),
            redirect_stdout(io.StringIO()),
            patch("sys.stderr", new_callable=io.StringIO) as err,
        ):
            with self.assertRaises(SystemExit) as error:
                main()

        self.assertEqual(1, error.exception.code)
        self.assertIn("来源不是文章", err.getvalue())
        crawler.fetch_info.assert_not_called()


class YearIndexModeTest(unittest.TestCase):
    def test_year_issue_links_are_sorted_and_require_multiple_issues(self) -> None:
        entries = [
            {
                "title": "《求是》2026年第12期",
                "column": "",
                "subtitle": "",
                "author": "",
                "author_role": "",
                "url": "https://example.com/12",
            },
            {
                "title": "《求是》2026年第2期",
                "column": "",
                "subtitle": "",
                "author": "",
                "author_role": "",
                "url": "https://example.com/2",
            },
        ]

        self.assertEqual(
            [
                ("2026", 2, "https://example.com/2"),
                ("2026", 12, "https://example.com/12"),
            ],
            _year_issue_links(entries),
        )
        self.assertEqual([], _year_issue_links(entries[:1]))

    def test_year_index_generates_one_epub_per_issue(self) -> None:
        year_url = "https://www.qstheory.cn/20251231/year/c.html"
        issue_urls = [
            "https://www.qstheory.cn/20251231/issue1/c.html",
            "https://www.qstheory.cn/20260115/issue2/c.html",
        ]
        year_toc = {
            "urls": issue_urls,
            "entries": [
                {
                    "title": f"《求是》2026年第{index}期",
                    "column": "",
                    "subtitle": "",
                    "author": "",
                    "author_role": "",
                    "url": url,
                }
                for index, url in enumerate(issue_urls, 1)
            ],
        }
        issue_tocs = [
            {
                "urls": [
                    issue_urls[0].replace("issue1", f"article{index}")
                    for index in (1, 2)
                ],
                "entries": [],
            },
            {
                "urls": [
                    issue_urls[1].replace("issue2", f"article{index}")
                    for index in (1, 2)
                ],
                "entries": [],
            },
        ]
        crawler = Mock()
        crawler.fetch_toc.side_effect = [year_toc, *issue_tocs]
        crawler.fetch_info.side_effect = [_ARTICLE] * 4
        crawler.download_toc_cover.return_value = None
        generator = Mock()
        generator.gen_issue.side_effect = lambda *args, **kwargs: kwargs["output_path"]

        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
                patch(
                    "qstheory2pdf.entry.EPUBGenerator",
                    return_value=generator,
                ),
                patch(
                    "sys.argv",
                    [
                        "qstheory2pdf",
                        "--format",
                        "epub",
                        "-o",
                        output_dir,
                        year_url,
                    ],
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                main()

            output_paths = [
                call.kwargs["output_path"]
                for call in generator.gen_issue.call_args_list
            ]
            self.assertEqual(
                [
                    str(Path(output_dir) / "求是_2026_01.epub"),
                    str(Path(output_dir) / "求是_2026_02.epub"),
                ],
                output_paths,
            )
            self.assertIn("期次目录集模式: 共 2 期", output.getvalue())


if __name__ == "__main__":
    unittest.main()
