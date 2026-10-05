"""Unit tests for LiquidAI HTTP client."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from conftest import load_component_module

client = load_component_module("client")


def _response(status: int, *, json: Any = None, text: str = "") -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=json)
    response.text = AsyncMock(return_value=text)
    return response


def _context(response: AsyncMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _session(method: str, *responses: AsyncMock) -> MagicMock:
    session = MagicMock()
    setattr(
        session, method, MagicMock(side_effect=[_context(r) for r in responses])
    )
    return session


@pytest.mark.asyncio
async def test_transcribe_returns_trimmed_text() -> None:
    """ASR JSON text is trimmed before return."""
    session = _session("post", _response(200, json={"text": "  hello world  "}))

    liquid_client = client.LiquidAiClient(session, "http://example:8811")
    result = await liquid_client.transcribe(b"RIFF", mime_type="audio/wav")

    assert result == "hello world"
    session.post.assert_called_once()
    assert session.post.call_args.args[0] == "http://example:8811/v1/asr"


@pytest.mark.asyncio
async def test_transcribe_empty_audio_returns_empty_string() -> None:
    """Empty audio skips the HTTP request."""
    session = MagicMock()
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    result = await liquid_client.transcribe(b"")

    assert result == ""
    session.post.assert_not_called()


@pytest.mark.asyncio
async def test_transcribe_raises_typed_http_error() -> None:
    """Non-200 ASR responses raise LiquidAiHttpError carrying the status."""
    session = _session("post", _response(500, text="server error"))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    with pytest.raises(client.LiquidAiHttpError, match="LiquidAI ASR failed") as info:
        await liquid_client.transcribe(b"RIFF")

    assert info.value.status == 500
    assert info.value.operation == "ASR"
    assert isinstance(info.value, client.HomeAssistantError)


@pytest.mark.asyncio
async def test_synthesize_raises_typed_http_error() -> None:
    session = _session("post", _response(503, text="busy"))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    with pytest.raises(client.LiquidAiHttpError) as info:
        await liquid_client.synthesize("hello")

    assert info.value.status == 503


@pytest.mark.asyncio
async def test_embed_speaker_parses_embedding_vector() -> None:
    """Speaker embed JSON returns a validated embedding payload."""
    session = _session(
        "post",
        _response(
            200,
            json={
                "embedding": [0.01] * 192,
                "model": "sherpa-onnx-3dspeaker",
                "quality": "ok",
                "duration_ms": 1500,
            },
        ),
    )

    liquid_client = client.LiquidAiClient(session, "http://example:8811")
    result = await liquid_client.embed_speaker(b"RIFF", mime_type="audio/wav")

    assert len(result["embedding"]) == 192
    assert result["model"] == "sherpa-onnx-3dspeaker"
    assert session.post.call_args.args[0] == "http://example:8811/v1/speaker/embed"


@pytest.mark.asyncio
async def test_embed_speaker_raises_on_empty_embedding() -> None:
    """Empty embedding vectors raise HomeAssistantError."""
    session = _session("post", _response(200, json={"embedding": []}))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    with pytest.raises(client.HomeAssistantError, match="empty embedding"):
        await liquid_client.embed_speaker(b"RIFF")


@pytest.mark.asyncio
async def test_embed_speaker_accepts_soft_quality_without_vector() -> None:
    """Soft quality responses degrade without raising."""
    session = _session(
        "post",
        _response(
            200,
            json={
                "embedding": [],
                "model": "sherpa-onnx-3dspeaker",
                "quality": "too_short",
                "duration_ms": 400,
            },
        ),
    )
    liquid_client = client.LiquidAiClient(session, "http://example:8811")
    result = await liquid_client.embed_speaker(b"RIFF")

    assert result["quality"] == "too_short"
    assert result["embedding"] == []


@pytest.mark.asyncio
async def test_embed_speaker_404_is_typed() -> None:
    session = _session("post", _response(404, text="not found"))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    with pytest.raises(client.LiquidAiHttpError) as info:
        await liquid_client.embed_speaker(b"RIFF")

    assert info.value.status == 404


@pytest.mark.asyncio
async def test_check_connection_uses_healthz_ready() -> None:
    """A ready server answers 200 on /healthz?ready=1 and returns its payload."""
    session = _session("get", _response(200, json={"audio_ready": True}))
    liquid_client = client.LiquidAiClient(session, "http://example:8811/")

    payload = await liquid_client.check_connection()

    assert payload == {"audio_ready": True}
    session.get.assert_called_once()
    assert session.get.call_args.args[0] == "http://example:8811/healthz"
    assert session.get.call_args.kwargs["params"] == {"ready": "1"}


@pytest.mark.asyncio
async def test_check_connection_reports_not_ready_on_503() -> None:
    session = _session("get", _response(503, text="loading"))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    with pytest.raises(client.LiquidAiNotReadyError):
        await liquid_client.check_connection()


@pytest.mark.asyncio
async def test_check_connection_falls_back_when_healthz_missing() -> None:
    """Servers without /healthz still pass when the base URL answers < 500."""
    session = _session("get", _response(404), _response(200))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    assert await liquid_client.check_connection() == {}
    assert session.get.call_count == 2
    assert session.get.call_args_list[1].args[0] == "http://example:8811"


@pytest.mark.asyncio
async def test_check_connection_fallback_rejects_server_error() -> None:
    session = _session("get", _response(404), _response(502, text="bad gateway"))
    liquid_client = client.LiquidAiClient(session, "http://example:8811")

    with pytest.raises(client.LiquidAiHttpError) as info:
        await liquid_client.check_connection()

    assert info.value.status == 502
