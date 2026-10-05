"""Unit tests for the config, reconfigure and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from conftest import ConfigEntry, load_component_module

client = load_component_module("client")
const = load_component_module("const")
config_flow = load_component_module("config_flow")


def _flow(**attrs) -> config_flow.LiquidAiFlowHandler:
    flow = config_flow.LiquidAiFlowHandler()
    flow.hass = object()
    for key, value in attrs.items():
        setattr(flow, key, value)
    return flow


def _patch_connection(side_effect=None):
    return patch.object(
        client.LiquidAiClient,
        "check_connection",
        AsyncMock(side_effect=side_effect, return_value={}),
    )


def test_options_schema_defaults_include_speaker_embed() -> None:
    validated = config_flow._options_schema()({})
    assert validated[const.CONF_SPEAKER_EMBED_ENABLED] is True
    assert (
        validated[const.CONF_SPEAKER_EMBED_GRACE] == const.SPEAKER_EMBED_GRACE_SECONDS
    )
    assert validated[const.CONF_MAX_CHUNK_LEN] == const.MAX_CHUNK_LEN
    assert validated[const.CONF_SPEECH_SPEED] == const.DEFAULT_SPEECH_SPEED


def test_prompt_schema_no_longer_carries_speaker_embed_fields() -> None:
    validated = config_flow._prompt_schema()({})
    assert const.CONF_SPEAKER_EMBED_ENABLED not in validated
    assert const.CONF_SPEAKER_EMBED_TIMEOUT not in validated
    assert validated[const.CONF_TIMEOUT] == const.DEFAULT_TIMEOUT


def test_reconfigure_schema_combines_url_and_prompts() -> None:
    validated = config_flow._reconfigure_schema({const.CONF_BASE_URL: "http://a"})({})
    assert validated[const.CONF_BASE_URL] == "http://a"
    assert validated[const.CONF_SYSTEM_PROMPT] == const.DEFAULT_SYSTEM_PROMPT
    assert validated[const.CONF_ASR_SYSTEM_PROMPT] == const.DEFAULT_ASR_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_user_step_happy_path_creates_entry() -> None:
    flow = _flow()
    with _patch_connection():
        result = await flow.async_step_user({const.CONF_BASE_URL: "http://x:8811/"})
    assert result["type"] == "form"
    assert result["step_id"] == "prompt"
    assert flow.unique_id == "http://x:8811"

    result = await flow.async_step_prompt(
        {const.CONF_SYSTEM_PROMPT: "tts", const.CONF_ASR_SYSTEM_PROMPT: "asr"}
    )
    assert result["step_id"] == "advanced"

    result = await flow.async_step_advanced({const.CONF_SPEAKER_EMBED_ENABLED: False})
    assert result["type"] == "create_entry"
    assert result["data"][const.CONF_BASE_URL] == "http://x:8811"
    assert result["data"][const.CONF_SYSTEM_PROMPT] == "tts"
    assert result["options"] == {const.CONF_SPEAKER_EMBED_ENABLED: False}


@pytest.mark.asyncio
async def test_user_step_cannot_connect() -> None:
    flow = _flow()
    with _patch_connection(side_effect=client.HomeAssistantError("nope")):
        result = await flow.async_step_user({const.CONF_BASE_URL: "http://x"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_user_step_not_ready_has_dedicated_error() -> None:
    flow = _flow()
    with _patch_connection(side_effect=client.LiquidAiNotReadyError("loading")):
        result = await flow.async_step_user({const.CONF_BASE_URL: "http://x"})
    assert result["errors"] == {"base": "not_ready"}


@pytest.mark.asyncio
async def test_reconfigure_updates_data_and_unique_id() -> None:
    entry = ConfigEntry(
        data={
            const.CONF_BASE_URL: "http://old:8811",
            const.CONF_SYSTEM_PROMPT: "old tts",
        },
        unique_id="http://old:8811",
    )
    flow = _flow(_reconfigure_entry=entry, _entries=[entry])

    result = await flow.async_step_reconfigure()
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    with _patch_connection():
        result = await flow.async_step_reconfigure(
            {
                const.CONF_BASE_URL: "http://new:8811/",
                const.CONF_SYSTEM_PROMPT: "new tts",
                const.CONF_ASR_SYSTEM_PROMPT: "asr",
                const.CONF_TIMEOUT: 60,
            }
        )

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    assert entry.data[const.CONF_BASE_URL] == "http://new:8811"
    assert entry.data[const.CONF_SYSTEM_PROMPT] == "new tts"
    assert entry.data[const.CONF_TIMEOUT] == 60
    assert entry.unique_id == "http://new:8811"


@pytest.mark.asyncio
async def test_reconfigure_rejects_url_of_another_entry() -> None:
    entry = ConfigEntry(
        data={const.CONF_BASE_URL: "http://a"}, unique_id="http://a", entry_id="a"
    )
    other = ConfigEntry(
        data={const.CONF_BASE_URL: "http://b"}, unique_id="http://b", entry_id="b"
    )
    flow = _flow(_reconfigure_entry=entry, _entries=[entry, other])

    with _patch_connection():
        result = await flow.async_step_reconfigure(
            {
                const.CONF_BASE_URL: "http://b",
                const.CONF_SYSTEM_PROMPT: "x",
                const.CONF_ASR_SYSTEM_PROMPT: "y",
            }
        )

    assert result == {"type": "abort", "reason": "already_configured"}
    assert entry.data[const.CONF_BASE_URL] == "http://a"


@pytest.mark.asyncio
async def test_reconfigure_connection_error_shows_form_again() -> None:
    entry = ConfigEntry(data={const.CONF_BASE_URL: "http://a"}, unique_id="http://a")
    flow = _flow(_reconfigure_entry=entry, _entries=[entry])

    with _patch_connection(side_effect=client.HomeAssistantError("down")):
        result = await flow.async_step_reconfigure(
            {
                const.CONF_BASE_URL: "http://a",
                const.CONF_SYSTEM_PROMPT: "x",
                const.CONF_ASR_SYSTEM_PROMPT: "y",
            }
        )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_options_flow_prefills_legacy_speaker_embed_from_data() -> None:
    entry = ConfigEntry(
        data={const.CONF_BASE_URL: "http://a", const.CONF_SPEAKER_EMBED_ENABLED: False},
        options={const.CONF_SPEECH_SPEED: 1.1},
    )
    handler = config_flow.LiquidAiFlowHandler.async_get_options_flow(entry)
    handler.config_entry = entry

    result = await handler.async_step_init()
    assert result["type"] == "form"
    defaults = result["data_schema"]({})
    assert defaults[const.CONF_SPEAKER_EMBED_ENABLED] is False
    assert defaults[const.CONF_SPEECH_SPEED] == 1.1

    result = await handler.async_step_init({const.CONF_SPEAKER_EMBED_ENABLED: True})
    assert result["type"] == "create_entry"
    assert result["data"] == {const.CONF_SPEAKER_EMBED_ENABLED: True}
