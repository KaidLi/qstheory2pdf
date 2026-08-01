"""爬虫图片缓存与元数据回退测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

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


class CoverDownloadTest(unittest.TestCase):
    def test_prefers_largest_srcset_candidate(self) -> None:
        crawler = QiuShiCrawler()
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text="""
                <html><head>
                  <meta property="og:image" content="/fallback.jpg"/>
                </head><body><div class="content">
                  <img src="/zxcode.png"/>
                  <img src="/small.jpg" data-original="/original.jpg"
                       srcset="/medium.jpg 600w, /large.jpg 1200w"/>
                </div></body></html>
                """,
                encoding="",
            )
        )
        crawler._download_img = Mock(  # type: ignore[method-assign]
            return_value="cover.jpg"
        )

        result = crawler.download_toc_cover("https://example.com/issue/c.html")

        self.assertEqual("cover.jpg", result)
        crawler._download_img.assert_called_once_with(
            "https://example.com/large.jpg"
        )

    def test_uses_lazy_attributes_then_open_graph_fallback(self) -> None:
        crawler = QiuShiCrawler()
        crawler._download_img = Mock(  # type: ignore[method-assign]
            side_effect=["lazy.jpg", "og.jpg"]
        )
        crawler._get = Mock(  # type: ignore[method-assign]
            side_effect=[
                SimpleNamespace(
                    text=(
                        '<div class="content">'
                        '<img src="/placeholder.gif" data-src="/lazy.jpg"/>'
                        "</div>"
                    ),
                    encoding="",
                ),
                SimpleNamespace(
                    text=(
                        '<html><head><meta property="og:image" '
                        'content="/cover-og.jpg"/></head>'
                        '<body><div class="content">'
                        '<img src="/zxcode.png"/></div></body></html>'
                    ),
                    encoding="",
                ),
            ]
        )

        self.assertEqual(
            "lazy.jpg",
            crawler.download_toc_cover("https://example.com/issue/c.html"),
        )
        self.assertEqual(
            "og.jpg",
            crawler.download_toc_cover("https://example.com/issue/c.html"),
        )
        self.assertEqual(
            [
                call("https://example.com/lazy.jpg"),
                call("https://example.com/cover-og.jpg"),
            ],
            crawler._download_img.call_args_list,
        )


class MetadataFallbackTest(unittest.TestCase):
    def _fetch(self, page: str):
        crawler = QiuShiCrawler()
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(text=page, encoding="")
        )
        return crawler.fetch_info(
            "https://www.qstheory.cn/20260801/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/c.html"
        )

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
        self.assertEqual("回退作者", info["byline"])
        self.assertEqual("《求是》2026/15", info["issue_label"])
        self.assertEqual(
            "https://www.qstheory.cn/20260801/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/c.html",
            info["source_url"],
        )
        self.assertEqual(
            "正文内容",
            "".join(run["text"] for run in info["body"][0]["runs"]),
        )

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
        self.assertEqual("结构化作者", info["byline"])
        self.assertEqual("《求是》2026/16", info["issue_label"])

    def test_text_roles_distinguish_headings_salutations_and_signatures(self) -> None:
        info = self._fetch(
            """
            <html><head>
              <meta property="og:title" content="语义测试"/>
              <meta name="author" content="测试作者"/>
            </head><body>
              <div class="content">
                <p>测试作者</p>
                <p><strong>同志们：</strong></p>
                <p style="font-weight: 700">一、编号标题</p>
                <p>一、<strong>仅部分粗体</strong></p>
                <p style="text-align: center"><strong>居中标题</strong></p>
                <p style="text-align: center"><strong>一</strong></p>
                <p><strong>普通粗体强调</strong></p>
                <p style="text-align: right">资料来源：统计年鉴</p>
                <p>某单位 测试作者</p>
              </div>
            </body></html>
            """
        )

        blocks = [block for block in info["body"] if block["kind"] == "paragraph"]
        self.assertEqual(
            [
                "salutation",
                "section_heading",
                "body",
                "body",
                "section_heading",
                "body",
                "body",
                "signature",
            ],
            [block["role"] for block in blocks],
        )


if __name__ == "__main__":
    unittest.main()
