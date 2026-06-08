"""Config flow for LiquidAI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import LiquidAiTtsClient
from .const import (
    CHUNK_GAP_MS,
    CONF_ASR_SYSTEM_PROMPT,
    CONF_BASE_URL,
    CONF_CHUNK_GAP_MS,
    CONF_KEEP_EDGE_MS,
    CONF_MAX_CHUNK_LEN,
    CONF_SILENCE_THRESHOLD,
    CONF_SPEECH_SPEED,
    CONF_STREAM_FIRST_CHUNK_CHARS,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_ASR_SYSTEM_PROMPT,
    DEFAULT_SPEECH_SPEED,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DOMAIN,
    KEEP_EDGE_MS,
    LOGGER,
    MAX_CHUNK_LEN,
    MAX_SPEECH_SPEED,
    MIN_SPEECH_SPEED,
    SILENCE_THRESHOLD,
    STREAM_FIRST_CHUNK_CHARS,
)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_BASE_URL,
                default=defaults.get(CONF_BASE_URL, DEFAULT_URL),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL),
            ),
        }
    )


def _prompt_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SYSTEM_PROMPT,
                default=defaults.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT),
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                ),
            ),
            vol.Required(
                CONF_ASR_SYSTEM_PROMPT,
                default=defaults.get(CONF_ASR_SYSTEM_PROMPT, DEFAULT_ASR_SYSTEM_PROMPT),
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.TEXT,
                    multiline=True,
                ),
            ),
            vol.Optional(
                CONF_TIMEOUT,
                default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=600,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
        }
    )


def _advanced_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_MAX_CHUNK_LEN,
                default=defaults.get(CONF_MAX_CHUNK_LEN, MAX_CHUNK_LEN),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=40,
                    max=500,
                    step=10,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional(
                CONF_KEEP_EDGE_MS,
                default=defaults.get(CONF_KEEP_EDGE_MS, KEEP_EDGE_MS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=500,
                    step=10,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional(
                CONF_CHUNK_GAP_MS,
                default=defaults.get(CONF_CHUNK_GAP_MS, CHUNK_GAP_MS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional(
                CONF_SILENCE_THRESHOLD,
                default=defaults.get(CONF_SILENCE_THRESHOLD, SILENCE_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=5000,
                    step=50,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional(
                CONF_STREAM_FIRST_CHUNK_CHARS,
                default=defaults.get(
                    CONF_STREAM_FIRST_CHUNK_CHARS, STREAM_FIRST_CHUNK_CHARS
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=200,
                    step=5,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Optional(
                CONF_SPEECH_SPEED,
                default=defaults.get(CONF_SPEECH_SPEED, DEFAULT_SPEECH_SPEED),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_SPEECH_SPEED,
                    max=MAX_SPEECH_SPEED,
                    step=0.05,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
        }
    )


class LiquidAiTtsFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LiquidAI TTS."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            client = LiquidAiTtsClient(
                async_create_clientsession(self.hass),
                base_url,
            )
            try:
                await client.check_connection()
            except Exception as err:
                LOGGER.warning("LiquidAI connection check failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                self._data[CONF_BASE_URL] = base_url
                return await self.async_step_prompt()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_prompt(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Configure prompt and timeout."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_advanced()

        return self.async_show_form(
            step_id="prompt",
            data_schema=_prompt_schema(self._data),
        )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Configure advanced audio tuning options."""
        if user_input is not None:
            return self.async_create_entry(
                title="LiquidAI",
                data=self._data,
                options=user_input,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=_advanced_schema(),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LiquidAiTtsOptionsFlowHandler:
        """Return the options flow handler."""
        return LiquidAiTtsOptionsFlowHandler(config_entry)


class LiquidAiTtsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for LiquidAI TTS."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage advanced options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        defaults = {**self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_advanced_schema(defaults),
        )
