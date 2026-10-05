"""HTTP client for the LiquidAI audio server (/v1/asr, /v1/tts, /v1/speaker/embed)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_ASR_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    EMBED_SOFT_QUALITIES,
    LOGGER,
)

if TYPE_CHECKING:
    from aiohttp import ClientSession

HEALTHZ_PATH = "/healthz"
CONNECTION_CHECK_TIMEOUT = 10


class LiquidAiHttpError(HomeAssistantError):
    """A LiquidAI request returned a non-success HTTP status."""

    def __init__(self, operation: str, status: int, body: str = "") -> None:
        """Initialize with the failing operation and HTTP status."""
        self.operation = operation
        self.status = status
        self.body = body[:200]
        super().__init__(f"LiquidAI {operation} failed (HTTP {status}): {self.body}")


class LiquidAiNotReadyError(HomeAssistantError):
    """The LiquidAI server is reachable but the audio model is not loaded yet."""


class LiquidAiClient:
    """Async client for LiquidAI speech-to-text, text-to-speech and speaker embed."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        timeout: int = DEFAULT_TIMEOUT,
        speaker_embed_timeout: int | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._system_prompt = system_prompt
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        embed_timeout = (
            speaker_embed_timeout if speaker_embed_timeout is not None else timeout
        )
        self._speaker_embed_timeout = aiohttp.ClientTimeout(total=embed_timeout)

    @property
    def base_url(self) -> str:
        """Return the configured base URL."""
        return self._base_url

    async def check_connection(self) -> dict[str, Any]:
        """Verify the LiquidAI server is reachable and its model is ready.

        Prefers ``GET /healthz?ready=1`` (returns 503 while the model loads).
        Falls back to a plain GET on the base URL for servers without
        ``/healthz`` so older deployments still pass the config flow.
        """
        timeout = aiohttp.ClientTimeout(total=CONNECTION_CHECK_TIMEOUT)
        try:
            async with self._session.get(
                f"{self._base_url}{HEALTHZ_PATH}",
                params={"ready": "1"},
                timeout=timeout,
            ) as response:
                if response.status == 200:
                    payload = await response.json(content_type=None)
                    return payload if isinstance(payload, dict) else {}
                if response.status == 503:
                    raise LiquidAiNotReadyError(
                        "LiquidAI server is still loading its audio model"
                    )
                if response.status != 404:
                    raise LiquidAiHttpError(
                        "health check", response.status, await response.text()
                    )

            async with self._session.get(
                self._base_url,
                timeout=timeout,
            ) as response:
                if response.status >= 500:
                    raise LiquidAiHttpError(
                        "connection check", response.status, await response.text()
                    )
                return {}
        except TimeoutError as err:
            raise HomeAssistantError("LiquidAI server timed out") from err
        except aiohttp.ClientError as err:
            raise HomeAssistantError(f"Cannot connect to LiquidAI: {err}") from err

    async def synthesize(self, text: str) -> bytes:
        """Synthesize speech and return raw WAV bytes."""
        if not text.strip():
            raise HomeAssistantError("No speakable text for TTS")

        data = {
            "text": text,
            "system_prompt": self._system_prompt,
        }

        try:
            async with self._session.post(
                f"{self._base_url}/v1/tts",
                data=data,
                timeout=self._timeout,
            ) as response:
                if response.status != 200:
                    raise LiquidAiHttpError(
                        "TTS", response.status, await response.text()
                    )
                wav_bytes = await response.read()
        except TimeoutError as err:
            raise HomeAssistantError("LiquidAI TTS request timed out") from err
        except aiohttp.ClientError as err:
            raise HomeAssistantError(f"LiquidAI TTS request failed: {err}") from err

        if not wav_bytes:
            raise HomeAssistantError("LiquidAI TTS returned empty audio")

        LOGGER.debug(
            "Synthesized %d bytes for %d characters",
            len(wav_bytes),
            len(text),
        )
        return wav_bytes

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/wav",
        system_prompt: str = DEFAULT_ASR_SYSTEM_PROMPT,
    ) -> str:
        """Transcribe audio and return plain text."""
        if not audio_bytes:
            return ""

        form = _audio_form(audio_bytes, mime_type)
        form.add_field("system_prompt", system_prompt)

        try:
            async with self._session.post(
                f"{self._base_url}/v1/asr",
                data=form,
                timeout=self._timeout,
            ) as response:
                if response.status != 200:
                    raise LiquidAiHttpError(
                        "ASR", response.status, await response.text()
                    )
                payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise HomeAssistantError("LiquidAI ASR request timed out") from err
        except aiohttp.ClientError as err:
            raise HomeAssistantError(f"LiquidAI ASR request failed: {err}") from err

        text = str(payload.get("text", "")).strip()
        LOGGER.debug(
            "Transcribed %d bytes to %d characters",
            len(audio_bytes),
            len(text),
        )
        return text

    async def embed_speaker(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/wav",
    ) -> dict[str, Any]:
        """Return speaker embedding payload from /v1/speaker/embed."""
        if not audio_bytes:
            raise HomeAssistantError("No audio for speaker embedding")

        form = _audio_form(audio_bytes, mime_type)

        try:
            async with self._session.post(
                f"{self._base_url}/v1/speaker/embed",
                data=form,
                timeout=self._speaker_embed_timeout,
            ) as response:
                if response.status != 200:
                    raise LiquidAiHttpError(
                        "speaker embed", response.status, await response.text()
                    )
                payload = await response.json(content_type=None)
        except TimeoutError as err:
            raise HomeAssistantError(
                "LiquidAI speaker embed request timed out"
            ) from err
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"LiquidAI speaker embed request failed: {err}"
            ) from err

        if not isinstance(payload, dict):
            raise HomeAssistantError("LiquidAI speaker embed returned invalid JSON")

        embedding = payload.get("embedding")
        quality = str(payload.get("quality") or "ok")
        if isinstance(embedding, list) and embedding:
            if not all(isinstance(value, (int, float)) for value in embedding):
                raise HomeAssistantError(
                    "LiquidAI speaker embed returned non-numeric embedding"
                )
            LOGGER.debug(
                "Embedded %d bytes to %d-d vector (quality=%s)",
                len(audio_bytes),
                len(embedding),
                quality,
            )
            return payload

        if quality in EMBED_SOFT_QUALITIES:
            LOGGER.debug(
                "Speaker embed returned soft quality=%s without vector",
                quality,
            )
            return {
                **payload,
                "embedding": [],
                "quality": quality,
            }

        raise HomeAssistantError("LiquidAI speaker embed returned empty embedding")


def _audio_form(audio_bytes: bytes, mime_type: str) -> aiohttp.FormData:
    """Build the multipart form shared by ASR and speaker embed."""
    filename = "audio.ogg" if "ogg" in mime_type else "audio.wav"
    form = aiohttp.FormData()
    form.add_field("type", mime_type)
    form.add_field(
        "audio",
        audio_bytes,
        filename=filename,
        content_type=mime_type,
    )
    return form
