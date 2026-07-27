"""CLI entry point for qstheory2pdf."""

import argparse
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


def _issue_article_urls(toc_url: str, urls: list[str]) -> list[str]:
    """Keep only URLs sharing the TOC page's /YYYYMMDD/ date segment.

    The TOC page also links non-article pages (e.g. the year-index page,
    which carries a different date); articles of an issue share the TOC's
    publication date.
    """
    m = re.search(r"/(\d{8})/", toc_url)
    if not m:
        return urls
    seg = f"/{m.group(1)}/"
    return [u for u in urls if seg in u]


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
        help="输出路径；同时生成两种格式时作为基础路径",
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


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    pdf_output, epub_output = _output_paths(args.format, args.output)

    # ---- determine mode (single fetch, no images needed) ------------------
    crawler = QiuShiCrawler()
    if args.single:
        mode = "single"
    else:
        toc = crawler.fetch_toc(args.url)
        article_urls = _issue_article_urls(args.url, toc["urls"])
        mode = "issue" if len(article_urls) >= 2 else "single"

    pdf_gen: PDFGenerator | None = None
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.format in ("pdf", "both"):
        pdf_gen = PDFGenerator(device=args.device, font=args.font)
        image_dir = pdf_gen.start()
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="qiushi_epub_")
        image_dir = os.path.join(temp_dir.name, "img")
        os.makedirs(image_dir, exist_ok=True)

    generated: list[tuple[str, str]] = []
    try:
        crawler.image_dir = image_dir

        # ---- single article ------------------------------------------------
        if mode == "single":
            print(f"单篇文章模式: {args.url}")
            crawler.image_dir = image_dir
            info = crawler.fetch_info(args.url, with_qr=True)
            if not info.get("content"):
                print("错误: 未能提取到文章内容")
                sys.exit(1)
            if pdf_gen is not None:
                output = pdf_gen.gen_single(info, pdf_output)
                generated.append(("PDF", output))
            if args.format in ("epub", "both"):
                output = EPUBGenerator(image_dir).gen_single(info, epub_output)
                generated.append(("EPUB", output))
        else:
            # ---- full issue -------------------------------------------------
            entry_by_url = {e["url"]: e for e in toc["entries"]}
            missing = [u for u in article_urls if u not in entry_by_url]
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
                except requests.RequestException as e:
                    print(f"跳过 (下载失败: {e})")
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
                print(f"错误: {completeness_error}")
                sys.exit(1)
            if not articles:
                print("错误: 未能下载任何文章")
                sys.exit(1)

            issue_vol = articles[0].get("volume", "")
            issue_date = articles[0].get("date", "")
            try:
                cover_img = crawler.download_toc_cover(args.url)
            except requests.RequestException as e:
                print(f"警告: 封面下载失败，使用默认扉页 ({e})")
                cover_img = None

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
    finally:
        if pdf_gen is not None:
            pdf_gen.finish()
        if temp_dir is not None:
            temp_dir.cleanup()

    for kind, path in generated:
        print(f"{kind} 已生成: {path}")
    print("完成!")


if __name__ == "__main__":
    main()
