"""LiquidAI STT entity."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable
from typing import Any

from homeassistant.components import ffmpeg
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audio import is_wav, pcm_to_wav
from .client import LiquidAiTtsClient
from .const import (
    CONF_ASR_SYSTEM_PROMPT,
    CONF_BASE_URL,
    CONF_SPEAKER_EMBED_ENABLED,
    CONF_SPEAKER_EMBED_TIMEOUT,
    CONF_TIMEOUT,
    DATA_EMBED_UNAVAILABLE,
    DEFAULT_ASR_SYSTEM_PROMPT,
    DEFAULT_LANGUAGE,
    DEFAULT_SPEAKER_EMBED_ENABLED,
    DEFAULT_SPEAKER_EMBED_TIMEOUT,
    DEFAULT_TIMEOUT,
    LOGGER,
    SPEAKER_EMBED_GRACE_SECONDS,
    SUPPORTED_LANGUAGES,
)
from .voice_cache import build_voice_turn_payload, store_voice_turn


def _embed_unavailable_entries(hass: HomeAssistant) -> set[str]:
    return hass.data.setdefault(DATA_EMBED_UNAVAILABLE, set())


def _is_embed_available(hass: HomeAssistant, entry_id: str) -> bool:
    return entry_id not in _embed_unavailable_entries(hass)


def _mark_embed_unavailable(
    hass: HomeAssistant,
    entry_id: str,
    err: BaseException,
) -> None:
    entries = _embed_unavailable_entries(hass)
    if entry_id not in entries:
        LOGGER.warning(
            "Speaker embedding unavailable for this session (%s); "
            "STT continues without voice fingerprinting",
            err,
        )
    entries.add(entry_id)


def _is_embed_endpoint_missing(err: BaseException) -> bool:
    message = str(err)
    return any(token in message for token in ("HTTP 404", "HTTP 405", "HTTP 501"))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LiquidAI STT from a config entry."""
    async_add_entities([LiquidAiSttEntity(hass, config_entry)])


