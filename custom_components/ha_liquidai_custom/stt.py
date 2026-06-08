"""LiquidAI STT entity."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable

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
    CONF_TIMEOUT,
    DEFAULT_ASR_SYSTEM_PROMPT,
    DEFAULT_LANGUAGE,
    DEFAULT_TIMEOUT,
    LOGGER,
    SUPPORTED_LANGUAGES,
)


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
        self._client = LiquidAiTtsClient(
            async_get_clientsession(hass),
            entry.data[CONF_BASE_URL],
            timeout=entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
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
            text = await self._client.transcribe(
                wav_bytes,
                mime_type="audio/wav",
                system_prompt=self.asr_system_prompt,
            )
        except HomeAssistantError as err:
            LOGGER.warning("LiquidAI ASR failed: %s", err)
            return SpeechResult(None, SpeechResultState.ERROR)

        return SpeechResult(text, SpeechResultState.SUCCESS)

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
