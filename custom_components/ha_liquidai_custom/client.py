"""HTTP client for LiquidAI /v1/tts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .const import DEFAULT_SYSTEM_PROMPT, DEFAULT_TIMEOUT, LOGGER

if TYPE_CHECKING:
    from aiohttp import ClientSession


class LiquidAiTtsClient:
    """Async client for LiquidAI text-to-speech."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._system_prompt = system_prompt
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    def base_url(self) -> str:
        """Return the configured base URL."""
        return self._base_url

    async def check_connection(self) -> None:
        """Verify the LiquidAI server is reachable."""
        try:
            async with self._session.get(
                self._base_url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status >= 500:
                    raise HomeAssistantError(
                        f"LiquidAI server returned HTTP {response.status}"
                    )
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
                    body = await response.text()
                    raise HomeAssistantError(
                        f"LiquidAI TTS failed (HTTP {response.status}): {body[:200]}"
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
