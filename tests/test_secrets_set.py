from __future__ import annotations

import pytest

from scripts import secrets_set

SCHEMA = {
    "groups": [
        {
            "name": "Core",
            "variables": {
                "SKILLRA_API_TOKEN": {"required": ["prod"]},
                "BOT_MODE": {"default": {"prod": "polling"}},
            },
        }
    ]
}


def test_read_secret_value_uses_env_without_printing(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_VALUE", "new-secret")

    assert secrets_set.read_secret_value(value_env="SECRET_VALUE", from_stdin=False, allow_empty=False) == "new-secret"


def test_read_secret_value_rejects_empty_by_default(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_VALUE", "")

    with pytest.raises(ValueError, match="empty"):
        secrets_set.read_secret_value(value_env="SECRET_VALUE", from_stdin=False, allow_empty=False)


def test_update_secret_payload_rejects_key_outside_schema() -> None:
    with pytest.raises(ValueError, match="not present"):
        secrets_set.update_secret_payload(SCHEMA, {"env": {}}, key="UNKNOWN", value="value")


def test_update_secret_payload_preserves_existing_values_and_schema_order() -> None:
    payload = secrets_set.update_secret_payload(
        SCHEMA,
        {"env": {"BOT_MODE": "polling", "SKILLRA_API_TOKEN": "old"}},
        key="SKILLRA_API_TOKEN",
        value="new",
    )

    assert payload == {"env": {"SKILLRA_API_TOKEN": "new", "BOT_MODE": "polling"}}


def test_update_secret_payload_can_require_changed_value() -> None:
    with pytest.raises(ValueError, match="already has"):
        secrets_set.update_secret_payload(
            SCHEMA,
            {"env": {"SKILLRA_API_TOKEN": "same"}},
            key="SKILLRA_API_TOKEN",
            value="same",
            require_change=True,
        )

    payload = secrets_set.update_secret_payload(
        SCHEMA,
        {"env": {"SKILLRA_API_TOKEN": "old"}},
        key="SKILLRA_API_TOKEN",
        value="new",
        require_change=True,
    )

    assert payload["env"]["SKILLRA_API_TOKEN"] == "new"
