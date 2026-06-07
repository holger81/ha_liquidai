# ha_liquidai

Home Assistant custom integration for **local LiquidAI TTS** with Assist **streaming** support.

Replaces the n8n `/webhook/tts` path from [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n) while keeping agent and STT on n8n.

## Status

**v0.1.0** — config flow, one-shot TTS, and Assist streaming TTS implemented.

## Stack

| Assist stage | Backend |
|--------------|---------|
| STT | n8n → LiquidAI `/v1/asr` |
| Conversation | n8n → llama.cpp + MCP |
| **TTS** | **This integration** → LiquidAI `/v1/tts` |

## Requirements

- Home Assistant **2025.10+** (Assist pipeline streaming TTS)
- LiquidAI server with `/v1/tts` (form POST: `text`, `system_prompt`)

## Install

### Manual

```bash
HA_CONFIG=/path/to/ha/config ./scripts/deploy_to_ha.sh
```

Or copy `custom_components/ha_liquidai_custom/` into `config/custom_components/`, then restart Home Assistant.

### HACS

Add this repository as a custom integration repository, then install **LiquidAI TTS** from HACS.

### Configure

1. **Settings → Devices & services → Add integration → LiquidAI TTS**
2. Enter your LiquidAI base URL (default `http://192.168.10.31:8811`)
3. Set the system prompt and optional advanced tuning
4. Wire the entity into your Assist pipeline — see [docs/assist-setup.md](docs/assist-setup.md)

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
- [Migration from n8n TTS](docs/migration-from-n8n-tts.md)

## License

MIT
