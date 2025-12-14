"""Unit tests for cleaning helpers."""

import pandas as pd

from src.skillra_pda import cleaning


def test_ensure_salary_gross_boolean_converts_and_preserves_columns():
    df = pd.DataFrame(
        {
            "salary_gross": ["True", "False", "unknown", "yes", "no"],
            "salary_from": [100000, 150000, None, 200000, 50000],
        }
    )

    result = cleaning.ensure_salary_gross_boolean(df.copy())

    assert set(result.columns) == set(df.columns)
    assert str(result["salary_gross"].dtype) == "boolean"
    pd.testing.assert_series_equal(result["salary_from"], df["salary_from"], check_names=False)
    assert list(result["salary_gross"].astype(object)) == [True, False, pd.NA, True, False]
