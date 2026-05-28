from __future__ import annotations

import pytest
from skillra_api.config import Settings


def test_settings_accepts_json_log_format() -> None:
    settings = Settings(log_format="json")

    assert settings.log_format == "json"


def test_settings_rejects_invalid_log_format() -> None:
    with pytest.raises(ValueError):
        Settings(log_format="plain")
