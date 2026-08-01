"""CLI entry point for qstheory2pdf."""

import argparse
import json
import os
import re
import sys
import tempfile

# Windows 终端常用 GBK；嵌入式调用中的 StringIO 则没有 reconfigure。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

from qstheory2pdf import EPUBGenerator, PDFGenerator, QiuShiCrawler
from qstheory2pdf.gen_pdf import _safe_name
from qstheory2pdf.types import Article, TocEntry, TocResult

_YEAR_ISSUE_RE = re.compile(r"(\d{4})年第(\d+)期")


class IssueBuildError(RuntimeError):
    """Raised when one issue cannot be built completely enough to publish."""


def _article_problems(info: Article) -> list[tuple[str, str]]:
    """Return (code, message) pairs for a fetched article's completeness gaps.

    A complete article needs a source article ID, a non-empty title and at
    least one substantive body block (CONTEXT.md). Byline, subtitle and
    dates may legitimately be absent.
    """
    problems: list[tuple[str, str]] = []
    if not info.get("source_id"):
        problems.append(("missing_source_id", "缺少来源文章标识"))
    if not (info.get("title") or "").strip():
        problems.append(("missing_title", "缺少标题"))
    if not info.get("content"):
        problems.append(("empty_content", "未提取到正文"))
    return problems


def _problems_message(prefix: str, problems: list[dict]) -> str:
    labels = "、".join(
        f"{p.get('code', '')}: {p.get('message', '')}" for p in problems
    )
    return f"{prefix}：{labels}"


def _partial_path(path: str) -> str:
    """Insert a -partial marker before the file extension."""
    base, extension = os.path.splitext(path)
    return f"{base}-partial{extension}"


def _materialize_default_paths(
    args: argparse.Namespace,
    base_name: str,
    pdf_output: str | None,
    epub_output: str | None,
) -> tuple[str | None, str | None]:
    """Fill generator default output paths so -partial marking applies to them.

    Mirrors the generators' own default naming (output/<safe-name>.<ext>) so
    complete builds produce identical paths, while partial builds can append
    the marker uniformly.
    """
    safe = _safe_name(base_name)
    if args.format in ("pdf", "both") and pdf_output is None:
        pdf_output = os.path.join("output", safe + ".pdf")
    if args.format in ("epub", "both") and epub_output is None:
        epub_output = os.path.join("output", safe + ".epub")
    return pdf_output, epub_output


def _year_issue_links(entries: list[TocEntry]) -> list[tuple[str, int, str]]:
    """Extract and sort issue links from a year-index page.

    Requiring at least two distinct issue numbers prevents an ordinary
    article or issue TOC from being mistaken for a year index merely because
    its text happens to mention one issue number.
    """
    issues: dict[tuple[str, int], str] = {}
    for entry in entries:
        match = _YEAR_ISSUE_RE.search(entry.get("title", ""))
        url = entry.get("url", "")
        if not match or not url:
            continue
        year, number = match.group(1), int(match.group(2))
        issues[(year, number)] = url
    if len(issues) < 2:
        return []
    return [
        (year, number, issues[(year, number)])
        for year, number in sorted(issues)
    ]


