from __future__ import annotations

"""Run the end-to-end data cleaning and feature engineering pipeline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skillra_pda import cleaning, config, features, io, market  # noqa: E402


def main() -> None:
    """Load raw data, clean it, engineer features, and persist outputs."""
    config.ensure_directories()

    raw_path = Path(config.RAW_DATA_FILE)
    clean_path = Path(config.CLEAN_DATA_FILE)
    feature_path = Path(config.FEATURE_DATA_FILE)
    market_view_path = Path(config.PROCESSED_DATA_DIR) / "market_view.parquet"

    df_raw = io.load_raw(raw_path)
    df_clean = cleaning.handle_missingness(
        df_raw, drop_threshold=cleaning.LOW_INFORMATION_THRESHOLD
    )
    df_clean = cleaning.parse_dates(df_clean)
    df_clean = cleaning.salary_prepare(df_clean)
    df_clean = cleaning.deduplicate(df_clean)
    io.save_processed(df_clean, clean_path)

    df_features = features.assemble_features(df_clean.copy())
    io.save_processed(df_features, feature_path)

    market_view = market.build_market_view(df_features.copy())
    io.save_processed(market_view, market_view_path)

    print(f"Saved clean dataset to {clean_path}")
    print(f"Saved feature dataset to {feature_path}")
    print(f"Saved market view to {market_view_path}")


if __name__ == "__main__":
    main()
