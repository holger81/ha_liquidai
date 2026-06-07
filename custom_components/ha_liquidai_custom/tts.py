"""LiquidAI TTS entity."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components import ffmpeg
from homeassistant.components.tts import (
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    TtsAudioType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audio import (
    concat_wav_buffers,
    extract_pcm,
    make_silence_pcm,
    pop_complete_sentence,
    pop_early_chunk,
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
    CONF_STREAM_FIRST_CHUNK_CHARS,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_LANGUAGE,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    KEEP_EDGE_MS,
    LOGGER,
    MAX_CHUNK_LEN,
    SILENCE_THRESHOLD,
    STREAM_FIRST_CHUNK_CHARS,
    SUPPORTED_LANGUAGES,
)

# HA converts TTS to mp3 for playback; raw pcm breaks ffmpeg conversion.
STREAM_EXTENSION = "mp3"
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

    @property
    def stream_first_chunk_chars(self) -> int:
        """Return minimum chars before the first streaming TTS chunk."""
        return int(
            self._entry.options.get(
                CONF_STREAM_FIRST_CHUNK_CHARS, STREAM_FIRST_CHUNK_CHARS
            )
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
        """Yield mp3 chunks for each completed sentence."""
        template_wav: bytes | None = None
        sample_rate: int | None = None
        async for sentence in self._message_to_sentences(request.message_gen):
            wav = await self._client.synthesize(sentence)
            if template_wav is None:
                template_wav = wav
                sample_rate = read_sample_rate(wav)
            wav_chunk = self._trimmed_wav(wav)
            if wav_chunk:
                yield await self._convert_wav_to_mp3(wav_chunk)
            if (
                self.chunk_gap_ms > 0
                and sample_rate is not None
                and template_wav is not None
            ):
                gap_wav = rebuild_wav(
                    template_wav,
                    make_silence_pcm(sample_rate, self.chunk_gap_ms),
                )
                yield await self._convert_wav_to_mp3(gap_wav)

    def _trimmed_wav(self, wav: bytes) -> bytes:
        """Return a trimmed WAV buffer."""
        sample_rate = read_sample_rate(wav)
        trimmed = trim_pcm_silence(
            extract_pcm(wav),
            sample_rate,
            threshold=self.silence_threshold,
            keep_edge_ms=self.keep_edge_ms,
        )
        if not trimmed:
            return b""
        return rebuild_wav(wav, trimmed)

    async def _convert_wav_to_mp3(self, wav: bytes) -> bytes:
        """Convert WAV bytes to MP3 using Home Assistant ffmpeg."""
        ffmpeg_manager = ffmpeg.get_ffmpeg_manager(self.hass)
        command = [
            ffmpeg_manager.binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "mp3",
            "-q:a",
            "0",
            "pipe:1",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(wav)
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise HomeAssistantError(f"ffmpeg mp3 conversion failed: {detail}")
        if not stdout:
            raise HomeAssistantError("ffmpeg mp3 conversion returned empty audio")
        return stdout

    async def _message_to_sentences(
        self, message_gen: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """Convert a text stream into speakable sentences."""
        buffer = ""
        first_chunk_sent = False
        min_early = self.stream_first_chunk_chars

        async for delta in message_gen:
            buffer += delta
            while True:
                sentence, buffer = pop_complete_sentence(buffer)
                if sentence is None:
                    break
                plain = sanitize_for_tts(sentence)
                if plain:
                    first_chunk_sent = True
                    LOGGER.debug("Streaming sentence (%d chars)", len(plain))
                    yield plain

            if not first_chunk_sent and min_early > 0:
                early, buffer = pop_early_chunk(buffer, min_early)
                if early:
                    plain = sanitize_for_tts(early)
                    if plain:
                        first_chunk_sent = True
                        LOGGER.debug(
                            "Streaming early chunk (%d chars)", len(plain)
                        )
                        yield plain

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
