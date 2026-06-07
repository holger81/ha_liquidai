# Assist pipeline setup

Use this integration as the **TTS** stage in a Home Assistant Assist pipeline while keeping **STT** and **Conversation** on n8n.

## Requirements

- Home Assistant **2025.10** or newer (streaming TTS in Assist pipelines)
- LiquidAI server reachable from Home Assistant (default `http://192.168.10.31:8811`)
- n8n workflow from [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n) for agent + STT

## Install the integration

1. Copy `custom_components/ha_liquidai_custom/` into your HA `config/custom_components/` directory, or run:

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
   | Text-to-speech | **LiquidAI TTS** (`tts.ha_liquidai_custom`) |

4. Remove or disable the old **Webhook TTS** sub-entry if it is still selected.
5. Keep agent timeout as configured in n8n; TTS timeout defaults to **120 s** per synthesis request.

## Verify streaming

1. Enable pipeline debug logging if needed.
2. Ask a long question, for example: “What are today's news?”
3. Expected behaviour:
   - Agent text streams from n8n
   - **First sentence audio** starts before the full reply is generated
   - `tts_output.url` appears early in pipeline debug output (HA 2025.10+)

### Three layers must all stream

End-to-end streaming is **not** only a TTS setting. All three layers must cooperate:

| Layer | What to check |
|-------|----------------|
| **1. Webhook Conversation (HA)** | Conversation sub-entry → **Enable Response Streaming** must be ON. If OFF, HA waits for the full n8n JSON reply before any TTS starts. |
| **2. n8n agent** | Webhook `responseMode: streaming`, Agent `enableStreaming: true`, and NDJSON lines like `{"type":"item","content":"..."}` (n8n LangChain agent handles this when streaming is wired correctly). |
| **3. LiquidAI TTS (this integration)** | Implements `async_stream_tts_audio`. HA only connects the text stream to TTS after **60 characters** (`STREAM_RESPONSE_CHARS` in core) or when tool calls follow text. |

In **Assist pipeline debug**, look for:

- `chat_log_delta` events during intent (text arriving incrementally)
- `tts_start_streaming: true` in an `intent-progress` event
- `stream_response: true` in `run-start` → `tts_output`

If text appears all at once at the end, the problem is layer 1 or 2, not TTS.

### TTS chunk tuning

Under **LiquidAI TTS → Configure → Advanced**:

- **Speech speed** — default `1.0`. Values above `1.0` play faster (e.g. `1.25` ≈ 25% faster) via ffmpeg; LiquidAI itself has no speed parameter.

Chat text appears before audio because the LLM streams faster than LiquidAI can synthesize each chunk. The integration overlaps synthesis, text buffering, and MP3 conversion between consecutive sentences to reduce gaps without changing the MP3 chunk format Home Assistant expects.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No audio | LiquidAI URL from HA host, firewall, `scripts/smoke_test_tts.py` |
| Long delay before speech | **Enable Response Streaming** on Webhook Conversation sub-entry; confirm `chat_log_delta` in pipeline debug; TTS entity is `ha_liquidai_custom` not webhook TTS |
| Choppy playback | Tune **Advanced** options (keep edge, chunk gap) under integration settings |
| Tool calls delay speech | Normal — streaming TTS starts after text deltas begin |

## Related

- [migration-from-n8n-tts.md](./migration-from-n8n-tts.md)
- [PLAN.md](../PLAN.md)
