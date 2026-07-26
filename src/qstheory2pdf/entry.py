"""CLI entry point for qstheory2pdf."""

import argparse
import re
import sys

# Force UTF-8 output on Windows, where the terminal defaults to GBK
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

from qstheory2pdf import QiuShiCrawler, PDFGenerator


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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qstheory2pdf",
        description="将求是网文章/整期杂志转换为PDF",
        epilog="示例: qstheory2pdf -d scribe https://www.qstheory.cn/.../c.html",
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
        help="输出PDF路径 (默认自动命名)",
    )
    parser.add_argument(
        "-s", "--single",
        action="store_true",
        help="强制按单篇文章模式处理",
    )
    args = parser.parse_args()

    # ---- determine mode (single fetch, no images needed) ------------------
    crawler = QiuShiCrawler()
    if args.single:
        mode = "single"
    else:
        toc = crawler.fetch_toc(args.url)
        article_urls = _issue_article_urls(args.url, toc["urls"])
        mode = "issue" if len(article_urls) >= 2 else "single"

    # ---- single article ---------------------------------------------------
    if mode == "single":
        print(f"单篇文章模式: {args.url}")
        pdf_gen = PDFGenerator(device=args.device, font=args.font)
        image_dir = pdf_gen.start()
        try:
            crawler.image_dir = image_dir
            info = crawler.fetch_info(args.url, with_qr=True)
            if not info.get("content"):
                print("错误: 未能提取到文章内容")
                sys.exit(1)
            output = pdf_gen.gen_single(info, args.output)
        finally:
            pdf_gen.finish()
        print(f"PDF已生成: {output}")
        return

    # ---- full issue -------------------------------------------------------
    # Walk article_urls (page order); entries may miss rows whose TOC line
    # had no <strong> title — synthesize those from the article page itself
    # instead of silently dropping the article.
    entry_by_url = {e["url"]: e for e in toc["entries"]}
    missing = [u for u in article_urls if u not in entry_by_url]
    if missing:
        print(f"提示: {len(missing)} 个链接缺少目录条目，将使用文章页标题")
    print(f"整期模式: 共 {len(article_urls)} 篇文章")

    pdf_gen = PDFGenerator(device=args.device, font=args.font)
    image_dir = pdf_gen.start()
    try:
        crawler.image_dir = image_dir
        articles = []
        matched_toc = []
        failed = []
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
            print(f"警告: {len(failed)} 篇文章下载失败，未包含在PDF中")

        if not articles:
            print("错误: 未能下载任何文章")
            sys.exit(1)

        # extract issue volume/date from first article (now well-defined;
        # see qstheory2pdf.types.Article for the schema)
        issue_vol = articles[0].get("volume", "")
        issue_date = articles[0].get("date", "")

        # download TOC page cover image for title page (optional — fall back
        # to the generated text title page on failure)
        try:
            cover_img = crawler.download_toc_cover(args.url)
        except requests.RequestException as e:
            print(f"警告: 封面下载失败，使用默认扉页 ({e})")
            cover_img = None

        print(f"生成PDF ({len(articles)}篇)...")
        output = pdf_gen.gen_issue(
            articles,
            issue_volume=issue_vol,
            issue_date=issue_date,
            toc_entries=matched_toc,
            cover_image=cover_img,
            output_path=args.output,
        )
    finally:
        pdf_gen.finish()
    print(f"PDF已生成: {output}")
    print("完成!")


if __name__ == "__main__":
    main()