def _output_paths(
    output_format: str,
    requested: str | None,
) -> tuple[str | None, str | None]:
    """根据输出格式解析 PDF 与 EPUB 的目标路径。"""
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qstheory2pdf",
        description="将求是网文章/整期杂志转换为 PDF 或 EPUB",
        epilog=(
            "示例: qstheory2pdf --format epub "
            "https://www.qstheory.cn/.../c.html"
        ),
    )
    parser.add_argument("url", help="文章或目录页URL")
    parser.add_argument(
        "-d", "--device",
        choices=["normal", "pad", "kindle", "screen", "pc", "scribe"],
        default="normal",
        help="阅读设备 (默认: normal)",
    )
    parser.add_argument(
        "-f", "--font",
        choices=["auto", "wenkai"],
        default="auto",
        help="字体方案: auto=开源字体自动探测(默认), wenkai=全文霞鹜文楷",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出路径；both 时作为基础路径；年度索引模式下作为输出目录",
    )
    parser.add_argument(
        "--format",
        choices=["pdf", "epub", "both"],
        default="pdf",
        help="输出格式: pdf（默认）、epub 或 both",
    )
    parser.add_argument(
        "-s", "--single",
        action="store_true",
        help="期望输入为文章页；输入期次目录或期次目录集时直接报错",
    )
    completeness = parser.add_mutually_exclusive_group()
    completeness.add_argument(
        "--strict",
        action="store_true",
        help="（已弃用）默认行为即为拒绝不完整重建；此参数仅作别名保留",
    )
    completeness.add_argument(
        "--allow-partial",
        action="store_true",
        help="允许生成部分重建产物：文件名追加 -partial，并在终端与状态文件中标记",
    )
    parser.add_argument(
        "--status-file",
        default=None,
        metavar="PATH",
        help="输出机器可读的重建状态 JSON（state/problems/outputs）",
    )
    return parser


def _issue_completeness_error(problems: list[dict]) -> str:
    """返回整期不完整错误；完整时返回空字符串。"""
    if not problems:
        return ""
    return _problems_message("整期内容不完整", problems)


def _generate_issue(
    crawler: QiuShiCrawler,
    toc_url: str,
    toc: TocResult,
    args: argparse.Namespace,
    pdf_output: str | None,
    epub_output: str | None,
) -> tuple[list[tuple[str, str]], list[dict]]:
    """Download and generate one complete issue.

    Returns (generated, problems). The official TOC decides membership: every
    listed position is downloaded (duplicates kept), and the issue is complete
    only when every position yields a complete article. Partial issues are
    rejected by default and generated with a -partial marker only when
    --allow-partial is given.
    """
    article_urls = list(toc.get("urls", []))
    if len(article_urls) < 2:
        raise IssueBuildError("目录页没有识别到足够的文章链接")

    pdf_gen: PDFGenerator | None = None
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.format in ("pdf", "both"):
        pdf_gen = PDFGenerator(device=args.device, font=args.font)
        image_dir = pdf_gen.start()
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="qiushi_epub_")
        image_dir = os.path.join(temp_dir.name, "img")
        os.makedirs(image_dir, exist_ok=True)

    try:
        crawler.image_dir = image_dir
        entry_by_url = {e["url"]: e for e in toc.get("entries", [])}
        missing = [url for url in article_urls if url not in entry_by_url]
        if missing:
            print(f"提示: {len(missing)} 个链接缺少目录条目，将使用文章页标题")
        print(f"整期模式: 共 {len(article_urls)} 篇文章")

        articles = []
        matched_toc = []
        problems: list[dict] = []
        for i, url in enumerate(article_urls, 1):
            print(f"  [{i}/{len(article_urls)}] 下载中...", end=" ")
            try:
                info = crawler.fetch_info(url, with_qr=False)
            except requests.RequestException as error:
                print(f"跳过 (下载失败: {error})")
                problems.append({"code": "download_failed", "message": f"下载失败: {error}", "url": url})
                continue
            if not info.get("content"):
                print("跳过 (无内容)")
                problems.append({"code": "empty_content", "message": "未提取到正文", "url": url})
                continue
            for code, message in _article_problems(info):
                problems.append({"code": code, "message": message, "url": url})
            entry = entry_by_url.get(url) or {
                "title": info.get("title", ""),
                "column": "",
                "subtitle": info.get("subtitle", ""),
                "author": info.get("author", ""),
                "author_role": "",
                "url": url,
            }
            articles.append(info)
            matched_toc.append(entry)
            print(info["title"][:30])

        completeness_error = _issue_completeness_error(problems)
        if completeness_error and not args.allow_partial:
            raise IssueBuildError(completeness_error)
        if not articles:
            raise IssueBuildError("未能下载任何文章")

        if problems:
            print(f"警告: 部分重建 — {'、'.join(p['message'] for p in problems)}")
        issue_vol = articles[0].get("volume", "")
        issue_date = toc.get("issue_date", "")
        # 物化默认路径（与生成器默认命名一致），再统一追加 -partial 标记。
        pdf_output, epub_output = _materialize_default_paths(
            args, issue_vol, pdf_output, epub_output
        )
        if problems:
            if pdf_output:
                pdf_output = _partial_path(pdf_output)
            if epub_output:
                epub_output = _partial_path(epub_output)

        try:
            cover_img = crawler.download_toc_cover(toc_url)
        except requests.RequestException as error:
            print(f"警告: 封面下载失败，使用默认扉页 ({error})")
            cover_img = None

        generated: list[tuple[str, str]] = []
        if pdf_gen is not None:
            print(f"生成 PDF ({len(articles)} 篇)...")
            output = pdf_gen.gen_issue(
                articles,
                issue_volume=issue_vol,
                issue_date=issue_date,
                toc_entries=matched_toc,
                cover_image=cover_img,
                output_path=pdf_output,
            )
            generated.append(("PDF", output))
        if args.format in ("epub", "both"):
            print(f"生成 EPUB ({len(articles)} 篇)...")
            output = EPUBGenerator(image_dir).gen_issue(
                articles,
                issue_volume=issue_vol,
                issue_date=issue_date,
                toc_entries=matched_toc,
                cover_image=cover_img,
                output_path=epub_output,
                source_url=toc_url,
            )
            generated.append(("EPUB", output))
        return generated, problems
    finally:
        if pdf_gen is not None:
            pdf_gen.finish()
        if temp_dir is not None:
            temp_dir.cleanup()


