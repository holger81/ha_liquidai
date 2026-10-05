"""Unit tests for the LiquidAI TTS entity (one-shot and streaming paths)."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from conftest import ConfigEntry, TTSAudioRequest, load_component_module, make_hass

audio = load_component_module("audio")
tts = load_component_module("tts")


def _wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    return audio.pcm_to_wav(pcm, sample_rate=sample_rate)


LOUD_WAV = _wav(b"\x00\x00" * 500 + struct.pack("<h", 20000) * 2000 + b"\x00\x00" * 500)


def _make_entity(options: dict | None = None) -> tts.LiquidAiTtsEntity:
    entity = tts.LiquidAiTtsEntity.__new__(tts.LiquidAiTtsEntity)
    entity.hass = make_hass()
    entity._entry = ConfigEntry(
        data={"base_url": "http://example:8811"}, options=options or {}
    )
    entity._client = MagicMock()
    entity._client.synthesize = AsyncMock(return_value=LOUD_WAV)
    entity._synth_semaphore = asyncio.Semaphore(tts.TTS_MAX_CONCURRENT_REQUESTS)
    entity._gap_mp3_cache = {}
    # ffmpeg is not available in unit tests; tag the output instead.
    entity._ffmpeg_wav = AsyncMock(
        side_effect=lambda wav, *, output_format, streaming=False: (
            f"{output_format}:".encode() + wav[:4] + len(wav).to_bytes(4, "little")
        )
    )
    return entity


async def _gen(*parts: str) -> AsyncGenerator[str, None]:
    for part in parts:
        yield part


async def _collect(agen) -> list:
    return [item async for item in agen]


@pytest.mark.asyncio
async def test_message_to_sentences_splits_on_whitespace_terminated_punctuation():
    entity = _make_entity({"stream_first_chunk_chars": 0})
    sentences = await _collect(
        entity._message_to_sentences(
            _gen("It is 21", ".5 degrees. ", "Dr. Who", " called. The end.")
        )
    )
    assert sentences == ["It is 21.5 degrees.", "Dr. Who called.", "The end."]


@pytest.mark.asyncio
async def test_message_to_sentences_emits_early_chunk_then_sentences():
    entity = _make_entity({"stream_first_chunk_chars": 10})
    sentences = await _collect(
        entity._message_to_sentences(
            _gen("Turning on the kitchen ", "lights now. Anything else?")
        )
    )
    assert sentences[0].startswith("Turning on")
    assert sentences[-1] == "Anything else?"
    assert " ".join(sentences).replace("  ", " ") == (
        "Turning on the kitchen lights now. Anything else?"
    )


@pytest.mark.asyncio
async def test_message_to_sentences_flushes_tail_without_punctuation():
    entity = _make_entity({"stream_first_chunk_chars": 0})
    sentences = await _collect(entity._message_to_sentences(_gen("Done. Bye")))
    assert sentences == ["Done.", "Bye"]


@pytest.mark.asyncio
async def test_message_to_sentences_sanitizes_markdown():
    entity = _make_entity({"stream_first_chunk_chars": 0})
    sentences = await _collect(
        entity._message_to_sentences(_gen("**Bold** and `code`. [link](http://x) ok."))
    )
    assert sentences == ["Bold and code.", "link ok."]


@pytest.mark.asyncio
async def test_oneshot_single_chunk_returns_wav():
    entity = _make_entity()
    extension, data = await entity.async_get_tts_audio("Hello there.", "en-US", {})
    assert extension == "wav"
    assert data.startswith(b"RIFF")
    entity._client.synthesize.assert_awaited_once_with("Hello there.")
    entity._ffmpeg_wav.assert_not_called()


@pytest.mark.asyncio
async def test_oneshot_multi_chunk_bounds_concurrency():
    entity = _make_entity({"chunk_gap_ms": 0})
    in_flight = 0
    peak = 0

    async def synth(_text: str) -> bytes:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return LOUD_WAV

    entity._client.synthesize = synth
    text = " ".join(f"Sentence number {i}." for i in range(6))

    extension, data = await entity.async_get_tts_audio(text, "en-US", {})

    assert extension == "wav"
    assert data.startswith(b"RIFF")
    assert peak == tts.TTS_MAX_CONCURRENT_REQUESTS


@pytest.mark.asyncio
async def test_oneshot_applies_speed_via_ffmpeg():
    entity = _make_entity({"speech_speed": 1.25})
    _, data = await entity.async_get_tts_audio("Fast.", "en-US", {})
    assert data.startswith(b"wav:")
    entity._ffmpeg_wav.assert_awaited_once()
    assert entity._ffmpeg_wav.call_args.kwargs["output_format"] == "wav"


@pytest.mark.asyncio
async def test_oneshot_empty_message_returns_none():
    entity = _make_entity()
    assert await entity.async_get_tts_audio("   ", "en-US", {}) == (None, None)
    entity._client.synthesize.assert_not_called()


@pytest.mark.asyncio
async def test_stream_yields_mp3_per_sentence_and_caches_gap():
    entity = _make_entity({"chunk_gap_ms": 5, "stream_first_chunk_chars": 0})
    request = TTSAudioRequest(message_gen=_gen("One. Two. ", "Three."))

    response = await entity.async_stream_tts_audio(request)
    chunks = await _collect(response.data_gen)

    assert response.extension == "mp3"
    assert entity._client.synthesize.await_count == 3
    # Three sentences => two gaps, but the gap is encoded only once.
    assert len(entity._gap_mp3_cache) == 1
    (gap_mp3,) = entity._gap_mp3_cache.values()
    assert chunks.count(gap_mp3) == 2
    sentence_chunks = [c for c in chunks if c != gap_mp3]
    assert len(sentence_chunks) == 3
    assert all(c.startswith(b"mp3:RIFF") for c in sentence_chunks)
    assert chunks == [
        sentence_chunks[0],
        gap_mp3,
        sentence_chunks[1],
        gap_mp3,
        sentence_chunks[2],
    ]
    # 3 sentence encodes + 1 gap encode
    assert entity._ffmpeg_wav.await_count == 4


@pytest.mark.asyncio
async def test_stream_without_gap_skips_gap_encoding():
    entity = _make_entity({"chunk_gap_ms": 0, "stream_first_chunk_chars": 0})
    request = TTSAudioRequest(message_gen=_gen("One. Two."))

    response = await entity.async_stream_tts_audio(request)
    chunks = await _collect(response.data_gen)

    assert len(chunks) == 2
    assert entity._ffmpeg_wav.await_count == 2
    assert entity._gap_mp3_cache == {}


@pytest.mark.asyncio
async def test_stream_empty_message_yields_nothing():
    entity = _make_entity()
    response = await entity.async_stream_tts_audio(TTSAudioRequest(message_gen=_gen()))
    assert await _collect(response.data_gen) == []
    entity._client.synthesize.assert_not_called()


@pytest.mark.asyncio
async def test_trim_runs_in_executor():
    """PCM trimming must be dispatched off the event loop."""
    entity = _make_entity()
    calls: list = []

    async def tracking_executor(func, *args):
        calls.append(func)
        return func(*args)

    entity.hass.async_add_executor_job = tracking_executor
    await entity.async_get_tts_audio("Hello.", "en-US", {})

    assert any(getattr(f, "__name__", "") == "_trimmed_wav" for f in calls)
