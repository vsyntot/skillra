from __future__ import annotations

try:
    from pydantic._internal import _config
except Exception:  # pragma: no cover - minimal environments without pydantic internals
    _config = None

if _config is not None:
    _config.config_defaults["protected_namespaces"] = ()
