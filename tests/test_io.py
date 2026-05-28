"""Tests for IO helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.skillra_pda import io


def test_save_processed_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    output_path = tmp_path / "processed.csv"
    calls: list[tuple[Path, Path]] = []
    original_replace = io.os.replace

    def tracking_replace(src: str | Path, dst: str | Path) -> None:
        calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    monkeypatch.setattr(io.os, "replace", tracking_replace)

    io.save_processed(df, output_path)

    assert output_path.exists()
    assert calls and calls[0][1] == output_path
    assert len(list(tmp_path.iterdir())) == 1


def test_save_processed_cleans_temp_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame({"a": [1, 2]})
    output_path = tmp_path / "processed.csv"

    def failing_to_csv(self: pd.DataFrame, path: str | Path, **kwargs: object) -> None:
        Path(path).write_text("partial")
        raise RuntimeError("boom")

    monkeypatch.setattr(pd.DataFrame, "to_csv", failing_to_csv)

    with pytest.raises(RuntimeError, match="boom"):
        io.save_processed(df, output_path)

    assert list(tmp_path.iterdir()) == []
