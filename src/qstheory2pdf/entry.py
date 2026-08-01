"""Command-line orchestration for publication reconstruction."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

from qstheory2pdf import EPUBGenerator, PDFGenerator, QiuShiCrawler
from qstheory2pdf.crawler import SourceClassificationError
from qstheory2pdf.domain import (
    problem_summary,
    reconstruction_status,
    validate_article,
    validate_issue,
)
from qstheory2pdf.types import (
    Article,
    CatalogIssue,
    Issue,
    ReconstructionProblem,
    ReconstructionStatus,
)


class IssueBuildError(RuntimeError):
    """Raised when a requested publication cannot be reconstructed."""


class IncompleteReconstructionError(IssueBuildError):
    def __init__(self, label: str, status: ReconstructionStatus) -> None:
        super().__init__(f"{label}为部分重建：{problem_summary(status)}")
        self.status = status


def _output_paths(output_format: str, requested: str | None) -> tuple[str | None, str | None]:
    if output_format == "pdf":
        return requested, None
    if output_format == "epub":
        return None, requested
    if requested is None:
        return None, None
    base, extension = os.path.splitext(requested)
    if extension.lower() in (".pdf", ".epub"):
        requested = base
    return requested + ".pdf", requested + ".epub"


def _partial_path(path: str | None, status: ReconstructionStatus) -> str | None:
    if path is None or status["state"] != "partial":
        return path
    base, extension = os.path.splitext(path)
    if base.endswith("-partial"):
        return path
    return base + "-partial" + extension


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qstheory2pdf",
        description="重建求是网文章、期次或期次目录集，并生成 PDF/EPUB",
    )
    parser.add_argument("url", help="文章、官方期次目录或期次目录集 URL")
    parser.add_argument(
        "-d", "--device",
        choices=["normal", "pad", "kindle", "screen", "pc", "scribe"],
        default="normal",
        help="PDF 阅读设备预设",
    )
    parser.add_argument(
        "-f", "--font",
        choices=["auto", "wenkai"],
        default="auto",
        help="PDF 字体方案",
    )
    parser.add_argument("-o", "--output", default=None, help="输出路径；目录集模式下为输出目录")
    parser.add_argument(
        "--format",
        choices=["pdf", "epub", "both"],
        default="pdf",
        help="输出格式",
    )
    parser.add_argument(
        "-s", "--single",
        action="store_true",
        help="声明期望输入为文章；实际类型不符时拒绝处理",
    )
    completeness = parser.add_mutually_exclusive_group()
    completeness.add_argument(
        "--allow-partial",
        action="store_true",
        help="显式允许生成醒目标记的部分重建",
    )
    completeness.add_argument(
        "--strict",
        action="store_true",
        help="已弃用：完整重建本来就是默认要求",
    )
    parser.add_argument(
        "--status-file",
        default=None,
        help="写入机器可读的重建状态 JSON（供 CI 门禁使用）",
    )
    return parser


def _issue_label(issue: Issue) -> str:
    issue_id = issue.get("id", {})
    return f"{issue_id.get('publication_year', 0)}年第{issue_id.get('issue_number', 0):02d}期"


def _status_problem(code: str, message: str, location: str = "") -> ReconstructionProblem:
    problem: ReconstructionProblem = {"code": code, "message": message}
    if location:
        problem["location"] = location
    return problem


def _write_status_file(
    path: str | None,
    status: ReconstructionStatus,
    generated: list[tuple[str, str]],
) -> None:
    if not path:
        return
    output = os.path.abspath(path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    payload = {
        "state": status["state"],
        "problems": status["problems"],
        "outputs": [{"format": kind.lower(), "path": value} for kind, value in generated],
    }
    with open(output, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class _BuildResources:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.pdf: PDFGenerator | None = None
        self.temp: tempfile.TemporaryDirectory[str] | None = None
        self.image_dir = ""

    def start(self) -> None:
        if self.args.format in ("pdf", "both"):
            self.pdf = PDFGenerator(device=self.args.device, font=self.args.font)
            self.image_dir = self.pdf.start()
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="qiushi_epub_")
            self.image_dir = os.path.join(self.temp.name, "img")
            os.makedirs(self.image_dir, exist_ok=True)

    def close(self) -> None:
        if self.pdf is not None:
            self.pdf.finish()
        if self.temp is not None:
            self.temp.cleanup()


def _render_single(
    article: Article,
    status: ReconstructionStatus,
    args: argparse.Namespace,
    resources: _BuildResources,
    pdf_output: str | None,
    epub_output: str | None,
) -> list[tuple[str, str]]:
    if status["state"] == "partial" and not args.allow_partial:
        raise IncompleteReconstructionError("文章", status)
    pdf_output = _partial_path(pdf_output, status)
    epub_output = _partial_path(epub_output, status)
    generated: list[tuple[str, str]] = []
    if resources.pdf is not None:
        generated.append((
            "PDF",
            resources.pdf.gen_single(
                article,
                pdf_output,
                status=status,
                allow_partial=args.allow_partial,
            ),
        ))
    if args.format in ("epub", "both"):
        generated.append((
            "EPUB",
            EPUBGenerator(resources.image_dir).gen_single(
                article,
                epub_output,
                status=status,
                allow_partial=args.allow_partial,
            ),
        ))
    return generated


def _acquire_issue_articles(
    crawler: QiuShiCrawler,
    issue: Issue,
) -> tuple[dict[str, Article], list[ReconstructionProblem]]:
    articles: dict[str, Article] = {}
    problems: list[ReconstructionProblem] = []
    entries = issue.get("entries", [])
    unique_by_id: dict[str, dict] = {}
    for entry in entries:
        source_id = entry.get("source_article_id", "")
        if not source_id:
            continue
        existing = unique_by_id.get(source_id)
        if existing is None or (
            not existing.get("source_url") and entry.get("source_url")
        ):
            unique_by_id[source_id] = entry
    unique_entries = list(unique_by_id.values())

    print(f"整期模式: {len(entries)} 个入刊条目，{len(unique_entries)} 篇唯一文章")
    for index, entry in enumerate(unique_entries, 1):
        source_id = entry["source_article_id"]
        url = entry.get("source_url", "")
        print(f"  [{index}/{len(unique_entries)}] 下载中...", end=" ")
        try:
            article = crawler.fetch_info(url, with_qr=False)
        except (requests.RequestException, SourceClassificationError, OSError) as error:
            print(f"失败 ({error})")
            problems.append(
                _status_problem(
                    "article_fetch_failed",
                    f"文章下载或解析失败: {error}",
                    f"article:{source_id}",
                )
            )
            continue
        actual_id = article.get("source_id", "")
        if actual_id != source_id:
            problems.append(
                _status_problem(
                    "article_identity_mismatch",
                    f"目录标识 {source_id} 与文章标识 {actual_id or '缺失'} 不一致",
                    f"article:{source_id}",
                )
            )
            print("身份不匹配，拒绝关联")
            continue
        articles[source_id] = article
        print(article.get("title", source_id)[:30])
    return articles, problems


def _render_issue(
    crawler: QiuShiCrawler,
    issue: Issue,
    args: argparse.Namespace,
    resources: _BuildResources,
    pdf_output: str | None,
    epub_output: str | None,
) -> tuple[list[tuple[str, str]], ReconstructionStatus]:
    articles, acquisition_problems = _acquire_issue_articles(crawler, issue)
    status = validate_issue(issue, articles, acquisition_problems)
    issue["reconstruction"] = status
    if status["state"] == "partial" and not args.allow_partial:
        raise IncompleteReconstructionError(_issue_label(issue), status)

    cover_image: str | None = None
    try:
        cover_image = crawler.download_toc_cover(issue.get("source_url", ""))
    except (requests.RequestException, OSError) as error:
        print(f"提示: 封面素材不可用，使用默认扉页 ({error})")

    pdf_output = _partial_path(pdf_output, status)
    epub_output = _partial_path(epub_output, status)
    generated: list[tuple[str, str]] = []
    if resources.pdf is not None:
        generated.append((
            "PDF",
            resources.pdf.gen_issue(
                issue,
                articles,
                cover_image=cover_image,
                output_path=pdf_output,
                status=status,
                allow_partial=args.allow_partial,
            ),
        ))
    if args.format in ("epub", "both"):
        generated.append((
            "EPUB",
            EPUBGenerator(resources.image_dir).gen_issue(
                issue,
                articles,
                cover_image=cover_image,
                output_path=epub_output,
                status=status,
                allow_partial=args.allow_partial,
            ),
        ))
    return generated, status


def _catalog_output_paths(
    args: argparse.Namespace,
    catalog_issue: CatalogIssue,
) -> tuple[str | None, str | None]:
    output_dir = os.path.abspath(args.output or "output")
    os.makedirs(output_dir, exist_ok=True)
    issue_id = catalog_issue["id"]
    base = os.path.join(
        output_dir,
        f"求是_{issue_id['publication_year']}_{issue_id['issue_number']:02d}",
    )
    return (
        base + ".pdf" if args.format in ("pdf", "both") else None,
        base + ".epub" if args.format in ("epub", "both") else None,
    )


def main() -> None:
    args = _build_parser().parse_args()
    if args.strict:
        print("提示: --strict 已弃用；完整重建现在是默认行为", file=sys.stderr)

    resources = _BuildResources(args)
    resources.start()
    crawler = QiuShiCrawler(resources.image_dir)
    generated: list[tuple[str, str]] = []
    final_status = reconstruction_status()
    exit_error: str | None = None

    try:
        document = crawler.fetch_document(args.url, with_qr=True)
        if args.single and document["kind"] != "article":
            raise IssueBuildError(
                f"--single 期望文章，但来源类型是 {document['kind']}"
            )

        pdf_output, epub_output = _output_paths(args.format, args.output)
        if document["kind"] == "article":
            article = document["article"]
            final_status = validate_article(article)
            article["reconstruction"] = final_status
            generated = _render_single(
                article,
                final_status,
                args,
                resources,
                pdf_output,
                epub_output,
            )
        elif document["kind"] == "issue_contents":
            generated, final_status = _render_issue(
                crawler,
                document["issue"],
                args,
                resources,
                pdf_output,
                epub_output,
            )
        else:
            catalog = document["catalog"]
            print(f"期次目录集: 共 {len(catalog.get('issues', []))} 期")
            aggregate_problems: list[ReconstructionProblem] = []
            hard_failure = False
            for catalog_issue in catalog.get("issues", []):
                label = (
                    f"{catalog_issue['id']['publication_year']}年"
                    f"第{catalog_issue['id']['issue_number']}期"
                )
                try:
                    issue_document = crawler.fetch_document(catalog_issue["source_url"])
                    if issue_document["kind"] != "issue_contents":
                        raise IssueBuildError(f"{label}来源不是官方期次目录")
                    issue = issue_document["issue"]
                    if issue.get("id") != catalog_issue["id"]:
                        raise IssueBuildError(f"{label}目录身份与期次目录集不一致")
                    issue_pdf, issue_epub = _catalog_output_paths(args, catalog_issue)
                    outputs, status = _render_issue(
                        crawler,
                        issue,
                        args,
                        resources,
                        issue_pdf,
                        issue_epub,
                    )
                    generated.extend(outputs)
                    if status["state"] == "partial":
                        aggregate_problems.extend(status["problems"])
                except (
                    IssueBuildError,
                    requests.RequestException,
                    SourceClassificationError,
                    OSError,
                    ValueError,
                ) as error:
                    print(f"错误: {label}生成失败: {error}")
                    hard_failure = True
                    aggregate_problems.append(
                        _status_problem("catalog_issue_failed", str(error), label)
                    )
            final_status = reconstruction_status(aggregate_problems)
            if hard_failure or (aggregate_problems and not args.allow_partial):
                exit_error = "期次目录集中至少一期未能完整重建"
            if not generated:
                exit_error = "期次目录集没有生成任何出版物"

    except IncompleteReconstructionError as error:
        final_status = error.status
        exit_error = str(error)
    except (
        IssueBuildError,
        SourceClassificationError,
        requests.RequestException,
        OSError,
        ValueError,
    ) as error:
        final_status = reconstruction_status([
            _status_problem("reconstruction_failed", str(error))
        ])
        exit_error = str(error)
    finally:
        resources.close()

    _write_status_file(args.status_file, final_status, generated)
    if exit_error:
        print(f"错误: {exit_error}")
        raise SystemExit(1)
    for kind, path in generated:
        print(f"{kind} 已生成: {path}")
    print("完成!")


if __name__ == "__main__":
    main()
