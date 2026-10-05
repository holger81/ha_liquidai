"""Unit tests for diagnostics and settings helpers."""

from __future__ import annotations

import pytest

from conftest import ConfigEntry, load_component_module, make_hass

const = load_component_module("const")
settings = load_component_module("settings")
voice_cache = load_component_module("voice_cache")
diagnostics = load_component_module("diagnostics")


def test_entry_setting_prefers_options_over_data() -> None:
    entry = ConfigEntry(data={"k": "data"}, options={"k": "opt"})
    assert settings.entry_setting(entry, "k", "default") == "opt"
    entry.options.clear()
    assert settings.entry_setting(entry, "k", "default") == "data"
    entry.data.clear()
    assert settings.entry_setting(entry, "k", "default") == "default"


@pytest.mark.asyncio
async def test_diagnostics_redacts_url_and_reports_embed_state() -> None:
    hass = make_hass()
    entry = ConfigEntry(
        data={const.CONF_BASE_URL: "http://192.168.10.31:8811", "timeout": 120},
        options={const.CONF_SPEAKER_EMBED_ENABLED: True},
        entry_id="entry-1",
    )
    hass.data[const.DATA_EMBED_UNAVAILABLE] = {"entry-1"}
    voice_cache.store_voice_turn(
        hass, voice_cache.build_voice_turn_payload("hello", None)
    )

    result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"]["data"][const.CONF_BASE_URL] == "**REDACTED**"
    assert result["entry"]["data"]["timeout"] == 120
    assert result["entry"]["options"] == {const.CONF_SPEAKER_EMBED_ENABLED: True}
    assert result["speaker_embed"]["endpoint_marked_unavailable"] is True
    assert result["speaker_embed"]["cached_voice_turns"] == 1
