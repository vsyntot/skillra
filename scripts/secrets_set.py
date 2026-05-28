#!/usr/bin/env python3
"""Set one value inside secrets/prod.sops.yaml without printing the secret."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    from env_contract import load_schema, schema_key_set
    from secrets_bootstrap import build_sops_payload, encrypt_payload, resolve_age_recipient
    from secrets_render import decrypt_sops_yaml, extract_env_values
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.secrets_set
    from scripts.env_contract import load_schema, schema_key_set
    from scripts.secrets_bootstrap import build_sops_payload, encrypt_payload, resolve_age_recipient
    from scripts.secrets_render import decrypt_sops_yaml, extract_env_values


DEFAULT_SCHEMA = Path("infra/env/schema.yml")
DEFAULT_SECRETS_FILE = Path("secrets/prod.sops.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update one env key in a SOPS file. The value is read from SECRET_VALUE " "or stdin and is never printed."
        ),
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS_FILE)
    parser.add_argument("--key", required=True, help="Env key to update, for example TELEGRAM_BOT_TOKEN.")
    parser.add_argument(
        "--value-env",
        default="SECRET_VALUE",
        help="Environment variable containing the new value. Default: SECRET_VALUE.",
    )
    parser.add_argument("--stdin", action="store_true", help="Read the new value from stdin instead of env.")
    parser.add_argument("--allow-empty", action="store_true", help="Allow setting an empty value.")
    parser.add_argument(
        "--require-change",
        action="store_true",
        help="Fail if the new value is identical to the existing decrypted value.",
    )
    parser.add_argument(
        "--age-recipient",
        default=None,
        help="age public recipient. Defaults to AGE_RECIPIENT env var.",
    )
    return parser.parse_args()


def read_secret_value(*, value_env: str, from_stdin: bool, allow_empty: bool) -> str:
    if from_stdin:
        value = sys.stdin.read()
        if value.endswith("\n"):
            value = value[:-1]
    else:
        value = os.environ.get(value_env)
        if value is None:
            raise ValueError(f"{value_env} is required or use --stdin")

    if value == "" and not allow_empty:
        raise ValueError("Secret value is empty. Use --allow-empty to set an empty value.")
    return value


def update_secret_payload(
    schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    key: str,
    value: str,
    require_change: bool = False,
) -> dict[str, dict[str, str]]:
    known_keys = schema_key_set(schema)
    if key not in known_keys:
        raise ValueError(f"{key} is not present in env schema")

    env_values = extract_env_values(payload, known_keys=known_keys)
    if require_change and env_values.get(key) == value:
        raise ValueError(f"{key} already has the provided value")
    env_values[key] = value
    return build_sops_payload(schema, env_values)


def main() -> None:
    args = parse_args()
    schema = load_schema(args.schema)
    value = read_secret_value(value_env=args.value_env, from_stdin=args.stdin, allow_empty=args.allow_empty)
    payload = decrypt_sops_yaml(args.secrets_file)
    updated_payload = update_secret_payload(
        schema,
        payload,
        key=args.key,
        value=value,
        require_change=args.require_change,
    )
    recipient = resolve_age_recipient(args.age_recipient)

    encrypt_payload(updated_payload, output=args.secrets_file, age_recipient=recipient, force=True)
    print(f"[secrets-set] Updated {args.key} in {args.secrets_file}")


if __name__ == "__main__":
    main()
