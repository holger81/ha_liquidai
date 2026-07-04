# LiquidAI audio — speaker embedding bridge (Phase 4)

**Transferable implementation plan** for ha_liquidai + inference box changes that
support [ha_agent Phase 9b voice identity](https://github.com/holger81/ha_agent/blob/main/docs/agent-voice-inference-plan.md).

This doc is self-contained: an agent or developer can implement from here without
reading the full ha_agent design history.

## Repository map (local)

| Part | Repo | Path |
|------|------|------|
| **A** — `/v1/speaker/embed` | [liquidai-audio-docker](https://github.com/holger81/liquidai-audio-docker) | `~/MeineDateien/Projekte/liquidai-audio` |
| **B–D** — client, STT, cache | [ha_liquidai](https://github.com/holger81/ha_liquidai) | `~/Projects/ha_liquidai` |
| **E** — clustering + conversation | [ha_agent](https://github.com/holger81/ha_agent) | `~/Projects/ha_agent` |

**Status (2026-07):** Part A **shipped** (API + tests in liquidai-audio). Parts B–D and E **pending**.

---

## Purpose

Home Assistant Assist STT returns **text only** to the conversation stage. ha_agent
needs a **speaker embedding** from the same utterance to assign a stable guest/user id.

ha_liquidai already holds the raw audio in `stt.py` before calling `/v1/asr`. This
plan adds:

1. A **speaker embed HTTP API** on the inference box (Sherpa-ONNX)
2. A **parallel embed call** from ha_liquidai STT
3. A **voice turn cache** on HA that ha_agent reads on the next conversation turn

---

## Target flow

```text
Assist pipeline (one utterance)
  │
  ├─ ha_liquidai STT
  │    ├─ collect audio → WAV (existing)
  │    ├─ parallel HTTP:
  │    │    POST /v1/asr            → text
  │    │    POST /v1/speaker/embed  → embedding[192]
  │    └─ write voice_turn_cache entry (TTL ~5s)
  │
  ├─ ha_agent conversation
  │    ├─ pop cache entry (match by text + recency / satellite)
  │    ├─ cluster embedding → agent_user_id (ha_agent)
  │    └─ run_agent(...)
  │
  └─ ha_liquidai TTS (unchanged)
```

---

## Part A — Inference box API ✅ (shipped)

**Repo:** `~/MeineDateien/Projekte/liquidai-audio` — `lfm2audio/speaker_embed.py`, `routes.py`, `docker-compose.yaml`  
**Host:** `192.168.10.31` (default LiquidAI base `http://192.168.10.31:8811`)

### New endpoint: `POST /v1/speaker/embed`

**Request** (multipart, same audio shape as ASR):

```http
POST /v1/speaker/embed HTTP/1.1
Content-Type: multipart/form-data

type=audio/wav
audio=<wav bytes>
```

**Response** (200):

```json
{
  "embedding": [0.012, -0.034, "... 192 floats total"],
  "model": "sherpa-onnx-3dspeaker",
  "duration_ms": 1840,
  "quality": "ok"
}
```

**Quality values:**

| Value | Meaning | ha_liquidai action |
|-------|---------|-------------------|
| `ok` | Usable utterance | Cache embedding |
| `too_short` | Below min duration (~800 ms) | Cache with flag; ha_agent uses guest fallback |
| `noisy` | Low SNR / unreliable | Cache with flag; lower confidence |
| `error` | Model failure | Skip embed; STT text still returned |

**Errors:** 4xx/5xx — log warning; STT succeeds with text only (identity degrades to Assist guest).

### Implementation notes (inference server)

- Use [Sherpa-ONNX](https://github.com/k2-fsa/sherpa-onnx) `SpeakerEmbeddingExtractor` with a prebuilt [speaker ID ONNX model](https://github.com/k2-fsa/sherpa-onnx#speaker-identification-speaker-id).
- **Stateless** — no enrolled gallery on the server.
- Model path e.g. `/models/speaker/` on the inference box.
- Target latency: **< 100 ms** CPU per utterance after WAV is available.

**Deployment:**

| Option | When |
|--------|------|
| Add route to existing LiquidAI server on `:8811` | Default |
| Separate container on `:8812` | If ASR latency regresses under load |

### Optional later: combined endpoint

```http
POST /v1/assist/transcribe
→ { "text": "...", "speaker": { "embedding": [...], "model": "...", "quality": "ok" } }
```

Same semantics; one round trip. Not required for MVP.

---

## Part B — ha_liquidai client (pending)

**Repo:** `~/Projects/ha_liquidai`  
**File:** `custom_components/ha_liquidai_custom/client.py`

Add method:

```python
async def embed_speaker(
    self,
    audio_bytes: bytes,
    *,
    mime_type: str = "audio/wav",
) -> dict[str, Any]:
    """Return speaker embedding payload from /v1/speaker/embed."""
```

- POST to `{base_url}/v1/speaker/embed`
- Parse JSON; validate `embedding` is a non-empty list of floats
- Raise `HomeAssistantError` on hard failures (caller decides whether to degrade)

**Config** (optional feature flag in config entry):

| Key | Default | Purpose |
|-----|---------|---------|
| `speaker_embed_enabled` | `true` | Skip embed call when false |
| `speaker_embed_timeout` | same as ASR timeout | Separate timeout if needed |

---

## Part C — ha_liquidai STT (pending)

**Repo:** `~/Projects/ha_liquidai`  
**File:** `custom_components/ha_liquidai_custom/stt.py`

After `_prepare_wav_for_asr()`:

```python
async def _transcribe_and_embed(self, wav_bytes: bytes) -> tuple[str, dict | None]:
    if not self._speaker_embed_enabled:
        text = await self._client.transcribe(...)
        return text, None

    asr_task = asyncio.create_task(self._client.transcribe(...))
    embed_task = asyncio.create_task(self._client.embed_speaker(wav_bytes))
    results = await asyncio.gather(asr_task, embed_task, return_exceptions=True)
    # handle exceptions: ASR failure → ERROR; embed failure → log + None
```

After success, call voice cache store (Part D).

---

## Part D — Voice turn cache (HA side channel, pending)

**Repo:** `~/Projects/ha_liquidai`  
**New module:** `custom_components/ha_liquidai_custom/voice_cache.py`

Because HA STT cannot attach metadata to `SpeechResult`, store embeddings in
`hass.data`:

```python
DATA_VOICE_TURNS = "ha_liquidai_voice_turns"

@dataclass
class VoiceTurnPayload:
    text: str
    embedding: list[float] | None
    model: str | None
    quality: str
    duration_ms: int | None
    created_at: float
    match_key: str  # see below

def store_voice_turn(hass, payload: VoiceTurnPayload) -> None: ...
def pop_voice_turn(hass, *, text: str, match_key: str | None) -> VoiceTurnPayload | None: ...
```

**TTL:** 5 seconds; prune on store/pop.

### Cache key strategy (phased)

| Phase | `match_key` | Notes |
|-------|-------------|-------|
| **MVP** | `hash(normalized_text)` + monotonic slot | Works for one active satellite |
| **v2** | `{satellite_id or device_id}:{text_hash}` | Needs pipeline context in STT |

**MVP matching in ha_agent:** pop most recent cache entry where `text` matches
(normalized) and `created_at` within 2 s. Document race if two satellites speak
simultaneously.

Export a stable helper for ha_agent:

```python
def pop_matching_voice_turn(hass, *, user_text: str) -> VoiceTurnPayload | None:
    """Public API for ha_agent conversation stage."""
```

Coordinate import path with ha_agent (optional dependency: ha_agent imports from
`ha_liquidai_custom.voice_cache` only if integration loaded).

---

## Part E — ha_agent consumption (pending)

**Repo:** `~/Projects/ha_agent` — see [docs/agent-voice-inference-plan.md](../../ha_agent/docs/agent-voice-inference-plan.md). Contract for handoff:

```python
# ha_agent/conversation.py (sketch)
from ha_liquidai_custom.voice_cache import pop_matching_voice_turn  # optional import

voice_turn = pop_matching_voice_turn(hass, user_text=user_text)
identity = await resolve_agent_user(
    ...,
    speaker_match=voice_turn_to_speaker_match(voice_turn) if voice_turn else None,
)
```

See [agent-voice-inference-plan.md](https://github.com/holger81/ha_agent/blob/main/docs/agent-voice-inference-plan.md) for clustering thresholds and SQLite schema.

---

## Part F — Tests (ha_liquidai)

| Test | File |
|------|------|
| `embed_speaker` parses 192-d vector | `tests/test_client.py` |
| Parallel ASR+embed; embed failure still returns text | `tests/test_stt.py` |
| Cache store/pop TTL and text match | `tests/test_voice_cache.py` |
| `speaker_embed_enabled=false` skips embed | `tests/test_stt.py` |

Mock HTTP; no live inference box in CI.

---

## Part G — Rollout checklist

### Inference box (`.31`) — Part A

- [x] Implement `POST /v1/speaker/embed` (liquidai-audio-docker, commit `f22c871`)
- [ ] Download Sherpa speaker ONNX model to `models/speaker/` on inference host
- [ ] Rebuild/restart container on `.31`
- [ ] Smoke: `curl -F audio=@sample.wav http://192.168.10.31:8811/v1/speaker/embed`
- [ ] Confirm p95 latency < 100 ms on representative WAV

### ha_liquidai

- [ ] `client.embed_speaker()`
- [ ] STT parallel ASR + embed
- [ ] `voice_cache.py` + tests
- [ ] Config flag `speaker_embed_enabled`
- [ ] Bump manifest version; deploy to HA

### ha_agent (separate repo)

- [ ] Clustering + identity resolver embedding path
- [ ] Conversation cache lookup
- [ ] See ha_agent plan doc

### Integration test (live)

- [ ] Speak as person A twice → same `agent_user_id` in Activity log
- [ ] Speak as person B → different id
- [ ] Very short “yeah” → Assist guest, no false cluster

---

## File checklist

### Part A — `~/MeineDateien/Projekte/liquidai-audio` ✅

| Action | Path |
|--------|------|
| Add | `lfm2audio/speaker_embed.py` |
| Edit | `lfm2audio/routes.py`, `lfm2audio/config.py`, `lfm2audio/main.py` |
| Edit | `Dockerfile`, `docker-compose.yaml`, `README.md` |
| Add | `tests/test_speaker_embed.py`, `models/speaker/.gitkeep` |

### Parts B–D — `~/Projects/ha_liquidai` (pending)

| Action | Path |
|--------|------|
| Add | `custom_components/ha_liquidai_custom/voice_cache.py` |
| Edit | `custom_components/ha_liquidai_custom/client.py` |
| Edit | `custom_components/ha_liquidai_custom/stt.py` |
| Edit | `custom_components/ha_liquidai_custom/const.py` |
| Edit | `custom_components/ha_liquidai_custom/config_flow.py` (optional flag) |
| Add | `tests/test_voice_cache.py` |
| Edit | `tests/test_client.py`, `tests/test_stt.py` |
| Edit | `PLAN.md` — Phase 4 |

---

## Environment reference

| Item | Value |
|------|-------|
| HA | `http://192.168.10.32:8123` |
| LiquidAI default | `http://192.168.10.31:8811` |
| LLM | `http://192.168.10.31:9292/v1` |
| MCP | `http://192.168.10.31:2222/mcp` |

---

## References

- [ha_agent agent-voice-inference-plan.md](https://github.com/holger81/ha_agent/blob/main/docs/agent-voice-inference-plan.md)
- [ha_agent agent-identity-design.md](https://github.com/holger81/ha_agent/blob/main/docs/agent-identity-design.md)
- [Sherpa-ONNX speaker ID](https://github.com/k2-fsa/sherpa-onnx#speaker-identification-speaker-id)
- [Assist setup](assist-setup.md)
