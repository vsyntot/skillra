"""Quick regression script to validate cleaning + save pipeline."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skillra_pda import cleaning, config, features, io


UNKNOWN_MARKERS = {"unknown", "Unknown", "UNKNOWN", ""}


def main() -> None:
    raw_path = Path(config.RAW_DATA_FILE)
    clean_path = Path(config.CLEAN_DATA_FILE)

    df = io.load_raw(raw_path)
    df = cleaning.parse_dates(df)
    df = cleaning.deduplicate(df)
    dedup_rows = int(df.attrs.get("deduplicated_rows", 0) or 0)
    df = cleaning.handle_missingness(df)
    dropped_cols = df.attrs.get("dropped_cols", [])
    df = cleaning.salary_prepare(df)
    non_rub_share = float(df.attrs.get("non_rub_share", 0.0) or 0.0)

    if "salary_gross" in df.columns:
        dtype_before = str(df["salary_gross"].dtype)
        unwanted_before = df["salary_gross"].isin(UNKNOWN_MARKERS).sum()
    else:
        dtype_before = "missing"
        unwanted_before = 0

    df_features = features.assemble_features(df.copy())

    try:
        io.save_processed(df, clean_path)
    except Exception as exc:  # pragma: no cover - script guard
        print(f"FAIL: saving clean dataset raised {exc}")
        return

    dtype_after = str(df["salary_gross"].dtype) if "salary_gross" in df.columns else "missing"
    unwanted_after = (
        df["salary_gross"].isin(UNKNOWN_MARKERS).sum() if "salary_gross" in df.columns else 0
    )
    ok = (
        "salary_gross" in df.columns
        and dtype_after == "boolean"
        and unwanted_after == 0
    )

    vacancy_age_ok = "vacancy_age_days" in df_features.columns
    if vacancy_age_ok:
        vacancy_age_ok = df_features["vacancy_age_days"].notna().any()

    print("\n=== Cleaning metrics ===")
    print(f"Deduplicated rows removed: {dedup_rows}")
    print(f"Dropped columns: {dropped_cols}")
    print(f"Non-RUB share: {non_rub_share:.3f}")
    print(f"vacancy_age_days present: {vacancy_age_ok}")

    print(f"salary_gross dtype before save: {dtype_before}")
    print(f"salary_gross unknown markers before save: {unwanted_before}")
    print(f"salary_gross dtype after save: {dtype_after}")
    print(f"salary_gross unknown markers after save: {unwanted_after}")
    print("OK" if ok and vacancy_age_ok else "FAIL: pipeline invariants failed")


if __name__ == "__main__":
    main()
