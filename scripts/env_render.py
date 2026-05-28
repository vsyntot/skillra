#!/usr/bin/env python3
"""Render Skillra env example files from the env schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from env_contract import (
        SUPPORTED_PROFILES,
        default_value,
        iter_env_vars,
        load_schema,
        parse_env_file,
        profile_value,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.env_render
    from scripts.env_contract import (
        SUPPORTED_PROFILES,
        default_value,
        iter_env_vars,
        load_schema,
        parse_env_file,
        profile_value,
    )


DEFAULT_SCHEMA = Path("infra/env/schema.yml")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render .env examples from infra/env/schema.yml")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--profile", choices=sorted(SUPPORTED_PROFILES), required=True)
    parser.add_argument("--output", type=Path, help="Write rendered env to this file. Defaults to stdout.")
    parser.add_argument("--check", action="store_true", help="Fail if --output content differs from rendered output.")
    parser.add_argument(
        "--merge-env-file",
        type=Path,
        help="Render full schema while preserving values from an existing env file.",
    )
    return parser.parse_args()


def render_env(schema: dict, profile: str, existing_values: dict[str, str] | None = None) -> str:
    profile_meta = schema.get("profiles", {}).get(profile, {})
    lines: list[str] = []
    title = profile_meta.get("title") or f"Skillra {profile} environment"
    description = profile_meta.get("description")
    lines.append(f"# {title}")
    if description:
        lines.append(f"# {description}")
    lines.append("# Generated from infra/env/schema.yml. Do not edit examples by hand.")

    current_group: str | None = None
    for env_var in iter_env_vars(schema):
        required_profiles = env_var.spec.get("required") or []
        has_profile_default = profile_value(env_var.spec, "default", profile) is not None
        has_required_when = bool(env_var.spec.get("required_when"))
        if not has_profile_default and profile not in required_profiles and not has_required_when:
            continue
        value = (existing_values or {}).get(env_var.name)
        if value is None:
            value = default_value(env_var.spec, profile)
        if env_var.group != current_group:
            lines.append("")
            lines.append(f"# {env_var.group}")
            current_group = env_var.group
        lines.append(f"{env_var.name}={value or ''}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = _parse_args()
    schema = load_schema(args.schema)
    existing_values: dict[str, str] | None = None
    if args.merge_env_file:
        existing_values, _duplicates = parse_env_file(args.merge_env_file)
    rendered = render_env(schema, args.profile, existing_values=existing_values)

    if args.check:
        if not args.output:
            raise SystemExit("--check requires --output")
        existing = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if existing != rendered:
            sys.stderr.write(f"{args.output} is not in sync with {args.schema}\n")
            raise SystemExit(1)
        return

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