class LiquidAiSttEntity(SpeechToTextEntity):
    """LiquidAI speech-to-text provider."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the STT entity."""
        self.hass = hass
        self._entry = entry
        request_timeout = entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        embed_timeout = entry.data.get(
            CONF_SPEAKER_EMBED_TIMEOUT, DEFAULT_SPEAKER_EMBED_TIMEOUT
        )
        self._client = LiquidAiTtsClient(
            async_get_clientsession(hass),
            entry.data[CONF_BASE_URL],
            timeout=request_timeout,
            speaker_embed_timeout=embed_timeout,
        )
        self._attr_name = "LiquidAI STT"
        self._attr_unique_id = f"{entry.entry_id}_stt"
        self._attr_default_language = DEFAULT_LANGUAGE

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages."""
        return list(SUPPORTED_LANGUAGES)

    @property
    def asr_system_prompt(self) -> str:
        """Return the ASR system prompt."""
        return self._entry.data.get(CONF_ASR_SYSTEM_PROMPT, DEFAULT_ASR_SYSTEM_PROMPT)

    @property
    def speaker_embed_enabled(self) -> bool:
        """Return whether speaker embedding is enabled."""
        return self._entry.data.get(
            CONF_SPEAKER_EMBED_ENABLED,
            DEFAULT_SPEAKER_EMBED_ENABLED,
        )

    @property
    def supported_formats(self) -> list[AudioFormats]:
        """Return supported audio container formats."""
        return [AudioFormats.WAV, AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return supported audio codecs."""
        return [AudioCodecs.PCM, AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return supported bit rates."""
        return [AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return supported sample rates."""
        return list(AudioSampleRates)

    @property
    def supported_channels(self) -> list[AudioChannels]:
        """Return supported channel counts."""
        return [AudioChannels.CHANNEL_MONO, AudioChannels.CHANNEL_STEREO]

    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Transcribe an Assist audio stream via LiquidAI ASR."""
        audio_bytes = b""
        async for chunk in stream:
            audio_bytes += chunk

        if not audio_bytes:
            return SpeechResult("", SpeechResultState.SUCCESS)

        LOGGER.debug(
            "Transcribing %d bytes (%s/%s, %s Hz, %s ch)",
            len(audio_bytes),
            metadata.format,
            metadata.codec,
            metadata.sample_rate,
            metadata.channel,
        )

        try:
            wav_bytes = await self._prepare_wav_for_asr(audio_bytes, metadata)
            text, embed_result = await self._transcribe_and_embed(wav_bytes)
        except HomeAssistantError as err:
            LOGGER.warning("LiquidAI ASR failed: %s", err)
            return SpeechResult(None, SpeechResultState.ERROR)

        if self.speaker_embed_enabled and _is_embed_available(
            self.hass, self._entry.entry_id
        ):
            satellite_id = getattr(metadata, "satellite_id", None) or getattr(
                metadata, "device_id", None
            )
            self._safe_store_voice_turn(text, embed_result, satellite_id=satellite_id)

        return SpeechResult(text, SpeechResultState.SUCCESS)

    def _safe_store_voice_turn(
        self,
        text: str,
        embed_result: dict[str, Any] | None,
        *,
        satellite_id: str | None = None,
    ) -> None:
        """Store voice metadata without affecting STT success."""
        try:
            store_voice_turn(
                self.hass,
                build_voice_turn_payload(
                    text,
                    embed_result,
                    satellite_id=satellite_id,
                ),
            )
        except Exception as err:
            LOGGER.debug("Voice turn cache store failed (ignored): %s", err)

    async def _transcribe_and_embed(
        self,
        wav_bytes: bytes,
    ) -> tuple[str, dict[str, Any] | None]:
        """Transcribe audio and optionally fetch a speaker embedding."""
        if not self.speaker_embed_enabled or not _is_embed_available(
            self.hass, self._entry.entry_id
        ):
            text = await self._client.transcribe(
                wav_bytes,
                mime_type="audio/wav",
                system_prompt=self.asr_system_prompt,
            )
            return text, None

        embed_task = asyncio.create_task(
            self._client.embed_speaker(wav_bytes, mime_type="audio/wav")
        )
        try:
            text = await self._client.transcribe(
                wav_bytes,
                mime_type="audio/wav",
                system_prompt=self.asr_system_prompt,
            )
        except HomeAssistantError:
            embed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await embed_task
            raise

        embed_result = await self._await_embed_result(embed_task)
        return text, embed_result

    async def _await_embed_result(
        self,
        embed_task: asyncio.Task[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return embed result without delaying ASR beyond a short grace window."""
        try:
            if embed_task.done():
                return self._resolve_embed_task(embed_task)
            return await asyncio.wait_for(
                asyncio.shield(embed_task),
                timeout=SPEAKER_EMBED_GRACE_SECONDS,
            )
        except TimeoutError:
            embed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await embed_task
            LOGGER.debug(
                "Speaker embed did not finish within %.1fs after ASR; "
                "continuing without fingerprint",
                SPEAKER_EMBED_GRACE_SECONDS,
            )
            return None
        except HomeAssistantError as err:
            return self._handle_embed_error(err)
        except Exception as err:
            LOGGER.warning(
                "LiquidAI speaker embed failed (ASR succeeded): %s",
                err,
            )
            return None

    def _handle_embed_error(self, err: HomeAssistantError) -> dict[str, Any] | None:
        if _is_embed_endpoint_missing(err):
            _mark_embed_unavailable(self.hass, self._entry.entry_id, err)
        else:
            LOGGER.warning(
                "LiquidAI speaker embed failed (ASR succeeded): %s",
                err,
            )
        return None

    def _resolve_embed_task(
        self,
        embed_task: asyncio.Task[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Convert a finished embed task into a result or graceful None."""
        try:
            return embed_task.result()
        except HomeAssistantError as err:
            return self._handle_embed_error(err)
        except Exception as err:
            LOGGER.warning(
                "LiquidAI speaker embed failed (ASR succeeded): %s",
                err,
            )
            return None

    async def _prepare_wav_for_asr(
        self,
        audio_bytes: bytes,
        metadata: SpeechMetadata,
    ) -> bytes:
        """Convert Assist pipeline audio into a WAV file for LiquidAI ASR."""
        if is_wav(audio_bytes):
            return audio_bytes

        if metadata.format == AudioFormats.WAV and metadata.codec == AudioCodecs.PCM:
            return pcm_to_wav(
                audio_bytes,
                sample_rate=int(metadata.sample_rate),
                channels=int(metadata.channel),
                bit_rate=int(metadata.bit_rate),
            )

        return await self._ffmpeg_to_wav(audio_bytes, metadata)

    async def _ffmpeg_to_wav(
        self,
        audio_bytes: bytes,
        metadata: SpeechMetadata,
    ) -> bytes:
        """Decode encoded Assist audio to WAV using ffmpeg."""
        ffmpeg_manager = ffmpeg.get_ffmpeg_manager(self.hass)
        input_format = "ogg" if metadata.format == AudioFormats.OGG else None
        command = [
            ffmpeg_manager.binary,
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if input_format:
            command.extend(["-f", input_format])
        command.extend(
            [
                "-i",
                "pipe:0",
                "-ac",
                str(int(metadata.channel)),
                "-ar",
                str(int(metadata.sample_rate)),
                "-f",
                "wav",
                "pipe:1",
            ]
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(audio_bytes)
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise HomeAssistantError(f"ffmpeg WAV conversion failed: {detail}")
        if not stdout:
            raise HomeAssistantError("ffmpeg WAV conversion returned empty audio")
        return stdout
