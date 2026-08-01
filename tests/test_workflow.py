"""发布工作流关键门禁测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

_WORKFLOW = (
    Path(__file__).parents[1] / ".github" / "workflows" / "build-issue.yml"
)


class WorkflowContractTest(unittest.TestCase):
    def test_release_requires_strict_build_and_epubcheck(self) -> None:
        workflow = _WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("qstheory2pdf --strict", workflow)
        self.assertIn("dry_run:", workflow)
        self.assertIn('echo "mode=dry-run"', workflow)
        self.assertIn("inputs.dry_run != true", workflow)
        self.assertIn("actions/setup-java@v4", workflow)
        self.assertIn("EPUBCHECK_VERSION: '5.3.0'", workflow)
        self.assertIn('java -jar "/tmp/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar"', workflow)
        self.assertLess(
            workflow.index("- name: Validate EPUB"),
            workflow.index("- name: Create Release"),
        )


if __name__ == "__main__":
    unittest.main()
