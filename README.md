# ha_liquidai

Home Assistant custom integration for **LiquidAI speech** — STT and TTS only.

Pair with **[ha_agent](https://github.com/holger81/ha_agent)** for the Assist conversation agent (LLM + MCP tool loop).

Replaces n8n Webhook STT/TTS from [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n).

## Status

| Feature | Status |
|---------|--------|
| TTS (1-shot + streaming) | **Done** |
| STT → LiquidAI `/v1/asr` | **Done** |
| Conversation agent | **[ha_agent](https://github.com/holger81/ha_agent)** |

See [PLAN.md](PLAN.md) for scope and [ha_agent PLAN](https://github.com/holger81/ha_agent/blob/main/PLAN.md) for the agent roadmap.

## Assist pipeline

| Stage | Integration |
|-------|-------------|
| STT | **This repo** → LiquidAI `/v1/asr` |
| Conversation | **[ha_agent](https://github.com/holger81/ha_agent)** |
| TTS | **This repo** → LiquidAI `/v1/tts` |

## Requirements

- Home Assistant **2025.10+** (streaming TTS in Assist)
- LiquidAI server with `/v1/tts` and `/v1/asr`

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
- [Migration from n8n STT](docs/migration-from-n8n-stt.md)
- [Migration from n8n TTS](docs/migration-from-n8n-tts.md)

## License

MIT
