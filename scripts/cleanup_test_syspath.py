"""Remove redundant sys.path boilerplate from API test files (GAP-S4-06 / TASK-05)."""

from __future__ import annotations

import re
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parents[1] / "apps" / "skillra_api" / "tests"
TARGET_FILES = [
    "test_auth.py",
    "test_datastore.py",
    "test_digest_preview.py",
    "test_health.py",
    "test_market_segment_summary.py",
    "test_meta_endpoints.py",
    "test_metrics.py",
    "test_persona_endpoints.py",
    "test_subscription_endpoints.py",
    "test_user_profile_endpoints.py",
    "test_validation_constraints.py",
]

# Matches the entire path-manipulation block:
#   PROJECT_ROOT = Path(__file__).resolve().parents[N]
#   SRC_DIR = PROJECT_ROOT / "src"           (optional)
#   APP_SRC = PROJECT_ROOT / "apps" / ...    (optional)
#   if str(X) not in sys.path:               (0 or more)
#       sys.path.insert(0, str(X))
SYSPATH_BLOCK_RE = re.compile(
    r"\n*PROJECT_ROOT\s*=\s*Path\(__file__\)\.resolve\(\)\.parents\[\d+\]\n"
    r"(?:SRC_DIR\s*=\s*PROJECT_ROOT[^\n]+\n)?"
    r"(?:APP_SRC\s*=\s*PROJECT_ROOT[^\n]+\n)?"
    r"(?:if\s+str\(\w+\)\s+not\s+in\s+sys\.path:\s*\n\s+sys\.path\.insert\(\d+,\s+str\(\w+\)\)\n)*"
    r"\n?",
)


def _uses_symbol(text: str, symbol: str) -> bool:
    """Return True if symbol appears in text outside import lines."""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("import ", "from ")):
            continue
        if symbol in line:
            return True
    return False


def clean_file(fpath: Path) -> None:
    original = fpath.read_text()

    cleaned = SYSPATH_BLOCK_RE.sub("\n", original)

    # Remove dangling "import sys" if sys no longer used anywhere
    if not _uses_symbol(cleaned, "sys.") and "import sys\n" in cleaned:
        cleaned = re.sub(r"^import sys\n", "", cleaned, flags=re.MULTILINE)

    # Remove dangling "from pathlib import Path" if Path no longer referenced
    path_used = _uses_symbol(cleaned, "Path(") or ": Path" in cleaned or "-> Path" in cleaned or "| Path" in cleaned
    if not path_used and "from pathlib import Path\n" in cleaned:
        cleaned = re.sub(r"^from pathlib import Path\n", "", cleaned, flags=re.MULTILINE)

    # Collapse 3+ consecutive blank lines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    if cleaned != original:
        fpath.write_text(cleaned)
        print(f"CLEANED: {fpath.name}")
    else:
        print(f"NO CHANGE: {fpath.name}")


def main() -> None:
    for fname in TARGET_FILES:
        fpath = TEST_DIR / fname
        if not fpath.exists():
            print(f"SKIP (not found): {fname}")
            continue
        clean_file(fpath)


if __name__ == "__main__":
    main()
