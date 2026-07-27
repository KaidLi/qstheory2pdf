"""爬虫图片缓存与元数据回退测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from qstheory2pdf.crawler import QiuShiCrawler


class ImageDownloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.image_dir = Path(self.temp.name)
        self.crawler = QiuShiCrawler(str(self.image_dir))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_same_basename_from_different_urls_does_not_collide(self) -> None:
        self.crawler._get = Mock(  # type: ignore[method-assign]
            side_effect=[
                SimpleNamespace(content=b"first"),
                SimpleNamespace(content=b"second"),
            ]
        )

        first = self.crawler._download_img("https://example.com/a/photo.jpg")
        second = self.crawler._download_img("https://example.com/b/photo.jpg")

        self.assertNotEqual(first, second)
        self.assertEqual(b"first", (self.image_dir / first).read_bytes())
        self.assertEqual(b"second", (self.image_dir / second).read_bytes())

    def test_query_string_affects_cache_key_but_not_extension(self) -> None:
        self.crawler._get = Mock(  # type: ignore[method-assign]
            side_effect=[
                SimpleNamespace(content=b"small"),
                SimpleNamespace(content=b"large"),
            ]
        )

        small = self.crawler._download_img("https://example.com/photo.png?size=small")
        large = self.crawler._download_img("https://example.com/photo.png?size=large")

        self.assertNotEqual(small, large)
        self.assertTrue(small.endswith(".png"))
        self.assertNotIn("?", small)

    def test_content_type_supplies_missing_extension(self) -> None:
        self.crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                content=b"png",
                headers={"Content-Type": "image/png; charset=binary"},
            )
        )

        name = self.crawler._download_img("https://example.com/image")

        self.assertTrue(name.endswith(".png"))


class MetadataFallbackTest(unittest.TestCase):
    def _fetch(self, page: str):
        crawler = QiuShiCrawler()
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(text=page, encoding="")
        )
        return crawler.fetch_info("https://www.qstheory.cn/20260801/hash/c.html")

    def test_open_graph_and_meta_fallbacks(self) -> None:
        info = self._fetch(
            """
            <html><head>
              <meta property="og:title" content="回退标题"/>
              <meta name="author" content="回退作者"/>
              <meta name="description" content="来源：《求是》2026/15"/>
            </head><body>
              <div class="content"><p>回退作者</p><p>正文内容</p></div>
            </body></html>
            """
        )

        self.assertEqual("回退标题", info["title"])
        self.assertEqual("回退作者", info["author"])
        self.assertEqual("《求是》2026/15", info["volume"])
        self.assertEqual("正文内容", info["content"][0]["text"])

    def test_json_ld_fallbacks(self) -> None:
        info = self._fetch(
            """
            <html><head>
              <script type="application/ld+json">
              {
                "@type": "NewsArticle",
                "headline": "结构化标题",
                "author": {"@type": "Person", "name": "结构化作者"},
                "isPartOf": {"name": "《求是》2026/16"}
              }
              </script>
            </head><body>
              <div class="content"><p>结构化作者</p><p>结构化正文</p></div>
            </body></html>
            """
        )

        self.assertEqual("结构化标题", info["title"])
        self.assertEqual("结构化作者", info["author"])
        self.assertEqual("《求是》2026/16", info["volume"])


if __name__ == "__main__":
    unittest.main()
