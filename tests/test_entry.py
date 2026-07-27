"""CLI 整期完整性策略测试。"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from qstheory2pdf.entry import _issue_article_urls, _year_issue_links, main
from qstheory2pdf.types import Article

_URL = "https://www.qstheory.cn/20260801/toc/c.html"
_ARTICLE_URLS = [
    "https://www.qstheory.cn/20260801/one/c.html",
    "https://www.qstheory.cn/20260801/two/c.html",
]
_ARTICLE: Article = {
    "title": "完整文章",
    "volume": "《求是》2026/15",
    "date": "2026-08-01",
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


class EntryStrictModeTest(unittest.TestCase):
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

    def test_default_mode_generates_available_articles(self) -> None:
        crawler = _crawler()
        generator = Mock()
        generator.gen_issue.return_value = "/tmp/partial.epub"
        with (
            patch("qstheory2pdf.entry.QiuShiCrawler", return_value=crawler),
            patch("qstheory2pdf.entry.EPUBGenerator", return_value=generator),
            patch("sys.argv", ["qstheory2pdf", "--format", "epub", _URL]),
            redirect_stdout(io.StringIO()),
        ):
            main()

        generated_articles = generator.gen_issue.call_args.args[0]
        self.assertEqual(1, len(generated_articles))
        self.assertEqual(_URL, generator.gen_issue.call_args.kwargs["source_url"])


class YearIndexModeTest(unittest.TestCase):
    def test_issue_links_allow_adjacent_publication_dates(self) -> None:
        toc_url = "https://www.qstheory.cn/20260701/toc/c.html"
        urls = [
            "https://www.qstheory.cn/20260701/current/c.html",
            "https://www.qstheory.cn/20260630/previous-day/c.html",
            "https://www.qstheory.cn/20251231/year-index/c.html",
        ]

        self.assertEqual(urls[:2], _issue_article_urls(toc_url, urls))

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
            self.assertIn("年度索引模式: 共 2 期", output.getvalue())


if __name__ == "__main__":
    unittest.main()
