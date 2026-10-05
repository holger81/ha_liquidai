"""Config flow for LiquidAI."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .client import LiquidAiClient, LiquidAiNotReadyError
from .const import (
    CHUNK_GAP_MS,
    CONF_ASR_SYSTEM_PROMPT,
    CONF_BASE_URL,
    CONF_CHUNK_GAP_MS,
    CONF_KEEP_EDGE_MS,
    CONF_MAX_CHUNK_LEN,
    CONF_SILENCE_THRESHOLD,
    CONF_SPEAKER_EMBED_ENABLED,
    CONF_SPEAKER_EMBED_GRACE,
    CONF_SPEECH_SPEED,
    CONF_STREAM_FIRST_CHUNK_CHARS,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_ASR_SYSTEM_PROMPT,
    DEFAULT_SPEAKER_EMBED_ENABLED,
    DEFAULT_SPEECH_SPEED,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DOMAIN,
    KEEP_EDGE_MS,
    LOGGER,
    MAX_CHUNK_LEN,
    MAX_SPEAKER_EMBED_GRACE,
    MAX_SPEECH_SPEED,
    MIN_SPEAKER_EMBED_GRACE,
    MIN_SPEECH_SPEED,
    SILENCE_THRESHOLD,
    SPEAKER_EMBED_GRACE_SECONDS,
    STREAM_FIRST_CHUNK_CHARS,
)

# Keys stored in entry.data (connection + model prompts).
CONNECTION_KEYS = (
    CONF_BASE_URL,
    CONF_SYSTEM_PROMPT,
    CONF_ASR_SYSTEM_PROMPT,
    CONF_TIMEOUT,
)


def _number(
    minimum: float, maximum: float, step: float
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
        ),
    )


def _multiline_text() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(
            type=selector.TextSelectorType.TEXT,
            multiline=True,
        ),
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
            ): _multiline_text(),
            vol.Required(
                CONF_ASR_SYSTEM_PROMPT,
                default=defaults.get(CONF_ASR_SYSTEM_PROMPT, DEFAULT_ASR_SYSTEM_PROMPT),
            ): _multiline_text(),
            vol.Optional(
                CONF_TIMEOUT,
                default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            ): _number(10, 600, 1),
        }
    )


def _reconfigure_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Combine connection and prompt settings into one reconfigure form."""
    return _user_schema(defaults).extend(_prompt_schema(defaults).schema)


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_SPEAKER_EMBED_ENABLED,
                default=defaults.get(
                    CONF_SPEAKER_EMBED_ENABLED, DEFAULT_SPEAKER_EMBED_ENABLED
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_SPEAKER_EMBED_GRACE,
                default=defaults.get(
                    CONF_SPEAKER_EMBED_GRACE, SPEAKER_EMBED_GRACE_SECONDS
                ),
            ): _number(MIN_SPEAKER_EMBED_GRACE, MAX_SPEAKER_EMBED_GRACE, 0.5),
            vol.Optional(
                CONF_MAX_CHUNK_LEN,
                default=defaults.get(CONF_MAX_CHUNK_LEN, MAX_CHUNK_LEN),
            ): _number(40, 500, 10),
            vol.Optional(
                CONF_KEEP_EDGE_MS,
                default=defaults.get(CONF_KEEP_EDGE_MS, KEEP_EDGE_MS),
            ): _number(0, 500, 10),
            vol.Optional(
                CONF_CHUNK_GAP_MS,
                default=defaults.get(CONF_CHUNK_GAP_MS, CHUNK_GAP_MS),
            ): _number(0, 100, 1),
            vol.Optional(
                CONF_SILENCE_THRESHOLD,
                default=defaults.get(CONF_SILENCE_THRESHOLD, SILENCE_THRESHOLD),
            ): _number(0, 5000, 50),
            vol.Optional(
                CONF_STREAM_FIRST_CHUNK_CHARS,
                default=defaults.get(
                    CONF_STREAM_FIRST_CHUNK_CHARS, STREAM_FIRST_CHUNK_CHARS
                ),
            ): _number(0, 200, 5),
            vol.Optional(
                CONF_SPEECH_SPEED,
                default=defaults.get(CONF_SPEECH_SPEED, DEFAULT_SPEECH_SPEED),
            ): _number(MIN_SPEECH_SPEED, MAX_SPEECH_SPEED, 0.05),
        }
    )


class LiquidAiFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LiquidAI."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}

    async def _async_check_connection(self, base_url: str) -> str | None:
        """Return an error key when the server cannot be reached, else None."""
        client = LiquidAiClient(async_create_clientsession(self.hass), base_url)
        try:
            await client.check_connection()
        except LiquidAiNotReadyError as err:
            LOGGER.warning("LiquidAI server not ready: %s", err)
            return "not_ready"
        except Exception as err:
            LOGGER.warning("LiquidAI connection check failed: %s", err)
            return "cannot_connect"
        return None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            error = await self._async_check_connection(base_url)
            if error:
                errors["base"] = error
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
    ) -> ConfigFlowResult:
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
    ) -> ConfigFlowResult:
        """Configure speaker embedding and audio tuning options."""
        if user_input is not None:
            return self.async_create_entry(
                title="LiquidAI",
                data=self._data,
                options=user_input,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=_options_schema(),
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Change server URL, prompts or timeout of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            error = await self._async_check_connection(base_url)
            if error:
                errors["base"] = error
            elif self._url_used_by_other_entry(entry, base_url):
                return self.async_abort(reason="already_configured")
            else:
                data_updates = {
                    key: user_input[key] for key in CONNECTION_KEYS if key in user_input
                }
                data_updates[CONF_BASE_URL] = base_url
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=base_url,
                    data_updates=data_updates,
                )

        defaults = {**entry.data, **(user_input or {})}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_schema(defaults),
            errors=errors,
        )

    def _url_used_by_other_entry(self, entry: ConfigEntry, base_url: str) -> bool:
        """Return True when another entry already points at base_url."""
        return any(
            other.entry_id != entry.entry_id and other.unique_id == base_url
            for other in self._async_current_entries()
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> LiquidAiOptionsFlowHandler:
        """Return the options flow handler."""
        return LiquidAiOptionsFlowHandler()


class LiquidAiOptionsFlowHandler(OptionsFlow):
    """Handle options for LiquidAI."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage speaker embedding and audio options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Older entries stored speaker_embed_enabled in data; pre-fill from it.
        defaults = {
            CONF_SPEAKER_EMBED_ENABLED: self.config_entry.data.get(
                CONF_SPEAKER_EMBED_ENABLED, DEFAULT_SPEAKER_EMBED_ENABLED
            ),
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults),
        )
