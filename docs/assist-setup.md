# Assist pipeline setup

Use this integration as the **TTS** stage in a Home Assistant Assist pipeline while keeping **STT** and **Conversation** on n8n.

## Requirements

- Home Assistant **2025.10** or newer (streaming TTS in Assist pipelines)
- LiquidAI server reachable from Home Assistant (default `http://192.168.10.31:8811`)
- n8n workflow from [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n) for agent + STT

## Install the integration

1. Copy `custom_components/liquidai_tts/` into your HA `config/custom_components/` directory, or run:

   ```bash
   HA_CONFIG=/path/to/ha/config ./scripts/deploy_to_ha.sh
   ```

2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Search for **LiquidAI TTS** and complete the config flow.

## Configure the Assist pipeline

1. Open **Settings → Voice assistants**.
2. Edit your pipeline (or create one).
3. Set the stages:

   | Stage | Provider |
   |-------|----------|
   | Speech-to-text | Webhook STT (n8n `/webhook/stt`) |
   | Conversation | Webhook Conversation (n8n `/webhook/agent`, **streaming ON**) |
   | Text-to-speech | **LiquidAI TTS** (`tts.liquidai_tts`) |

4. Remove or disable the old **Webhook TTS** sub-entry if it is still selected.
5. Keep agent timeout as configured in n8n; TTS timeout defaults to **120 s** per synthesis request.

## Verify streaming

1. Enable pipeline debug logging if needed.
2. Ask a long question, for example: “What are today's news?”
3. Expected behaviour:
   - Agent text streams from n8n
   - **First sentence audio** starts before the full reply is generated
   - `tts_output.url` appears early in pipeline debug output (HA 2025.10+)

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No audio | LiquidAI URL from HA host, firewall, `scripts/smoke_test_tts.py` |
| Long delay before speech | Conversation streaming enabled in n8n; TTS entity is `liquidai_tts` not webhook TTS |
| Choppy playback | Tune **Advanced** options (keep edge, chunk gap) under integration settings |
| Tool calls delay speech | Normal — streaming TTS starts after text deltas begin |

## Related

- [migration-from-n8n-tts.md](./migration-from-n8n-tts.md)
- [PLAN.md](../PLAN.md)
