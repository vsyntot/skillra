"""Project-wide configuration helpers.

This module centralizes frequently used paths so notebooks and scripts can rely
on a single source of truth.

Local development stores outputs under ``./reports``. In containers with a
read-only repo root, outputs fall back to ``/tmp/skillra/reports`` unless
explicitly overridden via environment variables.
"""

import logging
import os
from pathlib import Path
from typing import Set

logger = logging.getLogger(__name__)

# Repository root inferred from this file's location
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
PROCESSED_RUNS_DIR = PROCESSED_DATA_DIR / "runs"
PROCESSED_LATEST_DIR = PROCESSED_DATA_DIR / "latest"
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"

# Sprint-007 TASK-15: Path to noisy skills YAML config
NOISY_SKILLS_PATH = Path(__file__).parent / "noisy_skills.yaml"


def _default_noisy_skills() -> Set[str]:
    """Return the hardcoded fallback set of noisy skills."""
    return {
        "has_test_task",
        "has_relocation",
        "has_metro",
        "has_mentoring",
        "skill_php",
        "skill_javascript",
        "skill_html",
        "skill_css",
        "skill_git",
    }


def load_noisy_skills() -> Set[str]:
    """Load the noisy skills set from YAML config, falling back to defaults."""
    if not NOISY_SKILLS_PATH.exists():
        logger.warning("noisy_skills.yaml not found at %s — using defaults", NOISY_SKILLS_PATH)
        return _default_noisy_skills()
    try:
        import yaml  # type: ignore[import-untyped]

        with open(NOISY_SKILLS_PATH) as f:
            data = yaml.safe_load(f)
        if data and isinstance(data.get("skills"), list):
            return set(data["skills"])
    except Exception as exc:
        logger.warning("Failed to load noisy_skills.yaml: %s — using defaults", exc)
    return _default_noisy_skills()


def _is_repo_root_writable() -> bool:
    return os.access(REPO_ROOT, os.W_OK)


def _reports_base_dir() -> Path:
    env_override = os.getenv("SKILLRA_REPORTS_DIR")
    if env_override:
        return Path(env_override)
    if _is_repo_root_writable():
        return REPO_ROOT / "reports"
    return Path("/tmp/skillra/reports")


REPORTS_DIR = _reports_base_dir()
FIGURES_DIR = Path(os.getenv("SKILLRA_FIGURES_DIR", REPORTS_DIR / "figures"))
NOTEBOOK_REPORTS_DIR = Path(os.getenv("SKILLRA_NOTEBOOK_REPORTS_DIR", REPORTS_DIR / "notebooks"))

# Default filenames
RAW_DATA_FILE = RAW_DATA_DIR / "hh_moscow_it_2025_11_30.csv"
CLEAN_DATA_FILE = PROCESSED_LATEST_DIR / "hh_clean.parquet"
FEATURE_DATA_FILE = PROCESSED_LATEST_DIR / "hh_features.parquet"


def ensure_directories() -> None:
    """Create common output directories if they do not already exist."""
    for path in [PROCESSED_DATA_DIR, PROCESSED_RUNS_DIR, FIGURES_DIR, NOTEBOOK_REPORTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)
