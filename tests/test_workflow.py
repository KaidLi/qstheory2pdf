"""Release workflow completeness gates."""

from __future__ import annotations

import unittest
from pathlib import Path

_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "build-issue.yml"
_CI_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"


class WorkflowContractTest(unittest.TestCase):
    def test_release_requires_domain_status_and_epubcheck(self) -> None:
        workflow = _WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--status-file", workflow)
        self.assertIn("- name: Validate reconstruction completeness", workflow)
        self.assertIn("jq -e '.state == \"complete\"'", workflow)
        self.assertNotIn("qstheory2pdf --strict", workflow)
        self.assertNotIn("--allow-partial", workflow)
        self.assertIn("actions/setup-java@v5", workflow)
        self.assertIn("EPUBCHECK_VERSION: '5.3.0'", workflow)
        self.assertLess(
            workflow.index("- name: Validate reconstruction completeness"),
            workflow.index("- name: Create Release"),
        )
        self.assertLess(
            workflow.index("- name: Validate EPUB"),
            workflow.index("- name: Create Release"),
        )

    def test_ci_runs_without_release_permissions_or_release_steps(self) -> None:
        workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("push:", workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("python-version: ['3.10', '3.12']", workflow)
        self.assertIn("scripts/smoke_renditions.py", workflow)
        self.assertIn("EPUBCHECK_VERSION: '5.3.0'", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("action-gh-release", workflow)
        self.assertNotIn("gh release", workflow)


if __name__ == "__main__":
    unittest.main()
