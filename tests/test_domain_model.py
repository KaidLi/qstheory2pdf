"""CONTEXT.md domain-contract regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from lxml import etree

from qstheory2pdf.crawler import QiuShiCrawler, SourceClassificationError
from qstheory2pdf.domain import validate_article, validate_issue


_ARTICLE_ID = "eb2be76d239d4fa4a0ef3a9a9d82b970"
_OLD_ARTICLE_ID = "11111111111111111111111111111111"
_ARTICLE_URL = f"https://www.qstheory.cn/20260415/{_ARTICLE_ID}/c.html"
_ISSUE_URL = "https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html"


class ArticleReconstructionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.crawler = QiuShiCrawler(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _document(self, page: str):
        self.crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(text=page, encoding="")
        )
        return self.crawler.fetch_document(_ARTICLE_URL)

    def test_visible_heading_identity_date_and_inline_semantics_are_preserved(self) -> None:
        document = self._document(
            """
            <html><head>
              <meta property="og:title" content="错误回退标题"/>
              <meta property="article:published_time" content="2026-04-16T08:00:00+08:00"/>
            </head><body>
              <h1>可见<strong>标题</strong></h1>
              <div class="content">
                <p>普通<strong>重点</strong><span style="font-style: italic">提示</span><a href="/ref/c.html">参见规定</a></p>
              </div>
            </body></html>
            """
        )

        self.assertEqual("article", document["kind"])
        article = document["article"]
        self.assertEqual(_ARTICLE_ID, article["source_id"])
        self.assertEqual("可见标题", article["title"])
        self.assertEqual("2026-04-16", article["source_publication_date"])
        runs = article["body"][0]["runs"]
        self.assertEqual("重点", runs[1]["text"])
        self.assertTrue(runs[1]["strong"])
        self.assertTrue(runs[2]["emphasis"])
        self.assertEqual(
            "https://www.qstheory.cn/ref/c.html",
            runs[3]["href"],
        )
        self.assertEqual("complete", validate_article(article)["state"])

    def test_missing_official_source_id_is_partial_and_has_no_surrogate(self) -> None:
        self.crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text='<html><body><h1>无标识</h1><div class="content"><p>正文</p></div></body></html>',
                encoding="",
            )
        )
        article = self.crawler.fetch_document("https://www.qstheory.cn/article/c.html")["article"]
        self.assertEqual("", article["source_id"])
        self.assertEqual("partial", article["reconstruction"]["state"])
        self.assertIn("missing_source_article_id", [p["code"] for p in article["reconstruction"]["problems"]])

    def test_url_date_is_not_a_publication_date(self) -> None:
        document = self._document(
            '<html><body><h1>无日期文章</h1><div class="content"><p>正文</p></div></body></html>'
        )
        self.assertNotIn("source_publication_date", document["article"])

    def test_lists_tables_quotes_and_unknown_substantive_structures_are_explicit(self) -> None:
        html = etree.HTML(
            f"""
            <html><body><div class="content">
              <h1>结构化正文</h1><span class="appellation">作者：甲</span>
              <ul><li>第一<strong>重点</strong></li><li>第二项</li></ul>
              <blockquote>参见<a href="https://example.com/rule">规定</a></blockquote>
              <table><tr><th colspan="2">项目</th></tr><tr><td>A</td><td>1</td></tr></table>
              <p><svg><path d="M0 0"/></svg></p>
              <video src="meaningful.mp4"></video>
            </div></body></html>
            """
        )
        article = QiuShiCrawler()._parse_article(html, _ARTICLE_URL, with_qr=False)
        self.assertEqual(
            ["list", "quote", "table", "unsupported", "unsupported"],
            [block["kind"] for block in article["body"]],
        )
        self.assertTrue(article["body"][0]["items"][0][1]["strong"])
        self.assertEqual(
            "https://example.com/rule",
            article["body"][1]["paragraphs"][0][1]["href"],
        )
        self.assertTrue(article["body"][2]["rows"][0][0]["header"])
        self.assertEqual(2, article["body"][2]["rows"][0][0]["colspan"])
        self.assertEqual("partial", article["reconstruction"]["state"])
        self.assertIn("unsupported_body_element", [p["code"] for p in article["reconstruction"]["problems"]])

    def test_images_nested_in_list_or_table_are_not_silently_flattened(self) -> None:
        document = self._document(
            '''<html><body><h1>嵌套结构</h1><div class="content">
              <ul><li>列表文字<img src="list-chart.png"/></li></ul>
              <table><tr><td>表格文字<img src="table-chart.png"/></td></tr></table>
            </div></body></html>'''
        )
        article = document["article"]
        unsupported = [
            block for block in article["body"]
            if block["kind"] == "unsupported"
        ]
        self.assertEqual(2, len(unsupported))
        self.assertEqual("partial", article["reconstruction"]["state"])

    def test_empty_table_is_not_substantive_body(self) -> None:
        document = self._document(
            '<html><body><h1>空表</h1><div class="content"><table><tr><td></td></tr></table></div></body></html>'
        )
        article = document["article"]
        self.assertEqual("partial", article["reconstruction"]["state"])
        self.assertIn(
            "missing_substantive_body",
            [problem["code"] for problem in article["reconstruction"]["problems"]],
        )

    def test_quote_preserves_multiple_paragraphs(self) -> None:
        document = self._document(
            '<html><body><h1>引文</h1><div class="content"><blockquote><p>第一段</p><p>第二段</p></blockquote></div></body></html>'
        )
        quote = document["article"]["body"][0]
        self.assertEqual("quote", quote["kind"])
        self.assertEqual(2, len(quote["paragraphs"]))
        self.assertEqual("complete", document["article"]["reconstruction"]["state"])

    def test_qr_presentation_image_is_not_substantive_body(self) -> None:
        document = self._document(
            '<html><body><h1>正文</h1><div class="content"><p>实质文字</p><img src="zxcode_article.jpg"/></div></body></html>'
        )
        article = document["article"]
        self.assertEqual(["paragraph"], [block["kind"] for block in article["body"]])
        self.assertEqual("complete", article["reconstruction"]["state"])

    def test_failed_substantive_image_is_retained_as_a_partial_placeholder(self) -> None:
        html = etree.HTML(
            f'<html><body><div class="content"><h1>图文</h1><p><img src="chart.png" alt="关键图表"/></p></div></body></html>'
        )
        crawler = QiuShiCrawler()
        crawler._download_img = Mock(side_effect=OSError("download failed"))  # type: ignore[method-assign]
        article = crawler._parse_article(html, _ARTICLE_URL, with_qr=False)
        figure = article["body"][0]
        self.assertEqual("figure", figure["kind"])
        self.assertTrue(figure["images"][0]["missing"])
        self.assertEqual("partial", article["reconstruction"]["state"])
        self.assertIn("image_download_failed", [p["code"] for p in article["reconstruction"]["problems"]])

    def test_multi_image_paragraph_is_one_figure_with_shared_caption(self) -> None:
        self.crawler._download_img = Mock(  # type: ignore[method-assign]
            side_effect=["a.png", "b.png"]
        )
        document = self._document(
            """
            <html><body><h1>图版文章</h1><div class="content">
              <p><img src="/a.png"/><img src="/b.png"/></p>
              <p><span style="font-family: 楷体">共同图注</span></p>
            </div></body></html>
            """
        )
        figure = document["article"]["body"][0]
        self.assertEqual("figure", figure["kind"])
        self.assertEqual(["a.png", "b.png"], [image["src"] for image in figure["images"]])
        self.assertEqual("共同图注", "".join(run["text"] for run in figure["caption"]))


class SourceKindTest(unittest.TestCase):
    def _fetch(self, page: str):
        response = Mock(text=page)
        response.raise_for_status = Mock()
        crawler = QiuShiCrawler()
        crawler.session.get = Mock(return_value=response)
        return crawler.fetch_document("https://www.qstheory.cn/source/c.html")

    def test_issue_link_count_does_not_turn_an_article_into_a_catalog(self) -> None:
        links = "".join(
            f'<p><a href="https://www.qstheory.cn/20260101/{str(digit) * 32}/c.html">《求是》2026年第{digit}期</a></p>'
            for digit in (1, 2)
        )
        document = self._fetch(
            f'<html><body><h1>谈全年阅读</h1><div class="content"><p>正文</p>{links}</div></body></html>'
        )
        self.assertEqual("article", document["kind"])

    def test_official_year_heading_classifies_an_issue_catalog(self) -> None:
        links = "".join(
            f'<p><a href="https://www.qstheory.cn/20260101/{str(digit) * 32}/c.html">《求是》2026年第{digit}期</a></p>'
            for digit in (1, 2)
        )
        document = self._fetch(
            f'<html><body><h1>《求是》2026年</h1><div class="content">{links}</div></body></html>'
        )
        self.assertEqual("issue_catalog", document["kind"])
        self.assertEqual([1, 2], [item["id"]["issue_number"] for item in document["catalog"]["issues"]])


class IssueReconstructionTest(unittest.TestCase):
    def test_explicit_issue_heading_with_no_entries_is_partial_not_an_article(self) -> None:
        response = Mock()
        response.text = '<html><body><h1>2026年第8期《求是》目录</h1><div class="content"><p>暂无条目</p></div></body></html>'
        response.raise_for_status = Mock()
        crawler = QiuShiCrawler()
        crawler.session.get = Mock(return_value=response)
        document = crawler.fetch_document(_ISSUE_URL)
        self.assertEqual("issue_contents", document["kind"])
        self.assertEqual("partial", document["issue"]["reconstruction"]["state"])
        self.assertIn(
            "missing_issue_entries",
            [problem["code"] for problem in document["issue"]["reconstruction"]["problems"]],
        )
        with self.assertRaisesRegex(SourceClassificationError, "来源不是文章"):
            crawler.fetch_info(_ISSUE_URL)

    def test_list_based_official_contents_keep_each_list_item(self) -> None:
        response = Mock()
        response.text = f'''<html><body><h1>2026年第8期《求是》目录</h1>
          <span class="pubtime">2026-04-16 08:00</span>
          <div class="content"><ul>
            <li><a href="{_ARTICLE_URL}">第一篇</a></li>
            <li><a href="https://www.qstheory.cn/20200101/{_OLD_ARTICLE_ID}/c.html">第二篇</a></li>
          </ul></div></body></html>'''
        response.raise_for_status = Mock()
        crawler = QiuShiCrawler()
        crawler.session.get = Mock(return_value=response)
        issue = crawler.fetch_document(_ISSUE_URL)["issue"]
        self.assertNotIn("publication_date", issue)
        self.assertEqual([1, 2], [entry["ordinal"] for entry in issue["entries"]])

    def test_issue_date_requires_an_explicit_issue_date_label(self) -> None:
        response = Mock()
        response.text = f'''<html><body><h1>2026年第8期《求是》目录</h1>
          <span>本期出版日期：2026年4月15日</span>
          <div class="content"><p><a href="{_ARTICLE_URL}">第一篇</a></p></div>
        </body></html>'''
        response.raise_for_status = Mock()
        crawler = QiuShiCrawler()
        crawler.session.get = Mock(return_value=response)
        issue = crawler.fetch_document(_ISSUE_URL)["issue"]
        self.assertEqual("2026-04-15", issue["publication_date"])

    def test_official_entries_preserve_duplicate_positions(self) -> None:
        crawler = QiuShiCrawler()
        crawler._get = Mock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(
                text=f"""
                <html><body>
                  <span class="appellation">来源：《求是》2026/08</span>
                  <div class="content">
                    <p>本刊特稿</p>
                    <p><a href="{_ARTICLE_URL}"><strong>专题栏目│目录题一</strong></a></p>
                    <p><a href="{_ARTICLE_URL}"><strong>目录题二</strong></a></p>
                    <p><a href="https://www.qstheory.cn/20200101/{_OLD_ARTICLE_ID}/c.html"><strong>来源日期很远的正式条目</strong></a></p>
                    <p><a href="https://www.qstheory.cn/20251231/2d916da295774130ac2fb223fd208895/c.html"><img src="catalog.jpg"/></a></p>
                  </div>
                </body></html>
                """,
                encoding="",
            )
        )

        document = crawler.fetch_document(_ISSUE_URL)

        self.assertEqual("issue_contents", document["kind"])
        issue = document["issue"]
        self.assertEqual({"publication_year": 2026, "issue_number": 8}, issue["id"])
        self.assertNotIn("publication_date", issue)
        self.assertEqual([1, 2, 3], [entry["ordinal"] for entry in issue["entries"]])
        self.assertEqual(
            [_ARTICLE_ID, _ARTICLE_ID, _OLD_ARTICLE_ID],
            [entry["source_article_id"] for entry in issue["entries"]],
        )
        self.assertEqual("专题栏目", issue["entries"][0]["section_label"])
        self.assertEqual("目录题一", issue["entries"][0]["directory_title"])
        self.assertNotIn("section_label", issue["entries"][1])
        self.assertEqual("partial", validate_issue(issue, {})["state"])


if __name__ == "__main__":
    unittest.main()
