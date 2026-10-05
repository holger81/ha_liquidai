"""Shared test scaffolding: Home Assistant stubs and component loader.

The integration is tested without a Home Assistant install. Every
``homeassistant.*`` module the component imports is replaced with a small
stand-in below; the component package itself is loaded straight from
``custom_components/ha_liquidai_custom`` (its ``__init__`` is not executed).
"""

from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "ha_liquidai_custom"
)
PACKAGE = "ha_liquidai_custom"


def _module(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class HomeAssistantError(Exception):
    """Stub for homeassistant.exceptions.HomeAssistantError."""


class HomeAssistant:
    """Stub for homeassistant.core.HomeAssistant (type annotations only)."""


class ConfigEntry:
    """Minimal ConfigEntry stand-in."""

    def __init__(
        self,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        entry_id: str = "entry-1",
        unique_id: str | None = None,
        version: int = 1,
    ) -> None:
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.entry_id = entry_id
        self.unique_id = unique_id
        self.version = version


class ConfigFlowResult(dict):
    """Flow results are plain dicts in the stub."""


class _FlowBase:
    hass: Any = None

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: Any = None,
        errors: dict[str, str] | None = None,
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        return ConfigFlowResult(
            type="form",
            step_id=step_id,
            data_schema=data_schema,
            errors=errors or {},
        )

    def async_create_entry(
        self,
        *,
        title: str,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        return ConfigFlowResult(
            type="create_entry", title=title, data=data, options=options or {}
        )

    def async_abort(self, *, reason: str) -> ConfigFlowResult:
        return ConfigFlowResult(type="abort", reason=reason)


class ConfigFlow(_FlowBase):
    """Stub ConfigFlow supporting the subset the component uses."""

    unique_id: str | None = None
    _reconfigure_entry: ConfigEntry | None = None
    _entries: ClassVar[list[ConfigEntry]] = []
    _configured_unique_ids: ClassVar[set[str]] = set()

    def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    async def async_set_unique_id(self, unique_id: str) -> None:
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        if self.unique_id in self._configured_unique_ids:
            raise AbortFlow("already_configured")

    def _get_reconfigure_entry(self) -> ConfigEntry:
        assert self._reconfigure_entry is not None
        return self._reconfigure_entry

    def _async_current_entries(self) -> list[ConfigEntry]:
        return list(self._entries)

    def async_update_reload_and_abort(
        self,
        entry: ConfigEntry,
        *,
        unique_id: str | None = None,
        data_updates: dict[str, Any] | None = None,
        reason: str = "reconfigure_successful",
    ) -> ConfigFlowResult:
        if data_updates:
            entry.data = {**entry.data, **data_updates}
        if unique_id is not None:
            entry.unique_id = unique_id
        return ConfigFlowResult(type="abort", reason=reason)


class AbortFlow(Exception):
    """Stub for data_entry_flow.AbortFlow."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OptionsFlow(_FlowBase):
    """Stub OptionsFlow exposing config_entry like HA >= 2024.12."""

    config_entry: ConfigEntry


class _Selector:
    """Selector stub: accepts any config, validates by passthrough."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.config = args[0] if args else kwargs

    def __call__(self, value: Any) -> Any:
        return value


class _SelectorConfig(dict):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(kwargs)


class TextToSpeechEntity:
    """Stub TTS entity base."""

    hass: Any = None


@dataclass
class TTSAudioRequest:
    """Stub streaming TTS request."""

    message_gen: Any
    language: str = "en-US"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSAudioResponse:
    """Stub streaming TTS response."""

    extension: str
    data_gen: Any


class _Enum:
    def __init__(self, value: Any) -> None:
        self.value = value


class SpeechToTextEntity:
    """Stub STT entity base."""


class SpeechResult:
    def __init__(self, text: str | None, state: str) -> None:
        self.text = text
        self.state = state


class SpeechResultState:
    SUCCESS = "success"
    ERROR = "error"


class AudioFormats:
    WAV = _Enum("wav")
    OGG = _Enum("ogg")


class AudioCodecs:
    PCM = _Enum("pcm")
    OPUS = _Enum("opus")


class AudioBitRates:
    BITRATE_16 = _Enum(16)


class AudioSampleRates:
    RATE_16000 = _Enum(16000)

    def __iter__(self):
        yield self.RATE_16000


class AudioChannels:
    CHANNEL_MONO = _Enum(1)
    CHANNEL_STEREO = _Enum(2)


class SpeechMetadata:
    pass


def _redact(data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {k: ("**REDACTED**" if k in keys else v) for k, v in data.items()}


def install_ha_stubs() -> None:
    """Install stand-ins for every homeassistant module the component imports."""
    if "homeassistant" in sys.modules:
        return

    _module("homeassistant")
    _module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    _module(
        "homeassistant.core",
        HomeAssistant=HomeAssistant,
        callback=lambda func: func,
    )
    _module(
        "homeassistant.config_entries",
        ConfigEntry=ConfigEntry,
        ConfigFlow=ConfigFlow,
        ConfigFlowResult=ConfigFlowResult,
        OptionsFlow=OptionsFlow,
    )
    _module("homeassistant.data_entry_flow", AbortFlow=AbortFlow)
    _module("homeassistant.const", Platform=SimpleNamespace(STT="stt", TTS="tts"))
    _module("homeassistant.helpers")
    _module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _module(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda _hass: None,
        async_create_clientsession=lambda _hass: None,
    )
    _module(
        "homeassistant.helpers.selector",
        TextSelector=_Selector,
        TextSelectorConfig=_SelectorConfig,
        TextSelectorType=SimpleNamespace(TEXT="text", URL="url"),
        NumberSelector=_Selector,
        NumberSelectorConfig=_SelectorConfig,
        NumberSelectorMode=SimpleNamespace(BOX="box"),
        BooleanSelector=_Selector,
    )
    _module("homeassistant.components")
    _module(
        "homeassistant.components.ffmpeg",
        get_ffmpeg_manager=lambda _hass: SimpleNamespace(binary="ffmpeg"),
    )
    _module("homeassistant.components.diagnostics", async_redact_data=_redact)
    _module(
        "homeassistant.components.tts",
        TextToSpeechEntity=TextToSpeechEntity,
        TTSAudioRequest=TTSAudioRequest,
        TTSAudioResponse=TTSAudioResponse,
        TtsAudioType=tuple,
    )
    _module(
        "homeassistant.components.stt",
        SpeechToTextEntity=SpeechToTextEntity,
        SpeechResult=SpeechResult,
        SpeechResultState=SpeechResultState,
        AudioFormats=AudioFormats,
        AudioCodecs=AudioCodecs,
        AudioBitRates=AudioBitRates,
        AudioSampleRates=AudioSampleRates,
        AudioChannels=AudioChannels,
        SpeechMetadata=SpeechMetadata,
    )

    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
    sys.modules[PACKAGE] = package


def load_component_module(name: str) -> types.ModuleType:
    """Import ``ha_liquidai_custom.<name>`` against the stubbed HA modules."""
    install_ha_stubs()
    return importlib.import_module(f"{PACKAGE}.{name}")


install_ha_stubs()


def make_hass() -> MagicMock:
    """Return a hass stand-in with a dict data store and inline executor."""
    hass = MagicMock()
    hass.data = {}

    async def run_in_executor(func, *args):
        return func(*args)

    hass.async_add_executor_job = run_in_executor
    return hass


@pytest.fixture
def hass() -> MagicMock:
    """Provide a fake hass per test."""
    return make_hass()
