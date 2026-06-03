"""CLI entry point for qstheory2pdf."""

import argparse
import sys

# Force UTF-8 output on Windows, where the terminal defaults to GBK
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

    # ---- determine mode (single fetch, no images needed) ------------------
    crawler = QiuShiCrawler()
    if args.single:
        mode = "single"
    else:
        toc = crawler.fetch_toc(args.url)
        mode = "issue" if len(toc["urls"]) >= 2 else "single"

    # ---- single article ---------------------------------------------------
    if mode == "single":
        print(f"单篇文章模式: {args.url}")
        pdf_gen = PDFGenerator(device=args.device)
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
    toc_entries = toc["entries"]
    print(f"整期模式: 共 {len(toc_entries)} 篇文章")

    pdf_gen = PDFGenerator(device=args.device)
    image_dir = pdf_gen.start()
    try:
        crawler.image_dir = image_dir
        articles = []
        matched_toc = []
        for i, entry in enumerate(toc_entries, 1):
            url = entry["url"]
            print(f"  [{i}/{len(toc_entries)}] 下载中...", end=" ")
            info = crawler.fetch_info(url, with_qr=False)
            if info.get("content"):
                articles.append(info)
                matched_toc.append(entry)
                print(info["title"][:30])
            else:
                print("跳过 (无内容)")

        if not articles:
            print("错误: 未能下载任何文章")
            sys.exit(1)

        # extract issue volume/date from first article (now well-defined;
        # see qstheory2pdf.types.Article for the schema)
        issue_vol = articles[0].get("volume", "")
        issue_date = articles[0].get("date", "")

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
    finally:
        pdf_gen.finish()
    print(f"PDF已生成: {output}")
    print("完成!")


if __name__ == "__main__":
    main()