def _generate_single(
    crawler: QiuShiCrawler,
    args: argparse.Namespace,
    pdf_output: str | None,
    epub_output: str | None,
) -> tuple[list[tuple[str, str]], list[dict]]:
    """Generate one article in the requested format(s).

    Returns (generated, problems). A single article is complete only with a
    source article ID, a non-empty title and at least one body block; partial
    articles are rejected by default and marked -partial under --allow-partial.
    """
    pdf_gen: PDFGenerator | None = None
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.format in ("pdf", "both"):
        pdf_gen = PDFGenerator(device=args.device, font=args.font)
        image_dir = pdf_gen.start()
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="qiushi_epub_")
        image_dir = os.path.join(temp_dir.name, "img")
        os.makedirs(image_dir, exist_ok=True)

    try:
        crawler.image_dir = image_dir
        print(f"单篇文章模式: {args.url}")
        info = crawler.fetch_info(args.url, with_qr=True)
        problems = [
            {"code": code, "message": message, "url": args.url}
            for code, message in _article_problems(info)
        ]
        if problems and not args.allow_partial:
            raise IssueBuildError(_problems_message("文章重建不完整", problems))
        if problems:
            print(f"警告: 部分重建 — {'、'.join(p['message'] for p in problems)}")
        # 物化默认路径（与生成器默认命名一致），再统一追加 -partial 标记。
        pdf_output, epub_output = _materialize_default_paths(
            args, info.get("title", ""), pdf_output, epub_output
        )
        if problems:
            if pdf_output:
                pdf_output = _partial_path(pdf_output)
            if epub_output:
                epub_output = _partial_path(epub_output)

        generated: list[tuple[str, str]] = []
        if pdf_gen is not None:
            generated.append(("PDF", pdf_gen.gen_single(info, pdf_output)))
        if args.format in ("epub", "both"):
            generated.append(
                ("EPUB", EPUBGenerator(image_dir).gen_single(info, epub_output))
            )
        return generated, problems
    finally:
        if pdf_gen is not None:
            pdf_gen.finish()
        if temp_dir is not None:
            temp_dir.cleanup()


