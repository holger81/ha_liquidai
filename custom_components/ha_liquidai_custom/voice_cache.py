"""Voice turn cache bridging STT speaker embeddings to ha_agent."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    LOGGER,
    VOICE_TURN_MATCH_WINDOW_SECONDS,
    VOICE_TURN_TTL_SECONDS,
)

DATA_VOICE_TURNS = "ha_liquidai_voice_turns"


@dataclass(frozen=True)
class VoiceTurnPayload:
    """Speaker embedding payload for one Assist utterance."""

    text: str
    embedding: list[float] | None
    model: str | None
    quality: str
    duration_ms: int | None
    created_at: float
    match_key: str


def normalize_voice_text(text: str) -> str:
    """Normalize transcript text for cache matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def make_voice_match_key(text: str) -> str:
    """Build a stable cache key from normalized transcript text."""
    digest = hashlib.sha256(normalize_voice_text(text).encode()).hexdigest()
    return digest[:16]


def build_voice_turn_payload(
    text: str,
    embed_result: dict[str, Any] | None,
) -> VoiceTurnPayload:
    """Build a cache payload from ASR text and optional embed response."""
    if embed_result is None:
        return VoiceTurnPayload(
            text=text,
            embedding=None,
            model=None,
            quality="skipped",
            duration_ms=None,
            created_at=time.monotonic(),
            match_key=make_voice_match_key(text),
        )

    embedding_raw = embed_result.get("embedding")
    embedding: list[float] | None
    if isinstance(embedding_raw, list) and embedding_raw:
        embedding = [float(value) for value in embedding_raw]
    else:
        embedding = None

    duration_ms = embed_result.get("duration_ms")
    return VoiceTurnPayload(
        text=text,
        embedding=embedding,
        model=str(embed_result.get("model") or "") or None,
        quality=str(embed_result.get("quality") or "ok"),
        duration_ms=int(duration_ms) if duration_ms is not None else None,
        created_at=time.monotonic(),
        match_key=make_voice_match_key(text),
    )


def _voice_turn_store(hass: HomeAssistant) -> list[VoiceTurnPayload]:
    if DATA_VOICE_TURNS not in hass.data:
        hass.data[DATA_VOICE_TURNS] = []
    return hass.data[DATA_VOICE_TURNS]


def prune_voice_turns(hass: HomeAssistant, *, now: float | None = None) -> None:
    """Drop expired voice turn cache entries."""
    current = now if now is not None else time.monotonic()
    store = _voice_turn_store(hass)
    hass.data[DATA_VOICE_TURNS] = [
        payload
        for payload in store
        if current - payload.created_at <= VOICE_TURN_TTL_SECONDS
    ]


def store_voice_turn(hass: HomeAssistant, payload: VoiceTurnPayload) -> None:
    """Store one voice turn payload for ha_agent to consume."""
    prune_voice_turns(hass, now=payload.created_at)
    _voice_turn_store(hass).append(payload)
    LOGGER.debug(
        "Stored voice turn match_key=%s quality=%s",
        payload.match_key,
        payload.quality,
    )


def pop_voice_turn(
    hass: HomeAssistant,
    *,
    text: str,
    match_key: str | None = None,
) -> VoiceTurnPayload | None:
    """Pop a cache entry by normalized text and optional match key."""
    now = time.monotonic()
    prune_voice_turns(hass, now=now)
    normalized = normalize_voice_text(text)
    key = match_key or make_voice_match_key(text)
    store = _voice_turn_store(hass)

    for index in range(len(store) - 1, -1, -1):
        payload = store[index]
        if payload.match_key != key:
            continue
        if normalize_voice_text(payload.text) != normalized:
            continue
        store.pop(index)
        return payload

    return None


def pop_matching_voice_turn(
    hass: HomeAssistant,
    *,
    user_text: str,
) -> VoiceTurnPayload | None:
    """Return the most recent matching voice turn within the match window."""
    now = time.monotonic()
    prune_voice_turns(hass, now=now)
    normalized = normalize_voice_text(user_text)
    if not normalized:
        return None

    store = _voice_turn_store(hass)
    best_index: int | None = None
    best_created_at = -1.0

    for index, payload in enumerate(store):
        if normalize_voice_text(payload.text) != normalized:
            continue
        age = now - payload.created_at
        if age > VOICE_TURN_MATCH_WINDOW_SECONDS:
            continue
        if payload.created_at > best_created_at:
            best_created_at = payload.created_at
            best_index = index

    if best_index is None:
        return None

    return store.pop(best_index)
