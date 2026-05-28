from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from skillra_api.datastore import DataStore


def dataset_trust_payload(
    datastore: DataStore,
    *,
    sample_size: int | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    """Return common dataset trust metadata for analytical responses."""

    meta = datastore.get_dataset_meta() or {}
    generated_at_utc = _first_present(meta, "generated_at_utc", "generated_at", "created_at")
    generated_at = _first_present(meta, "generated_at", "generated_at_utc", "created_at")
    payload = {
        "dataset_run_id": _string_or_none(meta.get("run_id") or meta.get("dataset_run_id")),
        "generated_at": _string_or_none(generated_at),
        "generated_at_utc": _string_or_none(generated_at_utc),
        "freshness": _freshness_label(_parse_datetime(generated_at_utc)),
        "sample_size": sample_size,
        "confidence": confidence,
    }
    for key in (
        "source_kind",
        "dataset_semantic_type",
        "requested_date_from",
        "requested_date_to",
        "observed_published_at_from",
        "observed_published_at_to",
        "date_semantics_status",
    ):
        payload[key] = _string_or_none(meta.get(key))
    product_eligibility = meta.get("product_eligibility")
    payload["product_eligibility"] = product_eligibility if isinstance(product_eligibility, dict) else None
    source_capability_ref = meta.get("source_capability_ref")
    payload["source_capability_ref"] = source_capability_ref if isinstance(source_capability_ref, dict) else None
    trend_ready_gate = meta.get("trend_ready_gate")
    payload["trend_ready_gate"] = trend_ready_gate if isinstance(trend_ready_gate, dict) else None
    return payload


def _first_present(mapping: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def _string_or_none(value: Any | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_datetime(value: Any | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_label(generated_at: datetime | None) -> str:
    if generated_at is None:
        return "unknown"
    age_seconds = (datetime.now(timezone.utc) - generated_at).total_seconds()
    if age_seconds <= 7 * 24 * 60 * 60:
        return "fresh"
    if age_seconds <= 30 * 24 * 60 * 60:
        return "aging"
    return "stale"