def _write_status_file(path: str, state: str, problems: list[dict], outputs: list[tuple[str, str]]) -> None:
    """Write a machine-readable reconstruction status JSON."""
    payload = {
        "state": state,
        "problems": problems,
        "outputs": [{"format": kind, "path": path} for kind, path in outputs],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.strict:
        print(
            "提示: --strict 已弃用；默认行为即为拒绝不完整重建。"
            "如需允许部分重建请使用 --allow-partial。",
            file=sys.stderr,
        )
    pdf_output, epub_output = _output_paths(args.format, args.output)
    crawler = QiuShiCrawler()

    toc: TocResult | None = None
    year_issues: list[tuple[str, int, str]] = []
    if args.single:
        # --single 语义：期望输入为文章页；来源类型不能被操作模式改写。
        toc = crawler.fetch_toc(args.url)
        year_issues = _year_issue_links(toc["entries"])
        if year_issues or len(toc.get("urls", [])) >= 2:
            print(
                "错误: 来源不是文章：给定 URL 是期次目录或期次目录集"
                "（--single 只接受文章页）",
                file=sys.stderr,
            )
            sys.exit(1)
        mode = "single"
    else:
        toc = crawler.fetch_toc(args.url)
        year_issues = _year_issue_links(toc["entries"])
        if year_issues:
            mode = "year"
        else:
            mode = "issue" if len(toc.get("urls", [])) >= 2 else "single"

    generated: list[tuple[str, str]] = []
    all_problems: list[dict] = []
    try:
        if mode == "single":
            issue_generated, problems = _generate_single(
                crawler, args, pdf_output, epub_output
            )
            generated.extend(issue_generated)
            all_problems.extend(problems)
        elif mode == "issue":
            assert toc is not None
            issue_generated, problems = _generate_issue(
                crawler,
                args.url,
                toc,
                args,
                pdf_output,
                epub_output,
            )
            generated.extend(issue_generated)
            all_problems.extend(problems)
        else:
            output_dir = os.path.abspath(args.output or "output")
            os.makedirs(output_dir, exist_ok=True)
            print(f"期次目录集模式: 共 {len(year_issues)} 期，输出目录: {output_dir}")
            failed_issues: list[tuple[str, int]] = []
            for index, (year, number, issue_url) in enumerate(year_issues, 1):
                label = f"求是_{year}_{number:02d}"
                print(f"\n[{index}/{len(year_issues)}] 生成 {year} 年第 {number} 期")
                base = os.path.join(output_dir, label)
                issue_pdf = base + ".pdf" if args.format in ("pdf", "both") else None
                issue_epub = (
                    base + ".epub" if args.format in ("epub", "both") else None
                )
                try:
                    issue_toc = crawler.fetch_toc(issue_url)
                    issue_generated, problems = _generate_issue(
                        crawler,
                        issue_url,
                        issue_toc,
                        args,
                        issue_pdf,
                        issue_epub,
                    )
                    generated.extend(issue_generated)
                    all_problems.extend(problems)
                except (IssueBuildError, requests.RequestException) as error:
                    print(f"错误: {year} 年第 {number} 期生成失败: {error}")
                    failed_issues.append((year, number))
                    all_problems.append(
                        {
                            "code": "issue_failed",
                            "message": f"{year}年第{number}期生成失败: {error}",
                            "url": issue_url,
                        }
                    )

            if failed_issues:
                labels = "、".join(
                    f"{year}年第{number}期" for year, number in failed_issues
                )
                print(f"警告: 以下期号生成失败：{labels}")
            if not generated:
                raise IssueBuildError("全年没有成功生成任何文件")
    except IssueBuildError as error:
        print(f"错误: {error}")
        if args.status_file:
            _write_status_file(
                args.status_file,
                "failed",
                [{"code": "build_error", "message": str(error)}],
                [],
            )
        sys.exit(1)

    for kind, path in generated:
        print(f"{kind} 已生成: {path}")
    if all_problems:
        print(f"警告: 本次重建为部分重建，共 {len(all_problems)} 项问题")
        state = "partial"
    else:
        state = "complete"
    if args.status_file:
        _write_status_file(args.status_file, state, all_problems, generated)
    if mode == "year" and any(
        p.get("code") == "issue_failed" for p in all_problems
    ):
        print("错误: 期次目录集中存在生成失败的期次，整体退出非零", file=sys.stderr)
        sys.exit(1)
    print("完成!")


if __name__ == "__main__":
    main()
