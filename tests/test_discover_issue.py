"""最新期发现脚本测试。"""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import requests

_SCRIPT = Path(__file__).parents[1] / "scripts" / "discover_issue.py"
_SPEC = importlib.util.spec_from_file_location("discover_issue", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
discover_issue = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(discover_issue)


def _response(text: str):
    response = SimpleNamespace(text=text, encoding="")
    response.raise_for_status = Mock()
    return response


class DiscoverIssueTest(unittest.TestCase):
    def test_fetch_tree_checks_http_status(self) -> None:
        response = _response("<html/>")
        response.raise_for_status.side_effect = requests.HTTPError("503")
        session = SimpleNamespace(get=Mock(return_value=response))

        with self.assertRaises(requests.HTTPError):
            discover_issue._fetch_tree(session, "https://example.com")

        response.raise_for_status.assert_called_once_with()

    def test_archive_discovery_chooses_highest_issue(self) -> None:
        year = datetime.now().year
        archive = _response(
            f'<a href="/{year}/index.htm">{year}年</a>'
        )
        year_page = _response(
            f"""
            <a href="https://www.qstheory.cn/a">《求是》{year}年第2期</a>
            <a href="https://www.qstheory.cn/b">《求是》{year}年第16期</a>
            """
        )
        session = SimpleNamespace(get=Mock(side_effect=[archive, year_page]))

        result = discover_issue._discover_via_mulu(session)

        self.assertEqual(f"qstheory-{year}-16", result["tag"])
        self.assertEqual("https://www.qstheory.cn/b", result["url"])

    def test_manual_page_extracts_volume(self) -> None:
        page = _response(
            '<span class="appellation">来源：《求是》2026/15</span>'
        )
        session = SimpleNamespace(get=Mock(return_value=page))

        result = discover_issue._extract_issue_from_page(
            session,
            "https://www.qstheory.cn/issue",
        )

        self.assertEqual("2026年第15期", result["volume"])


if __name__ == "__main__":
    unittest.main()
