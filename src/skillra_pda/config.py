"""Project-wide configuration helpers.

This module centralizes frequently used paths so notebooks and scripts can rely
on a single source of truth. All paths are expressed relative to the repository
root to keep execution reproducible in different environments.
"""
from pathlib import Path

# Repository root inferred from this file's location
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = REPO_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"
NOTEBOOK_REPORTS_DIR = REPORTS_DIR / "notebooks"

# Default filenames
RAW_DATA_FILE = RAW_DATA_DIR / "hh_moscow_it_2025_11_30.csv"
CLEAN_DATA_FILE = PROCESSED_DATA_DIR / "hh_clean.parquet"
FEATURE_DATA_FILE = PROCESSED_DATA_DIR / "hh_features.parquet"


def ensure_directories() -> None:
    """Create common output directories if they do not already exist."""
    for path in [PROCESSED_DATA_DIR, FIGURES_DIR, NOTEBOOK_REPORTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)
