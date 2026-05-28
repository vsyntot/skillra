from __future__ import annotations

import stat

import pytest

from scripts.secrets_render import (
    extract_env_values,
    render_from_payload,
    write_env_file,
)

SCHEMA = {
    "profiles": {"prod": {"title": "Prod"}},
    "groups": [
        {
            "name": "API",
            "variables": {
                "SKILLRA_API_TOKEN": {"type": "string", "secret": True, "required": ["prod"]},
                "BOT_MODE": {"type": "string", "default": {"prod": "polling"}},
                "FEATURE_ENABLED": {"type": "bool", "default": {"prod": "false"}},
            },
        }
    ],
}


def test_extract_env_values_accepts_env_mapping_and_normalizes_scalars() -> None:
    values = extract_env_values(
        {"env": {"SKILLRA_API_TOKEN": "token", "FEATURE_ENABLED": True}},
        known_keys={"SKILLRA_API_TOKEN", "FEATURE_ENABLED"},
    )

    assert values == {"SKILLRA_API_TOKEN": "token", "FEATURE_ENABLED": "true"}


def test_extract_env_values_rejects_unknown_schema_keys() -> None:
    with pytest.raises(ValueError, match="outside env schema"):
        extract_env_values({"env": {"UNKNOWN": "value"}}, known_keys={"SKILLRA_API_TOKEN"})


def test_render_from_payload_preserves_schema_order_and_defaults() -> None:
    rendered = render_from_payload(SCHEMA, "prod", {"env": {"SKILLRA_API_TOKEN": "secret"}})

    assert "SKILLRA_API_TOKEN=secret" in rendered
    assert "BOT_MODE=polling" in rendered
    assert rendered.index("SKILLRA_API_TOKEN=secret") < rendered.index("BOT_MODE=polling")


def test_write_env_file_uses_owner_only_permissions(tmp_path) -> None:
    output = tmp_path / ".env.prod"

    write_env_file(output, "KEY=value\n")

    assert output.read_text(encoding="utf-8") == "KEY=value\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
