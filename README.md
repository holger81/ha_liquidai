# ha_liquidai

Home Assistant custom integration for **local LiquidAI TTS** with Assist **streaming** support.

Replaces the n8n `/webhook/tts` path from [ha_liquidai_n8n](../ha_liquidai_n8n) while keeping agent and STT on n8n.

## Status

Planning — see [PLAN.md](./PLAN.md) for the full implementation plan.

## Stack (target)

| Assist stage | Backend |
|--------------|---------|
| STT | n8n → LiquidAI `/v1/asr` |
| Conversation | n8n → llama.cpp + MCP |
| **TTS** | **This integration** → LiquidAI `/v1/tts` |

## Install (once implemented)

Copy `custom_components/liquidai_tts/` into your Home Assistant `config/custom_components/` directory, restart, then add the integration under **Settings → Devices & services**.

Detailed steps will be added in Phase 1.
