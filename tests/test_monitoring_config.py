from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_monitoring_config import (
    MonitoringConfigError,
    _validate_known_skillra_metrics,
    validate_monitoring_repo,
)


def test_monitoring_config_contract_is_complete() -> None:
    validate_monitoring_repo(Path("."))


def test_monitoring_config_rejects_unknown_skillra_metrics() -> None:
    with pytest.raises(MonitoringConfigError, match="skillra_digests_sent_total_timestamp_seconds"):
        _validate_known_skillra_metrics(
            "(time() - skillra_digests_sent_total_timestamp_seconds) > 7200",
            "unit-test",
        )
