"""Discover the latest 求是 magazine issue URL.

Strategy: qstheory.cn/qs/mulu.htm → current year index → parse all issues → pick latest.

Usage:
    python scripts/discover_issue.py             # auto-discover latest
    python scripts/discover_issue.py <toc-url>   # use provided URL, extract metadata

Output: JSON with keys: url, volume, tag
"""

import json
import re
import sys
from datetime import datetime

import requests
from lxml import html

BASE = "https://www.qstheory.cn"
UA = {"User-Agent": "Mozilla/5.0"}


def _fetch_tree(url: str) -> html.HtmlElement:
    resp = requests.get(url, headers=UA, timeout=30)
    resp.encoding = "utf-8"
    return html.fromstring(resp.text)


def _extract_issue_from_page(url: str) -> dict | None:
    """Fetch a TOC page and extract the issue volume from metadata."""
    tree = _fetch_tree(url)
    for span in tree.xpath("//span[@class='appellation']"):
        text = span.text_content().strip()
        m = re.search(r"《求是》(\d{4})/(\d+)", text)
        if m:
            year, num = m.group(1), m.group(2)
            return _result(url, year, int(num))
    return None


def _result(url: str, year: str, num: int) -> dict:
    return {
        "url": url,
        "volume": f"{year}年第{num:02d}期",
        "tag": f"{year}-{num:02d}",
    }


def _discover_via_mulu() -> dict | None:
    """Discover latest issue via the official archive directory."""
    # Step 1: fetch the mulu (archive) page
    tree = _fetch_tree(BASE + "/qs/mulu.htm")

    # Step 2: find the link for the current year (e.g., "2026年")
    current_year = str(datetime.now().year)
    year_url = None
    for a_tag in tree.xpath("//a"):
        text = a_tag.text_content().strip()
        if text == current_year + "年":
            href = (a_tag.get("href") or "").strip()
            if href.startswith("/"):
                year_url = BASE + href
            elif href.startswith("http"):
                year_url = href
            break

    if not year_url:
        return None

    # Step 3: fetch the year index page and parse all issue links
    tree = _fetch_tree(year_url)

    best: tuple[int, str] | None = None  # (issue_number, url)
    for a_tag in tree.xpath("//a"):
        text = a_tag.text_content().strip()
        m = re.match(r"(\d{4})年第(\d+)期$", text)
        if not m:
            continue
        href = (a_tag.get("href") or "").strip()
        if BASE not in href:
            continue
        year, num = m.group(1), m.group(2)
        issue_num = int(num)
        if best is None or issue_num > best[0]:
            best = (issue_num, href)

    if best:
        return _result(best[1], year, best[0])
    return None


def _discover_via_homepage() -> dict | None:
    """Fallback: scrape the homepage '在线读刊' section."""
    tree = _fetch_tree(BASE + "/")
    for a_tag in tree.xpath("//a"):
        text = a_tag.text_content().strip()
        m = re.match(r"(\d{4})年第(\d+)期$", text)
        if not m:
            continue
        href = (a_tag.get("href") or "").strip()
        if BASE not in href:
            continue
        year, num = m.group(1), m.group(2)
        return _result(href, year, int(num))
    return None


def main() -> None:
    result = None

    # --- Manual URL path ---
    if len(sys.argv) > 1 and sys.argv[1].strip():
        url = sys.argv[1].strip()
        result = _extract_issue_from_page(url)
        if result is None:
            m = re.search(r"/(\d{4})(\d{2})(\d{2})/", url)
            if m:
                result = {
                    "url": url,
                    "volume": f"{m.group(1)}年{m.group(2)}月",
                    "tag": f"{m.group(1)}-{m.group(2)}",
                }

    # --- Auto-discovery ---
    if result is None:
        result = _discover_via_mulu()

    if result is None:
        result = _discover_via_homepage()

    if result is None:
        print("无法发现最新期 URL", file=sys.stderr)
        sys.exit(1)

    json.dump(result, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
