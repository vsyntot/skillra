"""Regression tests for import-time side effects."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_viz_import_does_not_create_reports_dir(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports_side_effect_test"
    env = os.environ.copy()
    env["SKILLRA_REPORTS_DIR"] = str(reports_dir)

    subprocess.run(
        [sys.executable, "-c", "import src.skillra_pda.viz"],
        check=True,
        env=env,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert not reports_dir.exists()
