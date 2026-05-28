from __future__ import annotations

import pytest

from scripts.check_health_contour import HealthContourError, validate_health_contour


def test_validate_health_contour_accepts_expected_markers() -> None:
    validate_health_contour(
        {"status": "ok", "runtime_env": "staging", "public_base_url": "https://staging.skillra.ru"},
        expected_runtime_env="staging",
        expected_public_base_url="https://staging.skillra.ru/",
    )


def test_validate_health_contour_rejects_wrong_runtime_env() -> None:
    with pytest.raises(HealthContourError, match="runtime_env"):
        validate_health_contour(
            {"status": "ok", "runtime_env": "prod", "public_base_url": "https://skillra.ru"},
            expected_runtime_env="staging",
            expected_public_base_url=None,
        )


def test_validate_health_contour_rejects_degraded_status() -> None:
    with pytest.raises(HealthContourError, match="status"):
        validate_health_contour(
            {"status": "degraded", "runtime_env": "staging", "public_base_url": "https://staging.skillra.ru"},
            expected_runtime_env="staging",
            expected_public_base_url="https://staging.skillra.ru",
        )
