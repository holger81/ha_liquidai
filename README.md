# ha_liquidai

Home Assistant custom integration for **LiquidAI speech** — STT and TTS only.

Pair with **[ha_agent](https://github.com/holger81/ha_agent)** for the Assist conversation agent (LLM + MCP tool loop).

Replaces n8n Webhook STT/TTS from [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n).

## Status

| Feature | Status |
|---------|--------|
| TTS (1-shot + streaming) | **Done** |
| STT → LiquidAI `/v1/asr` | **Done** |
| Speaker embed → `/v1/speaker/embed` | **Done** — optional; STT works without it |
| Voice turn cache (for ha_agent) | **Done** |
| Conversation agent | **[ha_agent](https://github.com/holger81/ha_agent)** |

See [PLAN.md](PLAN.md) for scope and [ha_agent PLAN](https://github.com/holger81/ha_agent/blob/main/PLAN.md) for the agent roadmap.

## Assist pipeline

| Stage | Integration |
|-------|-------------|
| STT | **This repo** → LiquidAI `/v1/asr` (+ optional speaker embed) |
| Conversation | **[ha_agent](https://github.com/holger81/ha_agent)** |
| TTS | **This repo** → LiquidAI `/v1/tts` |

## Voice fingerprinting (optional)

When enabled (default), STT calls `/v1/speaker/embed` in parallel with ASR and stores a short-lived voice turn in `hass.data` for [ha_agent](https://github.com/holger81/ha_agent) to resolve speaker identity.

If fingerprinting is unavailable — endpoint missing, model not deployed, timeout, or disabled in config — **transcription and the rest of Assist still work**. Embed failures are logged and ignored; ha_agent falls back to guest identity.

Configure under **LiquidAI → Voice settings**: `speaker_embed_enabled`, `speaker_embed_timeout`.

Details: [docs/voice-speaker-embed-plan.md](docs/voice-speaker-embed-plan.md)

## Requirements

- Home Assistant **2025.10+** (streaming TTS in Assist)
- LiquidAI server with `/v1/tts` and `/v1/asr`
- Optional: `/v1/speaker/embed` on the same host (Sherpa-ONNX on the inference box)

## Install

```bash
HA_CONFIG=/path/to/ha/config ./scripts/deploy_to_ha.sh
```

Or install **LiquidAI** from HACS, then add **HA Agent** from [ha_agent](https://github.com/holger81/ha_agent).

## Development

```bash
pip install -r requirements.txt
ruff check .
pytest tests/
```

## Docs

- [Assist pipeline setup](docs/assist-setup.md)
- [Voice speaker embed plan](docs/voice-speaker-embed-plan.md) (Phase 4 / ha_agent 9b)
- [Migration from n8n STT](docs/migration-from-n8n-stt.md)
- [Migration from n8n TTS](docs/migration-from-n8n-tts.md)

## License

MIT
