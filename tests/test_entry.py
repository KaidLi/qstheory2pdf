"""CLI 整期完整性策略测试。"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import requests

from qstheory2pdf.entry import main
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


if __name__ == "__main__":
    unittest.main()
