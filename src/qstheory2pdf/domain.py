"""Completeness rules shared by acquisition, CLI, and release gates."""

from __future__ import annotations

import re
from collections.abc import Mapping

from qstheory2pdf.types import (
    Article,
    Issue,
    ReconstructionProblem,
    ReconstructionStatus,
)

_SOURCE_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _problem(code: str, message: str, location: str = "") -> ReconstructionProblem:
    item: ReconstructionProblem = {"code": code, "message": message}
    if location:
        item["location"] = location
    return item


def _deduplicate(problems: list[ReconstructionProblem]) -> list[ReconstructionProblem]:
    result: list[ReconstructionProblem] = []
    seen: set[tuple[str, str, str]] = set()
    for problem in problems:
        key = (
            problem.get("code", ""),
            problem.get("message", ""),
            problem.get("location", ""),
        )
        if key not in seen:
            seen.add(key)
            result.append(problem)
    return result


def reconstruction_status(
    problems: list[ReconstructionProblem] | None = None,
) -> ReconstructionStatus:
    normalized = _deduplicate(list(problems or []))
    return {
        "state": "partial" if normalized else "complete",
        "problems": normalized,
    }


def validate_article(article: Article) -> ReconstructionStatus:
    """Apply CONTEXT.md's complete-article invariant."""
    problems = list(article.get("reconstruction", {}).get("problems", []))
    source_id = article.get("source_id", "").strip()
    if not source_id:
        problems.append(_problem("missing_source_article_id", "缺少来源文章标识"))
    elif not _SOURCE_ID_RE.fullmatch(source_id):
        problems.append(_problem("invalid_source_article_id", "来源文章标识不是官方 32 位标识"))
    if not article.get("source_url", "").strip():
        problems.append(_problem("missing_article_source", "缺少文章来源关联"))
    if not article.get("title", "").strip():
        problems.append(_problem("missing_article_title", "缺少文章标题"))

    substantive = 0
    for index, element in enumerate(article.get("body", []), 1):
        kind = element.get("kind")
        if kind == "unsupported":
            problems.append(
                _problem(
                    "unsupported_body_element",
                    element.get("reason", "正文结构尚不支持"),
                    f"body[{index}]",
                )
            )
        elif kind == "figure":
            available_images = [
                image
                for image in element.get("images", [])
                if image.get("src") and not image.get("missing")
            ]
            if available_images:
                substantive += 1
            else:
                problems.append(
                    _problem("missing_figure_images", "图版没有取得任何图像", f"body[{index}]")
                )
        elif kind == "paragraph":
            if any(run.get("text", "").strip() for run in element.get("runs", [])):
                substantive += 1
        elif kind == "list":
            if any(
                run.get("text", "").strip()
                for item in element.get("items", [])
                for run in item
            ):
                substantive += 1
        elif kind == "table":
            if any(
                run.get("text", "").strip()
                for row in element.get("rows", [])
                for cell in row
                for run in cell.get("runs", [])
            ):
                substantive += 1
        elif kind == "quote":
            if any(
                run.get("text", "").strip()
                for paragraph in element.get("paragraphs", [])
                for run in paragraph
            ):
                substantive += 1

    if substantive == 0:
        problems.append(_problem("missing_substantive_body", "未取得实质正文内容"))
    return reconstruction_status(problems)


def validate_issue(
    issue: Issue,
    articles: Mapping[str, Article],
    extra_problems: list[ReconstructionProblem] | None = None,
) -> ReconstructionStatus:
    """Apply issue identity, official-entry, and article completeness rules."""
    problems = list(issue.get("reconstruction", {}).get("problems", []))
    problems.extend(extra_problems or [])
    issue_id = issue.get("id")
    if not issue_id or issue_id.get("publication_year", 0) <= 0 \
            or issue_id.get("issue_number", 0) <= 0:
        problems.append(_problem("missing_issue_id", "缺少出版年份或期号"))
    if not issue.get("source_url", "").strip():
        problems.append(_problem("missing_issue_source", "缺少官方期次目录来源"))

    entries = issue.get("entries", [])
    if not entries:
        problems.append(_problem("missing_issue_entries", "官方期次目录没有入刊条目"))
    for expected, entry in enumerate(entries, 1):
        location = f"entries[{expected}]"
        if entry.get("ordinal") != expected:
            problems.append(_problem("invalid_issue_ordinal", "入刊条目次序不连续", location))
        source_id = entry.get("source_article_id", "")
        if not source_id:
            problems.append(_problem("missing_entry_article_id", "入刊条目缺少来源文章标识", location))
            continue
        if not _SOURCE_ID_RE.fullmatch(source_id):
            problems.append(_problem("invalid_entry_article_id", "入刊条目的来源文章标识无效", location))
            continue
        article = articles.get(source_id)
        if article is None:
            problems.append(_problem("missing_entry_article", "入刊条目没有取得文章", location))
            continue
        if article.get("source_id") != source_id:
            problems.append(_problem("entry_article_id_mismatch", "入刊条目与文章身份不一致", location))
        article_status = validate_article(article)
        if article_status["state"] == "partial":
            problems.append(_problem("partial_entry_article", "入刊条目引用的文章不完整", location))
            for article_problem in article_status["problems"]:
                nested = dict(article_problem)
                nested["location"] = f"{location}.{article_problem.get('location', 'article')}"
                problems.append(nested)

    return reconstruction_status(problems)


def problem_summary(status: ReconstructionStatus) -> str:
    return "；".join(problem.get("message", problem.get("code", "未知问题")) for problem in status["problems"])
