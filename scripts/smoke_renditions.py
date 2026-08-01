#!/usr/bin/env python3
"""Build deterministic PDF/EPUB fixtures for CI rendition smoke tests."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from PIL import Image

from qstheory2pdf.domain import validate_article, validate_issue
from qstheory2pdf.gen_epub import EPUBGenerator
from qstheory2pdf.gen_pdf import PDFGenerator
from qstheory2pdf.types import Article, Issue

SOURCE_ID = "11111111111111111111111111111111"
SOURCE_URL = f"https://www.qstheory.cn/20260101/{SOURCE_ID}/c.html"


def _article(image_name: str) -> Article:
    article: Article = {
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "title": "呈现层 CI 冒烟测试",
        "byline": "测试署名",
        "body": [
            {
                "kind": "paragraph",
                "role": "body",
                "runs": [
                    {"text": "正文包含", "strong": False, "emphasis": False},
                    {"text": "强调", "strong": True, "emphasis": False},
                    {
                        "text": "与编辑链接",
                        "strong": False,
                        "emphasis": True,
                        "href": SOURCE_URL,
                    },
                    {"text": "。", "strong": False, "emphasis": False},
                ],
                "alignment": "default",
                "font_family": "",
                "font_size": 0,
            },
            {
                "kind": "list",
                "ordered": True,
                "items": [
                    [{"text": "第一项", "strong": False, "emphasis": False}],
                    [{"text": "第二项", "strong": False, "emphasis": False}],
                ],
            },
            {
                "kind": "table",
                "rows": [
                    [
                        {
                            "runs": [{"text": "项目", "strong": True, "emphasis": False}],
                            "header": True,
                            "rowspan": 1,
                            "colspan": 1,
                        },
                        {
                            "runs": [{"text": "数值", "strong": True, "emphasis": False}],
                            "header": True,
                            "rowspan": 1,
                            "colspan": 1,
                        },
                    ],
                    [
                        {
                            "runs": [{"text": "甲", "strong": False, "emphasis": False}],
                            "header": False,
                            "rowspan": 1,
                            "colspan": 1,
                        },
                        {
                            "runs": [{"text": "1", "strong": False, "emphasis": False}],
                            "header": False,
                            "rowspan": 1,
                            "colspan": 1,
                        },
                    ],
                ],
            },
            {
                "kind": "quote",
                "paragraphs": [
                    [{"text": "引文第一段。", "strong": False, "emphasis": False}],
                    [{"text": "引文第二段。", "strong": False, "emphasis": False}],
                ],
            },
            {
                "kind": "figure",
                "images": [
                    {
                        "src": image_name,
                        "alt": "测试图表",
                        "source_url": "https://www.qstheory.cn/test-chart.png",
                    }
                ],
                "caption": [
                    {"text": "图 1 测试图表", "strong": False, "emphasis": False}
                ],
            },
        ],
        "reconstruction": {"state": "complete", "problems": []},
    }
    article["reconstruction"] = validate_article(article)
    return article


def _issue(article: Article) -> Issue:
    issue: Issue = {
        "id": {"publication_year": 2026, "issue_number": 1},
        "source_url": "https://www.qstheory.cn/20260101/22222222222222222222222222222222/c.html",
        "entries": [
            {
                "ordinal": 1,
                "source_article_id": SOURCE_ID,
                "source_url": SOURCE_URL,
                "directory_title": "目录中的呈现层测试",
                "section_label": "CI 专栏",
            },
            {
                "ordinal": 2,
                "source_article_id": SOURCE_ID,
                "source_url": SOURCE_URL,
                "directory_title": "重复入刊位置",
            },
        ],
        "reconstruction": {"state": "complete", "problems": []},
    }
    issue["reconstruction"] = validate_issue(issue, {SOURCE_ID: article})
    return issue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output/ci-smoke")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_output = output_dir / "rendition-smoke.pdf"
    epub_output = output_dir / "rendition-smoke.epub"

    pdf = PDFGenerator()
    image_dir = pdf.start()
    try:
        image_name = "smoke-chart.png"
        Image.new("RGB", (320, 180), "white").save(os.path.join(image_dir, image_name))
        article = _article(image_name)
        issue = _issue(article)
        if article["reconstruction"]["state"] != "complete":
            raise RuntimeError(article["reconstruction"])
        if issue["reconstruction"]["state"] != "complete":
            raise RuntimeError(issue["reconstruction"])

        EPUBGenerator(image_dir).gen_issue(
            issue,
            {SOURCE_ID: article},
            output_path=str(epub_output),
            status=issue["reconstruction"],
        )
        pdf.gen_issue(
            issue,
            {SOURCE_ID: article},
            output_path=str(pdf_output),
            status=issue["reconstruction"],
        )
    finally:
        pdf.finish()

    for artifact in (pdf_output, epub_output):
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise RuntimeError(f"未生成有效产物: {artifact}")
        print(artifact)


if __name__ == "__main__":
    main()
