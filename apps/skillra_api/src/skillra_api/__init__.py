"""Skillra API package initialization."""

__all__ = [
    "get_settings",
    "Settings",
]

from .config import Settings, get_settings
