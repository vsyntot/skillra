#!/usr/bin/env python3
"""Bootstrap an encrypted SOPS YAML file from an existing Skillra env file."""

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
    from env_contract import SUPPORTED_PROFILES, iter_env_vars, load_schema, parse_env_file, schema_key_set
    from env_doctor import validate_env
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.secrets_bootstrap
    from scripts.env_contract import SUPPORTED_PROFILES, iter_env_vars, load_schema, parse_env_file, schema_key_set
    from scripts.env_doctor import validate_env


DEFAULT_SCHEMA = Path("infra/env/schema.yml")
DEFAULT_ENV_FILE = Path(".env.prod")
DEFAULT_OUTPUT = Path("secrets/prod.sops.yaml")
DEFAULT_SOPS_CONFIG = Path(".sops.yaml")
DEFAULT_AGE_KEY_FILE = Path.home() / ".config/sops/age/keys.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create secrets/prod.sops.yaml from .env.prod using SOPS + age. "
            "Secret values are written only to a temporary plaintext file and are never printed."
        ),
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--profile", choices=sorted(SUPPORTED_PROFILES), default="prod")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--age-recipient",
        default=None,
        help="age public recipient. Defaults to AGE_RECIPIENT env var. Comma-separated recipients are supported.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite --output if it already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and tooling without writing output.")
    return parser.parse_args()


def age_recipient_from_sops_config(path: Path = DEFAULT_SOPS_CONFIG) -> str | None:
    if not path.exists():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    creation_rules = payload.get("creation_rules")
    if not isinstance(creation_rules, list):
        return None
    for rule in creation_rules:
        if isinstance(rule, dict) and rule.get("age"):
            return str(rule["age"])
    return None


def resolve_age_recipient(value: str | None, *, sops_config: Path = DEFAULT_SOPS_CONFIG) -> str:
    recipient = (value or os.environ.get("AGE_RECIPIENT") or age_recipient_from_sops_config(sops_config) or "").strip()
    recipients = [item.strip() for item in recipient.split(",") if item.strip()]
    if not recipients:
        raise ValueError("AGE_RECIPIENT is required")
    invalid = [
        item
        for item in recipients
        if not item.startswith("age1") or "example" in item.lower() or "replace" in item.lower()
    ]
    if invalid:
        raise ValueError("AGE_RECIPIENT must contain real age public recipients")
    return ",".join(recipients)


def build_sops_payload(schema: dict[str, Any], env_values: dict[str, str]) -> dict[str, dict[str, str]]:
    known_keys = schema_key_set(schema)
    unknown = sorted(set(env_values) - known_keys)
    if unknown:
        raise ValueError("Env file contains keys outside env schema: " + ", ".join(unknown))

    ordered_values: dict[str, str] = {}
    for env_var in iter_env_vars(schema):
        if env_var.name in env_values:
            ordered_values[env_var.name] = env_values[env_var.name]

    if not ordered_values:
        raise ValueError("Env file does not contain any schema keys")
    return {"env": ordered_values}


def validate_source_env(schema: dict[str, Any], profile: str, env_file: Path) -> None:
    errors, warnings = validate_env(schema, profile, env_file, strict_unknown=True)
    for warning in warnings:
        print(f"[secrets-bootstrap] WARN: {warning}")
    if errors:
        for error in errors:
            print(f"[secrets-bootstrap] ERROR: {error}")
        raise SystemExit(1)


def require_sops() -> None:
    if shutil.which("sops") is None:
        raise SystemExit("sops is required. Install sops and age first, then rerun this command.")


def sops_environment() -> dict[str, str]:
    env = os.environ.copy()
    if "SOPS_AGE_KEY_FILE" not in env and DEFAULT_AGE_KEY_FILE.exists():
        env["SOPS_AGE_KEY_FILE"] = str(DEFAULT_AGE_KEY_FILE)
    return env


def encrypt_payload(
    payload: dict[str, Any],
    *,
    output: Path,
    age_recipient: str,
    force: bool = False,
) -> None:
    require_sops()
    if output.exists() and not force:
        raise SystemExit(f"{output} already exists. Use --force to overwrite it.")

    output.parent.mkdir(parents=True, exist_ok=True)
    plaintext = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=output.parent,
        prefix=".bootstrap-",
        suffix=".sops.yaml",
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(plaintext)
    os.chmod(temp_path, 0o600)

    try:
        subprocess.run(
            [
                "sops",
                "--encrypt",
                "--input-type",
                "yaml",
                "--output-type",
                "yaml",
                "--age",
                age_recipient,
                "--output",
                str(output),
                str(temp_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=sops_environment(),
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to encrypt {output} with sops") from exc
    finally:
        temp_path.unlink(missing_ok=True)

    os.chmod(output, 0o600)


def main() -> None:
    args = parse_args()
    schema = load_schema(args.schema)
    validate_source_env(schema, args.profile, args.env_file)
    env_values, duplicates = parse_env_file(args.env_file)
    if duplicates:
        raise SystemExit("Env file contains duplicate keys: " + ", ".join(sorted(set(duplicates))))

    recipient = resolve_age_recipient(args.age_recipient)
    payload = build_sops_payload(schema, env_values)
    require_sops()

    if args.dry_run:
        print(
            f"[secrets-bootstrap] OK: {args.env_file} can bootstrap {args.output} "
            f"with {len(payload['env'])} env keys"
        )
        return

    encrypt_payload(payload, output=args.output, age_recipient=recipient, force=args.force)
    print(f"[secrets-bootstrap] Wrote encrypted {args.output} with {len(payload['env'])} env keys")


if __name__ == "__main__":
    main()
