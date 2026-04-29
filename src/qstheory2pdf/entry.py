"""CLI entry point for qstheory2pdf."""

import argparse
import re
import sys

from qstheory2pdf import QiuShiCrawler, PDFGenerator


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

    crawler = QiuShiCrawler()
    pdf_gen = PDFGenerator(device=args.device)

    # ---- determine mode ------------------------------------------------------
    if args.single:
        mode = "single"
    else:
        urls = crawler.fetch_urls(args.url)
        mode = "issue" if len(urls) >= 2 else "single"

    # ---- single article ------------------------------------------------------
    if mode == "single":
        print(f"单篇文章模式: {args.url}")
        info = crawler.fetch_info(args.url, with_qr=True)
        if not info.get("content"):
            print("错误: 未能提取到文章内容")
            sys.exit(1)
        output = pdf_gen.gen_single(info, args.output)
        print(f"PDF已生成: {output}")

    # ---- full issue ----------------------------------------------------------
    else:
        toc_entries = crawler.fetch_toc_entries(args.url)
        urls = [e["url"] for e in toc_entries]
        print(f"整期模式: 共 {len(urls)} 篇文章")
        articles = []
        matched_toc = []  # only entries that have an article
        for i, url in enumerate(urls, 1):
            print(f"  [{i}/{len(urls)}] 下载中...", end=" ")
            info = crawler.fetch_info(url, with_qr=False)
            if info.get("content"):
                articles.append(info)
                matched_toc.append(toc_entries[i - 1])
                title = info["title"].replace(r"\ ", " ")
                title = re.sub(r"[\u200b-\u200f\u2028-\u202f\u00ad]", "", title)
                print(title[:30])
            else:
                print("跳过 (无内容)")

        if not articles:
            print("错误: 未能下载任何文章")
            sys.exit(1)

        # extract issue volume from first article
        issue_vol = articles[0].get("volume", "") if articles else ""
        issue_date = ""
        for a in articles:
            d = a.get("date", "").replace(r"\ ", " ")
            if d:
                issue_date = d[:10]
                break

        # download TOC page cover image for title page
        cover_img = crawler.download_toc_cover(args.url)

        print(f"生成PDF ({len(articles)}篇)...")
        output = pdf_gen.gen_issue(
            articles,
            issue_volume=issue_vol,
            issue_date=issue_date,
            toc_entries=matched_toc,
            cover_image=cover_img,
            output_path=args.output,
        )
        print(f"PDF已生成: {output}")

    print("完成!")


if __name__ == "__main__":
    main()
