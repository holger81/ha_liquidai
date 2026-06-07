"""LiquidAI TTS entity."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components.tts import (
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    TtsAudioType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audio import (
    concat_wav_buffers,
    extract_pcm,
    make_silence_pcm,
    pop_complete_sentence,
    read_sample_rate,
    rebuild_wav,
    sanitize_for_tts,
    split_for_tts,
    trim_pcm_silence,
)
from .client import LiquidAiTtsClient
from .const import (
    CHUNK_GAP_MS,
    CONF_BASE_URL,
    CONF_CHUNK_GAP_MS,
    CONF_KEEP_EDGE_MS,
    CONF_MAX_CHUNK_LEN,
    CONF_SILENCE_THRESHOLD,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_LANGUAGE,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    KEEP_EDGE_MS,
    LOGGER,
    MAX_CHUNK_LEN,
    SILENCE_THRESHOLD,
    SUPPORTED_LANGUAGES,
)

STREAM_EXTENSION = "pcm"
ONESHOT_EXTENSION = "wav"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LiquidAI TTS from a config entry."""
    async_add_entities([LiquidAiTtsEntity(hass, config_entry)])


class LiquidAiTtsEntity(TextToSpeechEntity):
    """LiquidAI text-to-speech provider."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the TTS entity."""
        self._entry = entry
        self._client = LiquidAiTtsClient(
            async_get_clientsession(hass),
            entry.data[CONF_BASE_URL],
            system_prompt=entry.data.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT),
            timeout=entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )
        self._attr_name = "LiquidAI TTS"
        self._attr_unique_id = entry.entry_id
        self._attr_supported_languages = SUPPORTED_LANGUAGES
        self._attr_default_language = DEFAULT_LANGUAGE

    @property
    def max_chunk_len(self) -> int:
        """Return the maximum chunk length."""
        return int(self._entry.options.get(CONF_MAX_CHUNK_LEN, MAX_CHUNK_LEN))

    @property
    def keep_edge_ms(self) -> int:
        """Return PCM edge padding in milliseconds."""
        return int(self._entry.options.get(CONF_KEEP_EDGE_MS, KEEP_EDGE_MS))

    @property
    def chunk_gap_ms(self) -> int:
        """Return silence gap between streamed sentences."""
        return int(self._entry.options.get(CONF_CHUNK_GAP_MS, CHUNK_GAP_MS))

    @property
    def silence_threshold(self) -> int:
        """Return PCM silence threshold."""
        return int(
            self._entry.options.get(CONF_SILENCE_THRESHOLD, SILENCE_THRESHOLD)
        )

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Synthesize one-shot TTS audio."""
        plain_text = sanitize_for_tts(message) or " ".join(message.split())
        if not plain_text:
            return None, None

        chunks = split_for_tts(plain_text, self.max_chunk_len)
        if not chunks:
            return None, None

        if len(chunks) == 1:
            wav = await self._client.synthesize(chunks[0])
            sample_rate = read_sample_rate(wav)
            trimmed = trim_pcm_silence(
                extract_pcm(wav),
                sample_rate,
                threshold=self.silence_threshold,
                keep_edge_ms=self.keep_edge_ms,
            )
            return ONESHOT_EXTENSION, rebuild_wav(wav, trimmed)

        wav_buffers = await asyncio.gather(
            *(self._client.synthesize(chunk) for chunk in chunks)
        )
        merged = concat_wav_buffers(
            list(wav_buffers),
            chunk_gap_ms=self.chunk_gap_ms,
            keep_edge_ms=self.keep_edge_ms,
            threshold=self.silence_threshold,
        )
        return ONESHOT_EXTENSION, merged

    async def async_stream_tts_audio(
        self, request: TTSAudioRequest
    ) -> TTSAudioResponse:
        """Stream TTS audio sentence by sentence."""
        return TTSAudioResponse(
            STREAM_EXTENSION,
            self._audio_gen(request),
        )

    async def _audio_gen(
        self, request: TTSAudioRequest
    ) -> AsyncGenerator[bytes, None]:
        """Yield trimmed PCM chunks for each completed sentence."""
        sample_rate = None
        async for sentence in self._message_to_sentences(request.message_gen):
            wav = await self._client.synthesize(sentence)
            if sample_rate is None:
                sample_rate = read_sample_rate(wav)
            pcm = trim_pcm_silence(
                extract_pcm(wav),
                sample_rate,
                threshold=self.silence_threshold,
                keep_edge_ms=self.keep_edge_ms,
            )
            if pcm:
                yield pcm
            if self.chunk_gap_ms > 0 and sample_rate is not None:
                yield make_silence_pcm(sample_rate, self.chunk_gap_ms)

    async def _message_to_sentences(
        self, message_gen: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """Convert a text stream into speakable sentences."""
        buffer = ""
        async for delta in message_gen:
            buffer += delta
            while True:
                sentence, buffer = pop_complete_sentence(buffer)
                if sentence is None:
                    break
                plain = sanitize_for_tts(sentence)
                if plain:
                    LOGGER.debug("Streaming sentence (%d chars)", len(plain))
                    yield plain

        tail = sanitize_for_tts(buffer.strip())
        if tail:
            LOGGER.debug("Streaming tail sentence (%d chars)", len(tail))
            yield tail
