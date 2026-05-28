from __future__ import annotations

from skillra_api.services.trust import dataset_trust_payload


class FakeDataStore:
    def get_dataset_meta(self) -> dict[str, object]:
        return {
            "run_id": "run-1",
            "generated_at_utc": "2026-05-26T00:00:00+00:00",
            "source_kind": "minio_backfill_completed",
            "dataset_semantic_type": "historical_publication_facts",
            "requested_date_from": "2025-12-01",
            "requested_date_to": "2025-12-02",
            "observed_published_at_from": "2025-12-01",
            "observed_published_at_to": "2025-12-02",
            "date_semantics_status": "passed",
        }


def test_dataset_trust_payload_exposes_lineage_fields() -> None:
    payload = dataset_trust_payload(FakeDataStore())  # type: ignore[arg-type]

    assert payload["dataset_run_id"] == "run-1"
    assert payload["source_kind"] == "minio_backfill_completed"
    assert payload["dataset_semantic_type"] == "historical_publication_facts"
    assert payload["requested_date_from"] == "2025-12-01"
    assert payload["observed_published_at_to"] == "2025-12-02"
    assert payload["date_semantics_status"] == "passed"
