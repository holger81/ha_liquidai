"""Helpers for reading config entry settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


def entry_setting(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return a setting from entry.options, falling back to entry.data.

    Settings that started life in ``entry.data`` (e.g. ``speaker_embed_enabled``)
    are now editable in the options flow; options take precedence so the UI
    change wins without migrating old entries.
    """
    options = entry.options or {}
    if key in options:
        return options[key]
    return (entry.data or {}).get(key, default)
