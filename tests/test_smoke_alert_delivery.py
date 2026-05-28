from __future__ import annotations

from scripts.smoke_alert_delivery import build_alert, has_smoke_alert


def test_build_alert_labels_smoke_run_id() -> None:
    alert = build_alert(alertname="SkillraSmokeAlert", run_id="smoke-1")

    assert alert["labels"]["alertname"] == "SkillraSmokeAlert"
    assert alert["labels"]["severity"] == "info"
    assert alert["labels"]["skillra_smoke_run_id"] == "smoke-1"
    assert alert["annotations"]["summary"] == "Skillra alert delivery smoke"
    assert "endsAt" in alert


def test_has_smoke_alert_matches_by_run_id() -> None:
    alerts = [
        {"labels": {"skillra_smoke_run_id": "other"}},
        {"labels": {"skillra_smoke_run_id": "smoke-1"}},
    ]

    assert has_smoke_alert(alerts, run_id="smoke-1")
    assert not has_smoke_alert(alerts, run_id="missing")
