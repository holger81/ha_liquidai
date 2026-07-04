"""Unit tests for voice turn cache."""

from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "ha_liquidai_custom"
)


def _load_module(name: str):
    module_name = f"ha_liquidai_custom.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    if "ha_liquidai_custom" not in sys.modules:
        package = types.ModuleType("ha_liquidai_custom")
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules["ha_liquidai_custom"] = package

    if name == "voice_cache" and "homeassistant.core" not in sys.modules:
        ha_pkg = types.ModuleType("homeassistant")
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = object
        sys.modules["homeassistant"] = ha_pkg
        sys.modules["homeassistant.core"] = ha_core

    path = COMPONENT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_module("const")
voice_cache = _load_module("voice_cache")


def _fake_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    return hass


def test_build_voice_turn_payload_parses_embedding() -> None:
    """Embed JSON is converted into a cache payload."""
    payload = voice_cache.build_voice_turn_payload(
        "Turn on the lights",
        {
            "embedding": [0.1, -0.2, 0.3],
            "model": "sherpa-onnx-3dspeaker",
            "quality": "ok",
            "duration_ms": 1200,
        },
    )

    assert payload.text == "Turn on the lights"
    assert payload.embedding == [0.1, -0.2, 0.3]
    assert payload.model == "sherpa-onnx-3dspeaker"
    assert payload.quality == "ok"
    assert payload.duration_ms == 1200
    assert payload.match_key == voice_cache.make_voice_match_key("Turn on the lights")


def test_store_and_pop_matching_voice_turn() -> None:
    """Most recent matching entry is returned within the match window."""
    hass = _fake_hass()
    now = time.monotonic()
    payload = voice_cache.VoiceTurnPayload(
        text="Hello there",
        embedding=[0.5],
        model="sherpa-onnx-3dspeaker",
        quality="ok",
        duration_ms=900,
        created_at=now,
        match_key=voice_cache.make_voice_match_key("Hello there"),
    )
    voice_cache.store_voice_turn(hass, payload)

    matched = voice_cache.pop_matching_voice_turn(hass, user_text="  hello   there ")

    assert matched is payload
    assert voice_cache.pop_matching_voice_turn(hass, user_text="hello there") is None


def test_pop_matching_voice_turn_prefers_satellite() -> None:
    """Exact satellite match wins over a legacy text-only entry."""
    hass = _fake_hass()
    now = time.monotonic()
    legacy = voice_cache.VoiceTurnPayload(
        text="Turn on the lights",
        embedding=[0.1],
        model="sherpa-onnx-3dspeaker",
        quality="ok",
        duration_ms=900,
        created_at=now,
        match_key=voice_cache.make_voice_match_key("Turn on the lights"),
        satellite_id=None,
    )
    scoped = voice_cache.VoiceTurnPayload(
        text="Turn on the lights",
        embedding=[0.2],
        model="sherpa-onnx-3dspeaker",
        quality="ok",
        duration_ms=900,
        created_at=now + 0.01,
        match_key=voice_cache.make_voice_match_key(
            "Turn on the lights",
            satellite_id="sat-kitchen",
        ),
        satellite_id="sat-kitchen",
    )
    voice_cache.store_voice_turn(hass, legacy)
    voice_cache.store_voice_turn(hass, scoped)

    matched = voice_cache.pop_matching_voice_turn(
        hass,
        user_text="turn on the lights",
        satellite_id="sat-kitchen",
    )

    assert matched is scoped


def test_prune_expired_voice_turns() -> None:
    """Expired entries are removed on store and pop."""
    hass = _fake_hass()
    stale = voice_cache.VoiceTurnPayload(
        text="old",
        embedding=None,
        model=None,
        quality="skipped",
        duration_ms=None,
        created_at=time.monotonic() - 10,
        match_key=voice_cache.make_voice_match_key("old"),
    )
    voice_cache.store_voice_turn(hass, stale)
    voice_cache.prune_voice_turns(hass)

    assert hass.data[voice_cache.DATA_VOICE_TURNS] == []


def test_pop_voice_turn_by_match_key() -> None:
    """Explicit match key lookup removes the matching entry."""
    hass = _fake_hass()
    payload = voice_cache.build_voice_turn_payload("News please", None)
    voice_cache.store_voice_turn(hass, payload)

    popped = voice_cache.pop_voice_turn(
        hass,
        text="News please",
        match_key=payload.match_key,
    )

    assert popped is payload
