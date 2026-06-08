# ha_liquidai

Home Assistant custom integration for **local LiquidAI voice** (STT, TTS, and agent) with native Assist pipeline support.

Replaces the n8n + Webhook Conversation stack from [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n).

## Status

| Phase | Feature | Status |
|-------|---------|--------|
| 1–2 | TTS (1-shot + streaming) | **Done** (v0.1.0) |
| 3 | STT → LiquidAI `/v1/asr` | **Done** (v0.2.0) |
| 4 | Conversation agent + tool loop | Planned |
| 5 | Multi-model router + MCP client | Planned |
| 6 | Retire n8n / Webhook Conversation | Planned |

See [PLAN.md](PLAN.md) for the full architecture (agent loop, model router, MCP client).

## Stack (target)

| Assist stage | Backend |
|--------------|---------|
| STT | **This integration** → LiquidAI `/v1/asr` |
| Conversation | **This integration** → llama.cpp + MCP Proxy agent loop |
| TTS | **This integration** → LiquidAI `/v1/tts` ✅ |

## Requirements

- Home Assistant **2025.10+** (Assist pipeline streaming TTS)
- LiquidAI server with `/v1/tts` and `/v1/asr` (form POST)

## Install

### Manual

```bash
HA_CONFIG=/path/to/ha/config ./scripts/deploy_to_ha.sh
```

Or copy `custom_components/ha_liquidai_custom/` into `config/custom_components/`, then restart Home Assistant.

### HACS

Add this repository as a custom integration repository, then install **LiquidAI** from HACS.

### Configure

1. **Settings → Devices & services → Add integration → LiquidAI**
2. Enter your LiquidAI base URL (default `http://192.168.10.31:8811`)
3. Set TTS/ASR system prompts and optional advanced tuning
4. Wire STT and TTS into your Assist pipeline — see [docs/assist-setup.md](docs/assist-setup.md)

## Usage

- **Assist**: streaming TTS starts on the first completed sentence while the agent still generates text
- **Automations / `tts.speak`**: one-shot WAV synthesis with sentence chunking for long text

```yaml
action: tts.speak
target:
  entity_id: tts.ha_liquidai_custom
data:
  message: "Hello from LiquidAI."
  media_player_entity_id: media_player.kitchen
```

## Smoke test (without HA)

```bash
pip install aiohttp
python3 scripts/smoke_test_tts.py --text "Hello world."
python3 scripts/smoke_test_stt.py --audio /path/to/sample.wav
```

## Development

```bash
pip install -r requirements.txt
ruff check .
pytest tests/
```

## Docs

- [Implementation plan](PLAN.md)
- [Assist pipeline setup](docs/assist-setup.md)
- [Migration from n8n STT](docs/migration-from-n8n-stt.md)
- [Migration from n8n TTS](docs/migration-from-n8n-tts.md)

## License

MIT
