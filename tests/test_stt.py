"""Unit tests for LiquidAI STT parallel ASR + embed."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from conftest import ConfigEntry, HomeAssistantError, load_component_module, make_hass

client = load_component_module("client")
voice_cache = load_component_module("voice_cache")
stt = load_component_module("stt")


def _make_entity(
    *, speaker_embed_enabled: bool, grace: float | None = None
) -> stt.LiquidAiSttEntity:
    entity = stt.LiquidAiSttEntity.__new__(stt.LiquidAiSttEntity)
    entity.hass = make_hass()
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
    options = {"speaker_embed_enabled": speaker_embed_enabled}
    if grace is not None:
        options["speaker_embed_grace"] = grace
    entity._entry = ConfigEntry(
        data={"base_url": "http://example:8811"},
        options=options,
        entry_id="entry-1",
    )
    return entity


def _metadata() -> MagicMock:
    metadata = MagicMock()
    metadata.format = stt.AudioFormats.WAV
    metadata.codec = stt.AudioCodecs.PCM
    metadata.sample_rate = 16000
    metadata.channel = 1
    metadata.bit_rate = 16
    return metadata


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
        side_effect=HomeAssistantError("embed down")
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


def test_speaker_embed_enabled_falls_back_to_entry_data() -> None:
    """Entries created before the options flow still honour entry.data."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._entry = ConfigEntry(
        data={"base_url": "http://x", "speaker_embed_enabled": False},
        options={},
    )
    assert entity.speaker_embed_enabled is False

    entity._entry.options["speaker_embed_enabled"] = True
    assert entity.speaker_embed_enabled is True


@pytest.mark.asyncio
async def test_asr_not_blocked_by_slow_embed() -> None:
    """Slow or stuck embed calls do not delay the ASR transcript."""
    entity = _make_entity(speaker_embed_enabled=True, grace=0.05)

    async def slow_embed(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {"embedding": [0.1], "quality": "ok"}

    entity._client.embed_speaker = slow_embed

    started = time.monotonic()
    text, embed_result = await entity._transcribe_and_embed(b"RIFF")
    elapsed = time.monotonic() - started

    assert text == "hello world"
    assert embed_result is None
    assert elapsed < 1.0


def test_speaker_embed_grace_defaults_and_options() -> None:
    entity = _make_entity(speaker_embed_enabled=True)
    assert entity.speaker_embed_grace == stt.SPEAKER_EMBED_GRACE_SECONDS

    entity._entry.options["speaker_embed_grace"] = 1.5
    assert entity.speaker_embed_grace == 1.5


@pytest.mark.asyncio
async def test_missing_embed_endpoint_disables_further_attempts() -> None:
    """HTTP 404 on embed disables fingerprinting for the rest of the session."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._client.embed_speaker = AsyncMock(
        side_effect=client.LiquidAiHttpError("speaker embed", 404, "not found")
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
async def test_transient_embed_http_error_keeps_endpoint_enabled() -> None:
    """A 500 is a transient failure; the next utterance tries again."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._client.embed_speaker = AsyncMock(
        side_effect=client.LiquidAiHttpError("speaker embed", 500, "boom")
    )

    await entity._transcribe_and_embed(b"RIFF")
    await entity._transcribe_and_embed(b"RIFF")

    assert entity._client.embed_speaker.await_count == 2


@pytest.mark.asyncio
async def test_voice_cache_store_failure_does_not_break_stt() -> None:
    """Cache write errors must not turn a successful transcript into STT failure."""
    entity = _make_entity(speaker_embed_enabled=True)
    entity._prepare_wav_for_asr = AsyncMock(return_value=b"RIFF")
    entity._transcribe_and_embed = AsyncMock(return_value=("hello world", None))

    async def stream():
        yield b"pcm"

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(
            stt,
            "store_voice_turn",
            MagicMock(side_effect=RuntimeError("cache down")),
        )
        result = await entity.async_process_audio_stream(_metadata(), stream())

    assert result.text == "hello world"
    assert result.state == stt.SpeechResultState.SUCCESS


@pytest.mark.asyncio
async def test_process_audio_stream_wraps_pcm_and_stores_voice_turn() -> None:
    """Headerless PCM from Assist is wrapped in WAV and the turn is cached."""
    entity = _make_entity(speaker_embed_enabled=True)

    async def stream():
        yield b"\x00\x01" * 800
        yield b"\x00\x01" * 800

    result = await entity.async_process_audio_stream(_metadata(), stream())

    assert result.text == "hello world"
    sent_wav = entity._client.transcribe.call_args.args[0]
    assert sent_wav.startswith(b"RIFF")
    assert len(sent_wav) == 44 + 3200
    turns = entity.hass.data[voice_cache.DATA_VOICE_TURNS]
    assert len(turns) == 1
    assert turns[0].embedding == [0.1, 0.2]


@pytest.mark.asyncio
async def test_process_audio_stream_asr_error_returns_error_state() -> None:
    entity = _make_entity(speaker_embed_enabled=False)
    entity._client.transcribe = AsyncMock(side_effect=HomeAssistantError("down"))

    async def stream():
        yield b"\x00\x01" * 10

    result = await entity.async_process_audio_stream(_metadata(), stream())

    assert result.text is None
    assert result.state == stt.SpeechResultState.ERROR


@pytest.mark.asyncio
async def test_process_audio_stream_empty_input() -> None:
    entity = _make_entity(speaker_embed_enabled=False)

    async def stream():
        if False:
            yield b""

    result = await entity.async_process_audio_stream(_metadata(), stream())

    assert result.text == ""
    assert result.state == stt.SpeechResultState.SUCCESS
    entity._client.transcribe.assert_not_called()
