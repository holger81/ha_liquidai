# Assist pipeline setup

Use this integration for **STT**, **conversation agent**, and **TTS** in a Home Assistant Assist pipeline — no n8n required.

## Requirements

- Home Assistant **2025.10** or newer (streaming TTS and conversation in Assist pipelines)
- LiquidAI server reachable from Home Assistant (default `http://192.168.10.31:8811`)
- OpenAI-compatible LLM server (default `http://192.168.10.31:9292/v1`)
- MCP Proxy for tools (default `http://192.168.10.31:2222/mcp`)

## Install the integration

1. Copy `custom_components/ha_liquidai_custom/` into your HA `config/custom_components/` directory, or run:

   ```bash
   HA_CONFIG=/path/to/ha/config ./scripts/deploy_to_ha.sh
   ```

2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Search for **LiquidAI** and complete the config flow (LiquidAI URL → voice prompts → agent prompts → LLM → MCP → agent settings → audio tuning).

## Configure the Assist pipeline

1. Open **Settings → Voice assistants**.
2. Edit your pipeline (or create one).
3. Set the stages:

   | Stage | Provider |
   |-------|----------|
   | Speech-to-text | **LiquidAI STT** (`stt.ha_liquidai_custom`) |
   | Conversation | **LiquidAI** (`conversation.ha_liquidai_custom`) |
   | Text-to-speech | **LiquidAI TTS** (`tts.ha_liquidai_custom`) |

4. Remove or disable **Webhook Conversation**, **Webhook STT**, and **Webhook TTS** if still selected.
5. Timeouts default to **120 s** per request (configurable in the integration).

## Verify STT

1. Use Assist with a short phrase, for example: “Turn on the kitchen light.”
2. Expected behaviour:
   - Transcript appears without n8n in the path
   - Agent receives the same text

Or run a local smoke test:

```bash
python3 scripts/smoke_test_stt.py --audio sample.wav
```

## Verify conversation agent

1. Ask: “Turn off the dining room lights” (with the entity exposed to Assist).
2. Expected behaviour:
   - Agent calls MCP `ha_call_service` via the tool loop
   - Spoken confirmation via LiquidAI TTS

3. Ask: “What’s the news?”
4. Expected behaviour:
   - Agent calls `mcp_news__news_curate` and summarizes headlines

Enable **Enable streaming responses** in agent settings for incremental text in Assist.

## Verify streaming TTS

1. Enable pipeline debug logging if needed.
2. Ask a long question, for example: “Tell me about Rome.”
3. Expected behaviour:
   - Agent text streams from the LLM
   - **First sentence audio** starts before the full reply is generated

In **Assist pipeline debug**, look for:

- `chat_log_delta` events during intent (text arriving incrementally)
- `tts_start_streaming: true` in an `intent-progress` event
- `stream_response: true` in `run-start` → `tts_output`

### TTS chunk tuning

Under **LiquidAI → Configure → Advanced**:

- **Speech speed** — default `1.0`. Values above `1.0` play faster (e.g. `1.25` ≈ 25% faster) via ffmpeg.

Chat text appears before audio because the LLM streams faster than LiquidAI can synthesize each chunk. The integration overlaps synthesis, text buffering, and MP3 conversion between consecutive sentences.

## Reconfigure

Use **Settings → Devices & services → LiquidAI → Reconfigure** to update LiquidAI, LLM, or MCP URLs without editing YAML.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No transcript | LiquidAI URL from HA host, firewall, `scripts/smoke_test_stt.py` |
| Agent says it can't reach tools | MCP URL, bearer token, MCP Proxy health at `/api/health` |
| Wrong model behaviour | LLM URL/model in integration settings; reload after change |
| No audio | LiquidAI URL, `scripts/smoke_test_tts.py` |
| Long delay before speech | Enable streaming in agent settings; confirm `chat_log_delta` in pipeline debug |
| Choppy playback | Tune **Advanced** options under integration settings |

## Related

- [migration-from-n8n-stt.md](./migration-from-n8n-stt.md)
- [migration-from-n8n-tts.md](./migration-from-n8n-tts.md)
- [PLAN.md](../PLAN.md)
