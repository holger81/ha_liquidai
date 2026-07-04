"""Unit tests for LiquidAI STT parallel ASR + embed."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "ha_liquidai_custom"
)


def _ensure_ha_stubs() -> None:
    if "homeassistant.exceptions" not in sys.modules:
        ha_pkg = types.ModuleType("homeassistant")
        ha_exc = types.ModuleType("homeassistant.exceptions")

        class HomeAssistantError(Exception):
            pass

        ha_exc.HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant"] = ha_pkg
        sys.modules["homeassistant.exceptions"] = ha_exc

    if "homeassistant.core" not in sys.modules:
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = object
        sys.modules["homeassistant.core"] = ha_core

    if "homeassistant.config_entries" not in sys.modules:
        config_entries = types.ModuleType("homeassistant.config_entries")
        config_entries.ConfigEntry = object
        sys.modules["homeassistant.config_entries"] = config_entries

    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = types.ModuleType("homeassistant.helpers")

    if "homeassistant.helpers.entity_platform" not in sys.modules:
        entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
        entity_platform.AddEntitiesCallback = object
        sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    if "homeassistant.helpers.aiohttp_client" not in sys.modules:
        aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
        aiohttp_client.async_get_clientsession = lambda _hass: None
        sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    if "homeassistant.components" not in sys.modules:
        sys.modules["homeassistant.components"] = types.ModuleType(
            "homeassistant.components"
        )
        sys.modules["homeassistant.components.ffmpeg"] = types.ModuleType(
            "homeassistant.components.ffmpeg"
        )

    if "homeassistant.components.stt" not in sys.modules:
        stt_mod = types.ModuleType("homeassistant.components.stt")

        class SpeechToTextEntity:
            pass

        class SpeechResult:
            def __init__(self, text, state):
                self.text = text
                self.state = state

        class SpeechResultState:
            SUCCESS = "success"
            ERROR = "error"

        class _Enum:
            def __init__(self, value):
                self.value = value

        class AudioFormats:
            WAV = _Enum("wav")
            OGG = _Enum("ogg")

        class AudioCodecs:
            PCM = _Enum("pcm")
            OPUS = _Enum("opus")

        class AudioBitRates:
            BITRATE_16 = _Enum(16)

        class AudioSampleRates:
            RATE_16000 = _Enum(16000)

        class AudioChannels:
            CHANNEL_MONO = _Enum(1)
            CHANNEL_STEREO = _Enum(2)

        class SpeechMetadata:
            pass

        stt_mod.SpeechToTextEntity = SpeechToTextEntity
        stt_mod.SpeechResult = SpeechResult
        stt_mod.SpeechResultState = SpeechResultState
        stt_mod.AudioFormats = AudioFormats
        stt_mod.AudioCodecs = AudioCodecs
        stt_mod.AudioBitRates = AudioBitRates
        stt_mod.AudioSampleRates = AudioSampleRates
        stt_mod.AudioChannels = AudioChannels
        stt_mod.SpeechMetadata = SpeechMetadata
        sys.modules["homeassistant.components.stt"] = stt_mod


def _load_module(name: str):
    module_name = f"ha_liquidai_custom.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    if "ha_liquidai_custom" not in sys.modules:
        package = types.ModuleType("ha_liquidai_custom")
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules["ha_liquidai_custom"] = package

    _ensure_ha_stubs()

    deps = {
        "client": ["const"],
        "voice_cache": ["const"],
        "stt": ["const", "client", "voice_cache", "audio"],
    }
    for dep in deps.get(name, []):
        if f"ha_liquidai_custom.{dep}" not in sys.modules:
            _load_module(dep)

    path = COMPONENT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


stt = _load_module("stt")


def _make_entity(*, speaker_embed_enabled: bool) -> stt.LiquidAiSttEntity:
    entity = stt.LiquidAiSttEntity.__new__(stt.LiquidAiSttEntity)
    entity.hass = MagicMock()
    entity.hass.data = {}
    entity._client = MagicMock()
    entity._client.transcribe = AsyncMock(return_value="hello world")
    entity._client.embed_speaker = AsyncMock(
        return_value={
            "embedding": [0.1, 0.2],
            "model": "sherpa-onnx-3dspeaker",
            "quality": "ok",
            "duration_ms": 1000,
        }
    )
    entity._entry = MagicMock()
    entity._entry.entry_id = "entry-1"
    type(entity).speaker_embed_enabled = PropertyMock(
        return_value=speaker_embed_enabled
    )
    type(entity).asr_system_prompt = PropertyMock(return_value="Perform ASR.")
    return entity


@pytest.mark.asyncio
async def test_transcribe_and_embed_runs_both_requests_in_parallel() -> None:
    """ASR and speaker embed both run when embedding is enabled."""
    entity = _make_entity(speaker_embed_enabled=True)

    text, embed_result = await entity._transcribe_and_embed(b"RIFF")

    assert text == "hello world"
    assert embed_result is not None
    assert len(embed_result["embedding"]) == 2
    entity._client.transcribe.assert_awaited_once()
    entity._client.embed_speaker.assert_awaited_once()


@pytest.mark.asyncio
async def test_transcribe_and_embed_continues_when_embed_fails() -> None:
    """Embed failures degrade gracefully while ASR text is returned."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._client.embed_speaker = AsyncMock(
        side_effect=sys.modules["homeassistant.exceptions"].HomeAssistantError(
            "embed down"
        )
    )

    text, embed_result = await entity._transcribe_and_embed(b"RIFF")

    assert text == "hello world"
    assert embed_result is None


