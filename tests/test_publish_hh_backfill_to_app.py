from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import publish_hh_backfill_to_app as publish
from skillra_pda.ingest.source_registry import build_source_capability_ref


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeS3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeClient:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if Key not in self.objects:
            raise FakeS3Error("404")
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if Key not in self.objects:
            raise FakeS3Error("NoSuchKey")
        return {"Body": FakeBody(self.objects[Key])}


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_publish_refuses_quarantined_backfill_prefix() -> None:
    client = FakeClient(
        {
            "backfills/test/_QUARANTINE.json": _json_bytes(
                {"status": "quarantined", "reason": "historical date semantics gate failed"}
            ),
            "backfills/test/state.json": _json_bytes({"completed_dates": ["2025-12-01"]}),
        }
    )

    with pytest.raises(SystemExit, match="Refusing to publish quarantined source"):
        publish.load_backfill_selection(
            client,
            bucket="skillra-raw-hh",
            backfill_id="test",
            max_date=None,
            min_completed_days=1,
        )


def test_publish_allows_quarantined_backfill_only_with_explicit_forensic_flag() -> None:
    client = FakeClient(
        {
            "backfills/test/_QUARANTINE.json": _json_bytes(
                {"status": "quarantined", "reason": "historical date semantics gate failed"}
            ),
            "backfills/test/state.json": _json_bytes(
                {
                    "completed_dates": ["2025-12-01"],
                    "current_date": None,
                    "updated_at_utc": "2026-05-26T00:00:00+00:00",
                }
            ),
        }
    )

    selection = publish.load_backfill_selection(
        client,
        bucket="skillra-raw-hh",
        backfill_id="test",
        max_date=None,
        min_completed_days=1,
        allow_quarantined_source=True,
    )

    assert selection.selected_dates == ["2025-12-01"]
    assert selection.quarantine and selection.quarantine["status"] == "quarantined"


def test_publish_rejects_quarantined_day_prefix(tmp_path: Path) -> None:
    client = FakeClient(
        {
            "backfills/test/date=2025-12-01/_QUARANTINE.json": _json_bytes(
                {"status": "quarantined", "reason": "day failed"}
            ),
            "backfills/test/date=2025-12-01/metadata.json": _json_bytes({"row_count": 0}),
        }
    )

    with pytest.raises(SystemExit, match="Refusing to publish quarantined source"):
        publish.ensure_cached_day(
            client,
            bucket="skillra-raw-hh",
            prefix="backfills/test/",
            storage_dir=tmp_path,
            backfill_id="test",
            day="2025-12-01",
        )


def test_publish_marks_quarantined_selection_as_forensic_not_historical() -> None:
    selection = publish.PublishSelection(
        backfill_id="test",
        bucket="skillra-raw-hh",
        prefix="backfills/test/",
        completed_dates=["2025-12-01"],
        selected_dates=["2025-12-01"],
        current_date=None,
        backfill_updated_at_utc=None,
        quarantine={"status": "quarantined"},
    )

    assert publish.resolve_dataset_semantic_type(selection, {"status": "passed"}) == "forensic_quarantined_snapshot"


def test_publish_marks_failed_date_semantics_as_current_snapshot() -> None:
    source_capability_ref = build_source_capability_ref(
        source_mode="fixture",
        use_case="historical_collection",
        capability_status="supported",
        evidence_type="test_fixture",
    )
    selection = publish.PublishSelection(
        backfill_id="test",
        bucket="skillra-raw-hh",
        prefix="backfills/test/",
        completed_dates=["2025-12-01"],
        selected_dates=["2025-12-01"],
        current_date=None,
        backfill_updated_at_utc=None,
        source_capability_ref=source_capability_ref,
    )

    assert publish.resolve_dataset_semantic_type(selection, {"status": "failed"}) == "current_market_snapshot"
    assert publish.resolve_dataset_semantic_type(selection, {"status": "passed"}) == "historical_publication_facts"


def test_publish_does_not_mark_historical_without_source_capability_ref() -> None:
    selection = publish.PublishSelection(
        backfill_id="test",
        bucket="skillra-raw-hh",
        prefix="backfills/test/",
        completed_dates=["2025-12-01"],
        selected_dates=["2025-12-01"],
        current_date=None,
        backfill_updated_at_utc=None,
    )

    assert publish.resolve_dataset_semantic_type(selection, {"status": "passed"}) == "current_market_snapshot"
