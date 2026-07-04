# LiquidAI for Home Assistant — STT & TTS

Project root: `~/Projects/ha_liquidai`  
Agent / conversation: [`~/Projects/ha_agent`](../ha_agent)  
Inference box (ASR/TTS/speaker embed): [`liquidai-audio-docker`](https://github.com/holger81/liquidai-audio-docker) (`~/MeineDateien/Projekte/liquidai-audio`)  
Legacy stack: `~/Projects/ha_liquidai_n8n` (n8n + Webhook Conversation — to be retired)

## Goal

Native Home Assistant integration for **LiquidAI speech only**:

1. **STT** — Assist pipeline → LiquidAI `/v1/asr` (`:8811`)
2. **TTS** — Assist pipeline → LiquidAI `/v1/tts` with streaming sentence chunks

Conversation, LLM, and MCP tooling live in the separate **[ha_agent](https://github.com/holger81/ha_agent)** integration.

## Target architecture

```mermaid
flowchart TB
  subgraph HA["Home Assistant Assist pipeline"]
    STT["ha_liquidai_custom STT"]
    Agent["ha_agent Conversation"]
    TTS["ha_liquidai_custom TTS"]
  end

  subgraph Backends
    LAI["LiquidAI :8811\nASR + TTS + speaker/embed"]
    LLM["llama.cpp :9292"]
    MCP["MCP Proxy :2222"]
  end

  STT --> LAI
  Agent --> LLM
  Agent --> MCP
  TTS --> LAI
```

## Repository layout

```
ha_liquidai/
├── custom_components/ha_liquidai_custom/
│   ├── client.py          # LiquidAI ASR/TTS HTTP
│   ├── stt.py             # SpeechToTextEntity
│   ├── tts.py             # TextToSpeechEntity (streaming)
│   ├── audio.py           # TTS sanitize/split/trim
│   ├── config_flow.py     # LiquidAI URL + prompts + audio tuning
│   └── ...
├── tests/
├── scripts/
└── docs/
```

## Phases

### Phase 0 — Bootstrap ✅

- [x] Repo, manifest, deploy script

### Phase 1 — Config flow + TTS ✅

- [x] Config flow, 1-shot TTS, tests + ruff CI

### Phase 2 — Streaming TTS ✅

- [x] `async_stream_tts_audio()` + Assist early playback (HA ≥ 2025.10)

### Phase 3 — LiquidAI STT ✅

- [x] `SpeechToTextEntity`, PCM→WAV wrap for Assist pipeline
- [x] Document pipeline wiring with [ha_agent](../ha_agent)

### Phase 4 — Speaker embedding bridge

Supports [ha_agent Phase 9b](https://github.com/holger81/ha_agent/blob/main/docs/agent-voice-inference-plan.md)
voice identity. Full plan: [docs/voice-speaker-embed-plan.md](docs/voice-speaker-embed-plan.md).

**Part A — inference box** (liquidai-audio-docker, shipped 2026-07):

- [x] `POST /v1/speaker/embed` (Sherpa-ONNX on `:8811`) — code in `lfm2audio/speaker_embed.py`, `routes.py`
- [ ] Deploy on `.31`: Sherpa ONNX in `models/speaker/`, rebuild container, smoke curl

**Parts B–D — this repo** (`~/Projects/ha_liquidai`):

- [x] `client.embed_speaker()` in `custom_components/ha_liquidai_custom/client.py`
- [x] Parallel ASR + embed in `custom_components/ha_liquidai_custom/stt.py`
- [x] `custom_components/ha_liquidai_custom/voice_cache.py` — short-lived `hass.data` bridge to ha_agent
- [x] Config flag `speaker_embed_enabled` in `const.py` / `config_flow.py`
- [x] Tests: `tests/test_client.py`, `tests/test_stt.py`, `tests/test_voice_cache.py`

## Assist pipeline wiring

| Stage | Integration |
|-------|-------------|
| Speech-to-text | **LiquidAI** (`stt.ha_liquidai_custom`) |
| Conversation | **[HA Agent](https://github.com/holger81/ha_agent)** (`conversation.ha_agent`) |
| Text-to-speech | **LiquidAI** (`tts.ha_liquidai_custom`) |

See [docs/assist-setup.md](docs/assist-setup.md).

## Next action

Deploy Sherpa model on `.31` and smoke-test `POST /v1/speaker/embed`. Then implement ha_agent Phase 9b clustering — see [ha_agent PLAN.md](https://github.com/holger81/ha_agent/blob/main/PLAN.md).
