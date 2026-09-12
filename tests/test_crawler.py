"""爬虫图片缓存与元数据回退测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

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
        return crawler.fetch_info("https://www.qstheory.cn/20260801/hash/c.html")

    def test_unsigned_article_keeps_every_body_paragraph(self) -> None:
        # Same structure as the 2026/17 本期导读: no repeated title or byline.
        info = self._fetch(
            '<h1>本期导读</h1><div class="content">'
            '<p>首段正文。</p><p>第二段正文。</p></div>'
        )
        self.assertEqual(
            ["首段正文。", "第二段正文。"],
            [block["text"] for block in info["content"]],
        )

    def test_preamble_is_removed_only_before_body_starts(self) -> None:
        cases = [
            ('<p>测试标题</p><p>正文。</p>', '', ["正文。"]),
            ('<p>测试标题<sup>※</sup></p><p>测 试作者</p><p>正文。</p>',
             '测试作者', ["正文。"]),
            ('<p>正文。</p><p>测试作者</p>', '测试作者', ["正文。", "测试作者"]),
            ('<p>正文。</p><p style="text-align:center">——正文中的引文</p>',
             '', ["正文。", "——正文中的引文"]),
        ]
        for body, author, expected in cases:
            with self.subTest(body=body):
                info = self._fetch(
                    f'<h1>测试标题</h1><meta name="author" content="{author}">'
                    f'<div class="content">{body}</div>'
                )
                self.assertEqual(expected, [b["text"] for b in info["content"]])

    def test_title_and_subtitle_without_body_are_not_content(self) -> None:
        info = self._fetch(
            '<h1>测试标题</h1><div class="content"><p>测试标题</p>'
            '<p style="text-align:center"><strong>——副标题</strong></p></div>'
        )
        self.assertEqual("——副标题", info["subtitle"])
        self.assertEqual([], info["content"])

    def test_split_column_title_and_byline_are_not_body(self) -> None:
        # The 2026/17 interview has a combined h1 but three heading paragraphs.
        for separator in ("│", "|", "｜"):
            for author in ("《求是》杂志记者 侯亚景", ""):
                with self.subTest(separator=separator, author=author):
                    byline = f'<p style="text-align:center">{author}</p>' if author else ''
                    info = self._fetch(
                        f'<h1>求是专访 {separator} 着力打通制约国内大循环的卡点堵点</h1>'
                        f'<meta name="author" content="{author}">'
                        '<div class="content"><p><strong>求是专访</strong></p><p> </p>'
                        '<p style="text-align:center"><strong>'
                        '着力打通制约国内大循环的卡点堵点<sup>※</sup></strong></p>'
                        f'{byline}<p><strong>编者按：</strong>这是正文首段。</p>'
                        '<p>记者：这是正文第二段。</p></div>'
                    )
                    self.assertEqual(
                        ["编者按：这是正文首段。", "记者：这是正文第二段。"],
                        [block["text"] for block in info["content"]],
                    )

    def test_unconfirmed_column_does_not_swallow_body(self) -> None:
        for body in (
            '<p>求是专访</p><p>这是真正的正文，不能跳过。</p><p>测试作者</p>',
            '<p>正文先开始。</p><p>求是专访</p><p>测试标题</p><p>测试作者</p>',
            '<p>求是专访</p><p><img src="figure.png"></p><p>测试标题</p>',
        ):
            with self.subTest(body=body), patch.object(
                QiuShiCrawler, "_download_img", return_value="figure.png"
            ):
                info = self._fetch(
                    '<h1>求是专访│测试标题</h1><meta name="author" content="测试作者">'
                    f'<div class="content">{body}</div>'
                )
                self.assertEqual(
                    "正文先开始。" if body.startswith('<p>正文') else "求是专访",
                    info["content"][0]["text"],
                )
                if '<img' in body:
                    self.assertEqual("figure.png", info["content"][1]["img"])

    def test_split_heading_without_body_remains_empty(self) -> None:
        info = self._fetch(
            '<h1>求是专访│测试标题</h1><meta name="author" content="测试作者">'
            '<div class="content"><p>求是专访</p><p>测试标题</p><p>测试作者</p></div>'
        )
        self.assertEqual([], info["content"])

    def test_column_prefix_in_h1_does_not_require_column_paragraph(self) -> None:
        info = self._fetch(
            '<h1>求是专访│测试标题</h1><meta name="author" content="测试作者">'
            '<div class="content"><p>测试标题</p><p>测试作者</p><p>正文。</p></div>'
        )
        self.assertEqual(["正文。"], [b["text"] for b in info["content"]])

    def test_unsigned_image_article_keeps_first_figure(self) -> None:
        with patch.object(QiuShiCrawler, "_download_img", return_value="figure.png"):
            info = self._fetch(
                '<h1>统计图表</h1><div class="content">'
                '<p><img src="figure.png"></p><p>图表说明。</p></div>'
            )
        self.assertEqual("figure.png", info["content"][0]["img"])

    def test_source_id_comes_from_url_hash(self) -> None:
        crawler = QiuShiCrawler()
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text=(
                    "<html><head><meta property='og:title' content='t'/></head>"
                    "<body><div class='content'><p>正文</p></div></body></html>"
                ),
                encoding="",
            )
        )
        url = (
            "https://www.qstheory.cn/20260801/"
            "0123456789abcdef0123456789abcdef/c.html"
        )
        info = crawler.fetch_info(url)
        self.assertEqual("0123456789abcdef0123456789abcdef", info["source_id"])
        # 非 32 位十六进制 URL 不产生来源标识。
        info_bad = crawler.fetch_info("https://www.qstheory.cn/20260801/hash/c.html")
        self.assertEqual("", info_bad["source_id"])

    def test_date_comes_from_official_meta_only(self) -> None:
        """日期只取官方字段；URL 路径日期不得冒充发布日期。"""
        crawler = QiuShiCrawler()
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text=(
                    "<html><head>"
                    "<meta property='og:title' content='t'/>"
                    "<meta name='publishdate' content='2026-08-02 10:00'/>"
                    "</head><body><div class='content'><p>正文</p></div></body></html>"
                ),
                encoding="",
            )
        )
        info = crawler.fetch_info(
            "https://www.qstheory.cn/20260801/0123456789abcdef0123456789abcdef/c.html"
        )
        self.assertEqual("2026-08-02", info["date"])

        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text=(
                    "<html><head><meta property='og:title' content='t'/></head>"
                    "<body><div class='content'><p>正文</p></div></body></html>"
                ),
                encoding="",
            )
        )
        info_no_date = crawler.fetch_info(
            "https://www.qstheory.cn/20260801/0123456789abcdef0123456789abcdef/c.html"
        )
        self.assertEqual("", info_no_date["date"])

    def test_toc_preserves_duplicate_entry_positions(self) -> None:
        """同一文章出现在目录多个位置时全部保留，且带官方期次日期。"""
        crawler = QiuShiCrawler()
        shared = "https://www.qstheory.cn/20260801/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/c.html"
        other = "https://www.qstheory.cn/20260801/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/c.html"
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text=(
                    f"<html><head><meta name='publishdate' content='2026-08-01'/></head>"
                    "<body><div class='content'>"
                    f"<p><a href='{shared}'><strong>第一处</strong></a></p>"
                    f"<p><a href='{other}'><strong>第二篇</strong></a></p>"
                    f"<p><a href='{shared}'><strong>第三处</strong></a></p>"
                    "</div></body></html>"
                ),
                encoding="",
            )
        )
        toc = crawler.fetch_toc("https://www.qstheory.cn/20260801/toc/c.html")
        self.assertEqual([shared, other, shared], toc["urls"])
        self.assertEqual(3, len(toc["entries"]))
        self.assertEqual("2026-08-01", toc["issue_date"])

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
        self.assertEqual(
            "https://www.qstheory.cn/20260801/hash/c.html",
            info["url"],
        )
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
                <p><strong>一、编号标题</strong></p>
                <p style="text-align: center"><strong>居中标题</strong></p>
                <p style="text-align: center"><strong>一</strong></p>
                <p><strong>普通粗体强调</strong></p>
                <p>某单位 测试作者</p>
              </div>
            </body></html>
            """
        )

        blocks = [block for block in info["content"] if "text" in block]
        self.assertEqual(
            [
                "salutation",
                "section_heading",
                "section_heading",
                "section_heading",
                "body",
                "signature",
            ],
            [block["role"] for block in blocks],
        )


if __name__ == "__main__":
    unittest.main()
