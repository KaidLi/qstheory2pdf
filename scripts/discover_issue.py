"""Discover the latest 求是 magazine issue URL.

Strategy: qstheory.cn/qs/mulu.htm → current year index → parse all issues → pick latest.

Usage:
    python scripts/discover_issue.py             # auto-discover latest
    python scripts/discover_issue.py <toc-url>   # use provided URL, extract metadata

Output: JSON with keys: url, volume, tag

Network errors (timeouts, connection failures, parse errors) exit with code 2
and a clear stderr message; the GHA workflow surfaces this without a stack
trace. Exits with code 1 only when discovery cannot find a candidate URL.
"""

import json
import re
import sys
from datetime import datetime
from urllib.parse import urljoin

import requests
from lxml import html
from lxml.etree import XMLSyntaxError

from qstheory2pdf import QiuShiCrawler

BASE = "https://www.qstheory.cn"
NETWORK_TIMEOUT = 30


def _fetch_tree(session: requests.Session, url: str) -> html.HtmlElement:
    """Fetch a URL with the shared QiuShiCrawler session."""
    resp = session.get(url, timeout=NETWORK_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return html.fromstring(resp.text)


def _extract_issue_from_page(session: requests.Session, url: str) -> dict | None:
    """Fetch a TOC page and extract the issue volume from metadata."""
    tree = _fetch_tree(session, url)
    candidates = tree.xpath(
        "//h1 | //span[contains(concat(' ', normalize-space(@class), ' '), ' appellation ')]"
    )
    for element in candidates:
        text = element.text_content().strip()
        match = re.search(r"《求是》\s*(\d{4})/(\d+)", text)
        if not match:
            match = re.search(r"(?:《求是》)?\s*(\d{4})\s*年第\s*(\d+)\s*期", text)
        if match:
            year, num = match.group(1), match.group(2)
            return _result(url, year, int(num))
    return None


def _result(url: str, year: str, num: int) -> dict:
    return {
        "url": url,
        "volume": f"{year}年第{num:02d}期",
        "tag": f"qstheory-{year}-{num:02d}",
    }


def _discover_via_mulu(session: requests.Session) -> dict | None:
    """Discover latest issue via the official archive directory."""
    # Step 1: fetch the mulu (archive) page
    tree = _fetch_tree(session, BASE + "/qs/mulu.htm")

    # Step 2: find the link for the current year (e.g., "2026年")
    current_year = str(datetime.now().year)
    year_url = None
    for a_tag in tree.xpath("//a"):
        text = a_tag.text_content().strip()
        if text == current_year + "年":
            href = (a_tag.get("href") or "").strip()
            year_url = urljoin(BASE + "/", href)
            break

    if not year_url:
        return None

    # Step 3: fetch the year index page and parse all issue links
    tree = _fetch_tree(session, year_url)

    best: tuple[int, str, str] | None = None  # (issue_number, url, year)
    for a_tag in tree.xpath("//a"):
        text = a_tag.text_content().strip()
        # Link text is e.g. "《求是》2026年第14期" — anchor only at the end.
        m = re.search(r"(\d{4})年第(\d+)期$", text)
        if not m:
            continue
        href = (a_tag.get("href") or "").strip()
        issue_url = urljoin(year_url, href)
        if not issue_url.startswith(BASE + "/"):
            continue
        year, num = m.group(1), m.group(2)
        issue_num = int(num)
        if best is None or issue_num > best[0]:
            best = (issue_num, issue_url, year)

    if best:
        return _result(best[1], best[2], best[0])
    return None


def _discover_via_homepage(session: requests.Session) -> dict | None:
    """Fallback: scrape the homepage '在线读刊' section."""
    tree = _fetch_tree(session, BASE + "/")
    for a_tag in tree.xpath("//a"):
        text = a_tag.text_content().strip()
        m = re.search(r"(\d{4})年第(\d+)期$", text)
        if not m:
            continue
        href = (a_tag.get("href") or "").strip()
        issue_url = urljoin(BASE + "/", href)
        if not issue_url.startswith(BASE + "/"):
            continue
        year, num = m.group(1), m.group(2)
        return _result(issue_url, year, int(num))
    return None


def main() -> None:
    # Reuse the QiuShiCrawler session (and its User-Agent) so that header
    # configuration lives in exactly one place.
    crawler = QiuShiCrawler()
    session = crawler.session

    try:
        result = None

        # --- Manual URL path ---
        manual_url = len(sys.argv) > 1 and bool(sys.argv[1].strip())
        if manual_url:
            url = sys.argv[1].strip()
            result = _extract_issue_from_page(session, url)
            if result is None:
                print(
                    "手动 URL 没有官方声明的出版年份与期号",
                    file=sys.stderr,
                )
                sys.exit(1)

        # --- Auto-discovery ---
        if not manual_url and result is None:
            result = _discover_via_mulu(session)

        if not manual_url and result is None:
            result = _discover_via_homepage(session)

        if result is None:
            print("无法发现最新期 URL", file=sys.stderr)
            sys.exit(1)

        json.dump(result, sys.stdout, ensure_ascii=False)
        print()

    except requests.exceptions.RequestException as e:
        print(f"无法连接 qstheory.cn: {e}", file=sys.stderr)
        sys.exit(2)
    except XMLSyntaxError as e:
        print(f"无法解析 qstheory.cn 返回的 HTML: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001 — last-resort guard for the CI job
        print(f"发现失败: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
