"""Input/output helpers for the Skillra PDA project."""
from pathlib import Path
from typing import Union

import pandas as pd

from .cleaning import BOOLEAN_MARKERS, ensure_salary_gross_boolean

PathLike = Union[str, Path]


def load_raw(path: PathLike) -> pd.DataFrame:
    """Load the raw CSV dataset with safe defaults.

    Parameters
    ----------
    path : PathLike
        Path to the raw CSV file.

    Returns
    -------
    pd.DataFrame
    """
    csv_path = Path(path)
    return pd.read_csv(csv_path, low_memory=False)


def _coerce_boollike_object_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Sanitize nearly-boolean object columns before persistence."""

    allowed = BOOLEAN_MARKERS | {True, False, 0, 1, "true", "false", "yes", "no"}
    replace_map = {
        "true": True,
        "false": False,
        "yes": True,
        "no": False,
        "1": True,
        "0": False,
        "unknown": pd.NA,
        "": pd.NA,
        "n/a": pd.NA,
        "nan": pd.NA,
    }

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)
        if dtype_str == "bool":
            df[col] = series.astype("boolean")
            continue
        if dtype_str != "object":
            continue

        uniques = set(series.dropna().unique().tolist())
        normalized = {u.strip().lower() if isinstance(u, str) else u for u in uniques}
        if normalized and not normalized.issubset(allowed):
            continue

        def _convert(val: object) -> object:
            if pd.isna(val):
                return pd.NA
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)) and val in (0, 1):
                return bool(val)
            if isinstance(val, str):
                lowered = val.strip().lower()
                if lowered in replace_map:
                    return replace_map[lowered]
            return pd.NA

        df[col] = series.map(_convert).astype("boolean")

    return df


def save_processed(df: pd.DataFrame, path: PathLike) -> None:
    """Save a processed dataframe to CSV or Parquet.

    The parent directory is created automatically. Format is inferred from the
    file suffix: `.parquet` → Parquet, otherwise CSV.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df_to_save = ensure_salary_gross_boolean(df.copy())
    df_to_save = _coerce_boollike_object_columns(df_to_save)

    if output_path.suffix.lower() == ".parquet":
        df_to_save.to_parquet(output_path, index=False)
    else:
        df_to_save.to_csv(output_path, index=False)
