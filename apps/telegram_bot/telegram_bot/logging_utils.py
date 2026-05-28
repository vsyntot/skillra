"""Logging helpers that avoid PII."""

from __future__ import annotations

import hashlib
from typing import Any


def mask_user_id(user_id: Any) -> str:
    """Mask Telegram user ids before logging."""

    if user_id is None:
        return "anonymous"
    digest = hashlib.sha256(str(user_id).encode()).hexdigest()
    return digest[:10]
