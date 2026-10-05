"""Diagnostics support for LiquidAI."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_URL, DATA_EMBED_UNAVAILABLE
from .voice_cache import DATA_VOICE_TURNS

TO_REDACT = {CONF_BASE_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    embed_unavailable: set[str] = hass.data.get(DATA_EMBED_UNAVAILABLE, set())
    voice_turns = hass.data.get(DATA_VOICE_TURNS, [])
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "version": entry.version,
        },
        "speaker_embed": {
            "endpoint_marked_unavailable": entry.entry_id in embed_unavailable,
            "cached_voice_turns": len(voice_turns),
        },
    }
