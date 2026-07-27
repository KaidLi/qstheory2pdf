"""CLI entry point for qstheory2pdf."""

import argparse
import os
import re
import sys
import tempfile
from datetime import datetime

# Windows 终端常用 GBK；嵌入式调用中的 StringIO 则没有 reconfigure。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

from qstheory2pdf import EPUBGenerator, PDFGenerator, QiuShiCrawler
from qstheory2pdf.types import TocEntry, TocResult

_YEAR_ISSUE_RE = re.compile(r"(\d{4})年第(\d+)期")


class IssueBuildError(RuntimeError):
    """Raised when one issue cannot be built completely enough to publish."""


def _issue_article_urls(toc_url: str, urls: list[str]) -> list[str]:
    """Keep links published near the issue TOC's date.

    Issue pages also link back to a year index, whose URL date is months away.
    Most article URLs share the TOC date, but some issues are assembled from
    pages published the previous day, so exact date equality would discard
    valid articles (observed on 2026/13). A seven-day window keeps real issue
    content while excluding archive navigation links.
    """
    m = re.search(r"/(\d{8})/", toc_url)
    if not m:
        return urls
    toc_date = datetime.strptime(m.group(1), "%Y%m%d")
    result = []
    for url in urls:
        match = re.search(r"/(\d{8})/", url)
        if not match:
            continue
        try:
            url_date = datetime.strptime(match.group(1), "%Y%m%d")
        except ValueError:
            continue
        if abs((url_date - toc_date).days) <= 7:
            result.append(url)
    return result


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
        help="强制按单篇文章模式处理",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="整期模式下任一文章下载或解析失败即终止，不生成残缺刊物",
    )
    return parser


def _issue_completeness_error(
    failed_urls: list[str],
    empty_urls: list[str],
) -> str:
    """返回整期不完整错误；完整时返回空字符串。"""
    parts = []
    if failed_urls:
        parts.append(f"{len(failed_urls)} 篇下载失败")
    if empty_urls:
        parts.append(f"{len(empty_urls)} 篇未提取到正文")
    if not parts:
        return ""
    return "整期内容不完整：" + "，".join(parts)


def _generate_issue(
    crawler: QiuShiCrawler,
    toc_url: str,
    toc: TocResult,
    args: argparse.Namespace,
    pdf_output: str | None,
    epub_output: str | None,
) -> list[tuple[str, str]]:
    """Download and generate one complete issue."""
    article_urls = _issue_article_urls(toc_url, toc["urls"])
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
        entry_by_url = {e["url"]: e for e in toc["entries"]}
        missing = [url for url in article_urls if url not in entry_by_url]
        if missing:
            print(f"提示: {len(missing)} 个链接缺少目录条目，将使用文章页标题")
        print(f"整期模式: 共 {len(article_urls)} 篇文章")

        articles = []
        matched_toc = []
        failed = []
        empty = []
        for i, url in enumerate(article_urls, 1):
            print(f"  [{i}/{len(article_urls)}] 下载中...", end=" ")
            try:
                info = crawler.fetch_info(url, with_qr=False)
            except requests.RequestException as error:
                print(f"跳过 (下载失败: {error})")
                failed.append(url)
                continue
            if not info.get("content"):
                print("跳过 (无内容)")
                empty.append(url)
                continue
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

        if failed:
            print(f"警告: {len(failed)} 篇文章下载失败，未包含在输出中")
        if empty:
            print(f"警告: {len(empty)} 篇文章未提取到正文，未包含在输出中")
        completeness_error = _issue_completeness_error(failed, empty)
        if args.strict and completeness_error:
            raise IssueBuildError(completeness_error)
        if not articles:
            raise IssueBuildError("未能下载任何文章")

        issue_vol = articles[0].get("volume", "")
        issue_date = articles[0].get("date", "")
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
            )
            generated.append(("EPUB", output))
        return generated
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
) -> list[tuple[str, str]]:
    """Generate one article in the requested format(s)."""
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
        if not info.get("content"):
            raise IssueBuildError("未能提取到文章内容")
        generated: list[tuple[str, str]] = []
        if pdf_gen is not None:
            generated.append(("PDF", pdf_gen.gen_single(info, pdf_output)))
        if args.format in ("epub", "both"):
            generated.append(
                ("EPUB", EPUBGenerator(image_dir).gen_single(info, epub_output))
            )
        return generated
    finally:
        if pdf_gen is not None:
            pdf_gen.finish()
        if temp_dir is not None:
            temp_dir.cleanup()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    pdf_output, epub_output = _output_paths(args.format, args.output)
    crawler = QiuShiCrawler()

    toc: TocResult | None = None
    year_issues: list[tuple[str, int, str]] = []
    if args.single:
        mode = "single"
    else:
        toc = crawler.fetch_toc(args.url)
        year_issues = _year_issue_links(toc["entries"])
        if year_issues:
            mode = "year"
        else:
            article_urls = _issue_article_urls(args.url, toc["urls"])
            mode = "issue" if len(article_urls) >= 2 else "single"

    generated: list[tuple[str, str]] = []
    try:
        if mode == "single":
            generated = _generate_single(crawler, args, pdf_output, epub_output)
        elif mode == "issue":
            assert toc is not None
            generated = _generate_issue(
                crawler,
                args.url,
                toc,
                args,
                pdf_output,
                epub_output,
            )
        else:
            output_dir = os.path.abspath(args.output or "output")
            os.makedirs(output_dir, exist_ok=True)
            print(f"年度索引模式: 共 {len(year_issues)} 期，输出目录: {output_dir}")
            failed_issues = []
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
                    generated.extend(
                        _generate_issue(
                            crawler,
                            issue_url,
                            issue_toc,
                            args,
                            issue_pdf,
                            issue_epub,
                        )
                    )
                except (IssueBuildError, requests.RequestException) as error:
                    print(f"错误: {year} 年第 {number} 期生成失败: {error}")
                    failed_issues.append((year, number))
                    if args.strict:
                        raise IssueBuildError(
                            f"年度生成已在第 {number} 期停止"
                        ) from error

            if failed_issues:
                labels = "、".join(
                    f"{year}年第{number}期" for year, number in failed_issues
                )
                print(f"警告: 以下期号生成失败：{labels}")
            if not generated:
                raise IssueBuildError("全年没有成功生成任何文件")
    except IssueBuildError as error:
        print(f"错误: {error}")
        sys.exit(1)

    for kind, path in generated:
        print(f"{kind} 已生成: {path}")
    print("完成!")


if __name__ == "__main__":
    main()
