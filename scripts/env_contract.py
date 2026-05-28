#!/usr/bin/env python3
"""Shared helpers for Skillra env contract tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_PROFILES = {"local", "prod", "staging"}


@dataclass(frozen=True)
class EnvVar:
    name: str
    group: str
    spec: dict[str, Any]


def load_schema(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "groups" not in payload:
        raise ValueError(f"env schema {path} does not contain groups")
    return payload


def iter_env_vars(schema: dict[str, Any]) -> list[EnvVar]:
    variables: list[EnvVar] = []
    for group in schema.get("groups", []):
        group_name = str(group.get("name") or "Ungrouped")
        for name, spec in (group.get("variables") or {}).items():
            variables.append(EnvVar(name=str(name), group=group_name, spec=dict(spec or {})))
    return variables


def profile_value(spec: dict[str, Any], key: str, profile: str) -> Any:
    value = spec.get(key)
    if isinstance(value, dict):
        return value.get(profile)
    return value


def default_value(spec: dict[str, Any], profile: str) -> str | None:
    default = profile_value(spec, "default", profile)
    if default is not None:
        return str(default)
    placeholder = spec.get("placeholder")
    if placeholder is not None:
        return str(placeholder)
    return None


def is_required(spec: dict[str, Any], profile: str, env: dict[str, str] | None = None) -> bool:
    required = spec.get("required") or []
    if profile in required:
        return True
    required_when = spec.get("required_when") or {}
    if required_when and env:
        return all(env.get(str(key)) == str(value) for key, value in required_when.items())
    return False


def parse_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    duplicates: list[str] = []
    if not path.exists():
        return values, duplicates

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in values:
            duplicates.append(key)
        values[key] = value
    return values, duplicates


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.strip().lower()
    return (
        lowered.startswith("changeme")
        or lowered.startswith("change-me")
        or "example.com" in lowered
        or lowered.startswith("replace-")
    )


def schema_key_set(schema: dict[str, Any]) -> set[str]:
    return {env_var.name for env_var in iter_env_vars(schema)}