@pytest.mark.asyncio
async def test_transcribe_and_embed_skips_embed_when_disabled() -> None:
    """Speaker embedding is skipped when disabled in config."""
    entity = _make_entity(speaker_embed_enabled=False)

    text, embed_result = await entity._transcribe_and_embed(b"RIFF")

    assert text == "hello world"
    assert embed_result is None
    entity._client.embed_speaker.assert_not_called()


@pytest.mark.asyncio
async def test_asr_not_blocked_by_slow_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slow or stuck embed calls do not delay the ASR transcript."""
    entity = _make_entity(speaker_embed_enabled=True)

    async def slow_embed(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {"embedding": [0.1], "quality": "ok"}

    entity._client.embed_speaker = slow_embed
    monkeypatch.setattr(stt, "SPEAKER_EMBED_GRACE_SECONDS", 0.05)

    started = time.monotonic()
    text, embed_result = await entity._transcribe_and_embed(b"RIFF")
    elapsed = time.monotonic() - started

    assert text == "hello world"
    assert embed_result is None
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_missing_embed_endpoint_disables_further_attempts() -> None:
    """HTTP 404 on embed disables fingerprinting for the rest of the session."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._client.embed_speaker = AsyncMock(
        side_effect=sys.modules["homeassistant.exceptions"].HomeAssistantError(
            "LiquidAI speaker embed failed (HTTP 404): not found"
        )
    )

    text, embed_result = await entity._transcribe_and_embed(b"RIFF")
    assert text == "hello world"
    assert embed_result is None
    assert entity._client.embed_speaker.await_count == 1

    text, embed_result = await entity._transcribe_and_embed(b"RIFF")
    assert text == "hello world"
    assert embed_result is None
    assert entity._client.embed_speaker.await_count == 1


@pytest.mark.asyncio
async def test_voice_cache_store_failure_does_not_break_stt() -> None:
    """Cache write errors must not turn a successful transcript into STT failure."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._prepare_wav_for_asr = AsyncMock(return_value=b"RIFF")
    entity._transcribe_and_embed = AsyncMock(return_value=("hello world", None))

    metadata = MagicMock()
    metadata.format = stt.AudioFormats.WAV
    metadata.codec = stt.AudioCodecs.PCM
    metadata.sample_rate = 16000
    metadata.channel = 1

    async def stream():
        yield b"pcm"

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(
            stt,
            "store_voice_turn",
            MagicMock(side_effect=RuntimeError("cache down")),
        )
        result = await entity.async_process_audio_stream(metadata, stream())

    assert result.text == "hello world"
    assert result.state == stt.SpeechResultState.SUCCESS
