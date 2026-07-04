"""Unit tests for LiquidAI HTTP client."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "ha_liquidai_custom"
)


def _load_component_module(name: str):
    """Load a ha_liquidai_custom submodule without importing Home Assistant."""
    module_name = f"ha_liquidai_custom.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    if "ha_liquidai_custom" not in sys.modules:
        package = types.ModuleType("ha_liquidai_custom")
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules["ha_liquidai_custom"] = package

    if name == "client" and "homeassistant.exceptions" not in sys.modules:
        ha_pkg = types.ModuleType("homeassistant")
        ha_exc = types.ModuleType("homeassistant.exceptions")

        class HomeAssistantError(Exception):
            """Stub for tests."""

        ha_exc.HomeAssistantError = HomeAssistantError
        sys.modules["homeassistant"] = ha_pkg
        sys.modules["homeassistant.exceptions"] = ha_exc

    path = COMPONENT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_component_module("const")
client = _load_component_module("client")


@pytest.mark.asyncio
async def test_transcribe_returns_trimmed_text() -> None:
    """ASR JSON text is trimmed before return."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"text": "  hello world  "})

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.post = MagicMock(return_value=context)

    liquid_client = client.LiquidAiTtsClient(session, "http://example:8811")
    result = await liquid_client.transcribe(b"RIFF", mime_type="audio/wav")

    assert result == "hello world"
    session.post.assert_called_once()
    assert session.post.call_args.args[0] == "http://example:8811/v1/asr"


@pytest.mark.asyncio
async def test_transcribe_empty_audio_returns_empty_string() -> None:
    """Empty audio skips the HTTP request."""
    session = MagicMock()
    liquid_client = client.LiquidAiTtsClient(session, "http://example:8811")

    result = await liquid_client.transcribe(b"")

    assert result == ""
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_transcribe_raises_on_http_error() -> None:
    """Non-200 ASR responses raise HomeAssistantError."""
    response = AsyncMock()
    response.status = 500
    response.text = AsyncMock(return_value="server error")

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.post = MagicMock(return_value=context)

    liquid_client = client.LiquidAiTtsClient(session, "http://example:8811")

    with pytest.raises(client.HomeAssistantError, match="LiquidAI ASR failed"):
        await liquid_client.transcribe(b"RIFF")


@pytest.mark.asyncio
async def test_embed_speaker_parses_embedding_vector() -> None:
    """Speaker embed JSON returns a validated embedding payload."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "embedding": [0.01] * 192,
            "model": "sherpa-onnx-3dspeaker",
            "quality": "ok",
            "duration_ms": 1500,
        }
    )

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.post = MagicMock(return_value=context)

    liquid_client = client.LiquidAiTtsClient(session, "http://example:8811")
    result = await liquid_client.embed_speaker(b"RIFF", mime_type="audio/wav")

    assert len(result["embedding"]) == 192
    assert result["model"] == "sherpa-onnx-3dspeaker"
    session.post.assert_called_once()
    assert session.post.call_args.args[0] == "http://example:8811/v1/speaker/embed"


@pytest.mark.asyncio
async def test_embed_speaker_raises_on_empty_embedding() -> None:
    """Empty embedding vectors raise HomeAssistantError."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"embedding": []})

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.post = MagicMock(return_value=context)

    liquid_client = client.LiquidAiTtsClient(session, "http://example:8811")

    with pytest.raises(client.HomeAssistantError, match="empty embedding"):
        await liquid_client.embed_speaker(b"RIFF")


@pytest.mark.asyncio
async def test_embed_speaker_accepts_soft_quality_without_vector() -> None:
    """Soft quality responses degrade without raising."""
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "embedding": [],
            "model": "sherpa-onnx-3dspeaker",
            "quality": "too_short",
            "duration_ms": 400,
        }
    )

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.post = MagicMock(return_value=context)

    liquid_client = client.LiquidAiTtsClient(session, "http://example:8811")
    result = await liquid_client.embed_speaker(b"RIFF")

    assert result["quality"] == "too_short"
    assert result["embedding"] == []
