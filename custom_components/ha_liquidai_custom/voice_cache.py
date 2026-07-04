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
DEFAULT_SATELLITE_KEY = "__default__"


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
    satellite_id: str | None = None


def normalize_voice_text(text: str) -> str:
    """Normalize transcript text for cache matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def make_voice_match_key(text: str, *, satellite_id: str | None = None) -> str:
    """Build a stable cache key from normalized transcript text."""
    normalized = normalize_voice_text(text)
    scope = satellite_id or DEFAULT_SATELLITE_KEY
    digest = hashlib.sha256(f"{scope}:{normalized}".encode()).hexdigest()
    return digest[:16]


def build_voice_turn_payload(
    text: str,
    embed_result: dict[str, Any] | None,
    *,
    satellite_id: str | None = None,
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
            match_key=make_voice_match_key(text, satellite_id=satellite_id),
            satellite_id=satellite_id,
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
        match_key=make_voice_match_key(text, satellite_id=satellite_id),
        satellite_id=satellite_id,
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
        "Stored voice turn match_key=%s satellite=%s quality=%s",
        payload.match_key,
        payload.satellite_id,
        payload.quality,
    )


def _payload_matches_text(payload: VoiceTurnPayload, normalized: str) -> bool:
    return normalize_voice_text(payload.text) == normalized


def _payload_matches_satellite(
    payload: VoiceTurnPayload,
    satellite_id: str | None,
) -> bool:
    if satellite_id:
        return payload.satellite_id in {satellite_id, None}
    return True


def pop_voice_turn(
    hass: HomeAssistant,
    *,
    text: str,
    match_key: str | None = None,
    satellite_id: str | None = None,
) -> VoiceTurnPayload | None:
    """Pop a cache entry by normalized text and optional match key."""
    now = time.monotonic()
    prune_voice_turns(hass, now=now)
    normalized = normalize_voice_text(text)
    key = match_key or make_voice_match_key(text, satellite_id=satellite_id)
    store = _voice_turn_store(hass)

    for index in range(len(store) - 1, -1, -1):
        payload = store[index]
        if payload.match_key != key:
            continue
        if not _payload_matches_text(payload, normalized):
            continue
        if satellite_id and payload.satellite_id not in {satellite_id, None}:
            continue
        store.pop(index)
        return payload

    return None


def pop_matching_voice_turn(
    hass: HomeAssistant,
    *,
    user_text: str,
    satellite_id: str | None = None,
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
    best_is_exact_satellite = False

    for index, payload in enumerate(store):
        if not _payload_matches_text(payload, normalized):
            continue
        age = now - payload.created_at
        if age > VOICE_TURN_MATCH_WINDOW_SECONDS:
            continue
        exact_satellite = bool(
            satellite_id and payload.satellite_id == satellite_id
        )
        if not _payload_matches_satellite(payload, satellite_id):
            continue
        if payload.created_at > best_created_at or (
            payload.created_at == best_created_at and exact_satellite
        ):
            if exact_satellite or not best_is_exact_satellite:
                best_created_at = payload.created_at
                best_index = index
                best_is_exact_satellite = exact_satellite

    if best_index is None:
        return None

    return store.pop(best_index)
