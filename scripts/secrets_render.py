#!/usr/bin/env python3
"""Render Skillra env files from SOPS-encrypted YAML without printing secrets."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

try:
    from env_contract import SUPPORTED_PROFILES, load_schema, schema_key_set
    from env_doctor import validate_env
    from env_render import render_env
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.secrets_render
    from scripts.env_contract import SUPPORTED_PROFILES, load_schema, schema_key_set
    from scripts.env_doctor import validate_env
    from scripts.env_render import render_env


DEFAULT_SCHEMA = Path("infra/env/schema.yml")
DEFAULT_SECRETS_FILE = Path("secrets/prod.sops.yaml")
DEFAULT_OUTPUT = Path(".env.prod")
DEFAULT_AGE_KEY_FILE = Path.home() / ".config/sops/age/keys.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decrypt SOPS YAML and render a Skillra env file from infra/env/schema.yml.",
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--profile", choices=sorted(SUPPORTED_PROFILES), default="prod")
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="Decrypt and validate without writing --output.")
    parser.add_argument("--validate", action="store_true", help="Run env_doctor validation on the rendered output.")
    return parser.parse_args()


def sops_environment() -> dict[str, str]:
    env = os.environ.copy()
    if "SOPS_AGE_KEY_FILE" not in env and DEFAULT_AGE_KEY_FILE.exists():
        env["SOPS_AGE_KEY_FILE"] = str(DEFAULT_AGE_KEY_FILE)
    return env


def decrypt_sops_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Secrets file does not exist: {path}")
    if not shutil.which("sops"):
        raise SystemExit("sops is required to decrypt secrets. Install sops and configure age keys first.")

    try:
        result = subprocess.run(
            ["sops", "-d", str(path)],
            check=True,
            capture_output=True,
            text=True,
            env=sops_environment(),
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to decrypt {path} with sops") from exc

    payload = yaml.safe_load(result.stdout) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"Decrypted {path} must contain a YAML mapping")
    return payload


def extract_env_values(payload: dict[str, Any], *, known_keys: set[str]) -> dict[str, str]:
    raw_values = payload.get("env", payload)
    if not isinstance(raw_values, dict):
        raise ValueError("SOPS payload must contain a YAML mapping or an 'env' mapping")

    values: dict[str, str] = {}
    unknown_keys: list[str] = []
    for raw_key, raw_value in raw_values.items():
        key = str(raw_key)
        if key == "sops":
            continue
        if key not in known_keys:
            unknown_keys.append(key)
            continue
        if raw_value is None:
            values[key] = ""
        elif isinstance(raw_value, bool):
            values[key] = "true" if raw_value else "false"
        else:
            values[key] = str(raw_value)

    if unknown_keys:
        raise ValueError("Secrets payload contains keys outside env schema: " + ", ".join(sorted(unknown_keys)))
    return values


def write_env_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


def validate_rendered_env(schema: dict[str, Any], profile: str, content: str) -> tuple[list[str], list[str]]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        return validate_env(schema, profile, temp_path, strict_unknown=True)
    finally:
        temp_path.unlink(missing_ok=True)


def render_from_payload(schema: dict[str, Any], profile: str, payload: dict[str, Any]) -> str:
    values = extract_env_values(payload, known_keys=schema_key_set(schema))
    return render_env(schema, profile, existing_values=values)


def main() -> None:
    args = parse_args()
    schema = load_schema(args.schema)
    payload = decrypt_sops_yaml(args.secrets_file)
    rendered = render_from_payload(schema, args.profile, payload)

    if args.validate:
        errors, warnings = validate_rendered_env(schema, args.profile, rendered)
        for warning in warnings:
            print(f"[secrets-render] WARN: {warning}")
        if errors:
            for error in errors:
                print(f"[secrets-render] ERROR: {error}")
            raise SystemExit(1)

    if args.dry_run:
        print(f"[secrets-render] OK: {args.secrets_file} decrypts and renders for {args.profile}")
        return

    write_env_file(args.output, rendered)
    print(f"[secrets-render] Wrote {args.output} from {args.secrets_file} with mode 0600")


if __name__ == "__main__":
    main()
