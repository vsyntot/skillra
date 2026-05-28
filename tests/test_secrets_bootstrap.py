from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import secrets_bootstrap

SCHEMA = {
    "groups": [
        {
            "name": "Core",
            "variables": {
                "SKILLRA_API_TOKEN": {"required": ["prod"]},
                "BOT_MODE": {"default": {"prod": "polling"}},
            },
        },
        {
            "name": "Telegram",
            "variables": {
                "TELEGRAM_BOT_TOKEN": {"required": ["prod"], "secret": True},
            },
        },
    ]
}


def test_resolve_age_recipient_accepts_comma_separated_public_recipients() -> None:
    recipient = secrets_bootstrap.resolve_age_recipient("age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq, age1pppppp")

    assert recipient == "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq,age1pppppp"


def test_resolve_age_recipient_can_read_sops_config(tmp_path) -> None:
    config = tmp_path / ".sops.yaml"
    config.write_text(
        "creation_rules:\n"
        "  - path_regex: secrets/.*\\.sops\\.ya?ml$\n"
        "    age: age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq\n",
        encoding="utf-8",
    )

    recipient = secrets_bootstrap.resolve_age_recipient(None, sops_config=config)

    assert recipient == "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"


def test_resolve_age_recipient_rejects_missing_or_placeholder(tmp_path) -> None:
    missing_config = tmp_path / "missing.sops.yaml"
    with pytest.raises(ValueError, match="required"):
        secrets_bootstrap.resolve_age_recipient("", sops_config=missing_config)

    with pytest.raises(ValueError, match="real age"):
        secrets_bootstrap.resolve_age_recipient("age1example", sops_config=missing_config)


def test_build_sops_payload_preserves_schema_order() -> None:
    payload = secrets_bootstrap.build_sops_payload(
        SCHEMA,
        {
            "TELEGRAM_BOT_TOKEN": "bot-secret",
            "SKILLRA_API_TOKEN": "api-secret",
            "BOT_MODE": "polling",
        },
    )

    assert list(payload["env"]) == ["SKILLRA_API_TOKEN", "BOT_MODE", "TELEGRAM_BOT_TOKEN"]


def test_build_sops_payload_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="outside env schema"):
        secrets_bootstrap.build_sops_payload(SCHEMA, {"UNKNOWN": "value"})


def test_encrypt_payload_invokes_sops_without_secret_values(tmp_path, monkeypatch) -> None:
    output = tmp_path / "prod.sops.yaml"
    calls: list[list[str]] = []

    monkeypatch.setattr(secrets_bootstrap.shutil, "which", lambda name: "/usr/bin/sops" if name == "sops" else None)

    def fake_run(cmd: list[str], **_: object) -> SimpleNamespace:
        calls.append(cmd)
        output.write_text("env:\n  SKILLRA_API_TOKEN: ENC[AES256_GCM,data:...]\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(secrets_bootstrap.subprocess, "run", fake_run)

    secrets_bootstrap.encrypt_payload(
        {"env": {"SKILLRA_API_TOKEN": "api-secret"}},
        output=output,
        age_recipient="age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq",
    )

    assert output.exists()
    assert calls
    assert "api-secret" not in " ".join(calls[0])


def test_encrypt_payload_refuses_to_overwrite_without_force(tmp_path, monkeypatch) -> None:
    output = tmp_path / "prod.sops.yaml"
    output.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(secrets_bootstrap.shutil, "which", lambda name: "/usr/bin/sops" if name == "sops" else None)

    with pytest.raises(SystemExit, match="already exists"):
        secrets_bootstrap.encrypt_payload(
            {"env": {"SKILLRA_API_TOKEN": "api-secret"}},
            output=output,
            age_recipient="age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq",
        )
