"""LiquidAI STT entity."""

from __future__ import annotations

from collections.abc import AsyncIterable

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


def _mime_from_metadata(metadata: SpeechMetadata) -> str:
    """Map Assist pipeline metadata to LiquidAI ASR type field."""
    if metadata.format == AudioFormats.OGG or metadata.codec == AudioCodecs.OPUS:
        return "audio/ogg"
    return "audio/wav"


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
        self._entry = entry
        self._client = LiquidAiTtsClient(
            async_get_clientsession(hass),
            entry.data[CONF_BASE_URL],
            timeout=entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )
        self._attr_name = "LiquidAI STT"
        self._attr_unique_id = f"{entry.entry_id}_stt"
        self._attr_supported_languages = SUPPORTED_LANGUAGES
        self._attr_default_language = DEFAULT_LANGUAGE

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

        mime_type = _mime_from_metadata(metadata)
        LOGGER.debug(
            "Transcribing %d bytes (%s, %s Hz)",
            len(audio_bytes),
            mime_type,
            metadata.sample_rate,
        )

        try:
            text = await self._client.transcribe(
                audio_bytes,
                mime_type=mime_type,
                system_prompt=self.asr_system_prompt,
            )
        except HomeAssistantError as err:
            LOGGER.warning("LiquidAI ASR failed: %s", err)
            return SpeechResult(None, SpeechResultState.ERROR)

        return SpeechResult(text, SpeechResultState.SUCCESS)
