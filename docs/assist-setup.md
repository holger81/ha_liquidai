# Assist pipeline setup

Use **LiquidAI** (this integration) for **STT** and **TTS**, and **[HA Agent](https://github.com/holger81/ha_agent)** for the conversation stage.

## Requirements

- Home Assistant **2025.10** or newer
- LiquidAI server (default `http://192.168.10.31:8811`)
- [HA Agent](https://github.com/holger81/ha_agent) installed for conversation (LLM + MCP)

## Install LiquidAI (STT + TTS)

1. Copy or deploy `custom_components/ha_liquidai_custom/`, restart HA
2. **Settings → Devices & services → Add integration → LiquidAI**
3. Complete: LiquidAI URL → voice prompts → advanced audio tuning

## Install HA Agent (conversation)

1. Deploy `custom_components/ha_agent/` from [ha_agent](https://github.com/holger81/ha_agent)
2. **Add integration → HA Agent**
3. Complete: agent prompts → LLM → MCP → agent settings

## Configure the Assist pipeline

| Stage | Provider |
|-------|----------|
| Speech-to-text | **LiquidAI STT** (`stt.ha_liquidai_custom`) |
| Conversation | **HA Agent** (`conversation.ha_agent`) |
| Text-to-speech | **LiquidAI TTS** (`tts.ha_liquidai_custom`) |

Remove Webhook STT/TTS/Conversation if still wired.

## Verify STT

Use Assist mic or:

```bash
python3 scripts/smoke_test_stt.py --audio sample.wav
```

Assist sends raw PCM; the integration wraps it in WAV before calling LiquidAI ASR.

## Verify streaming TTS

Ask a long question in Assist. In pipeline debug, look for `chat_log_delta` and `tts_start_streaming: true`.

### TTS tuning

**LiquidAI → Configure → Advanced:** speech speed, chunk length, stream-first-chunk chars.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| speech-to-text failed | LiquidAI URL; HA logs for ASR HTTP errors |
| No LiquidAI STT in pipeline | Reload integration after update |
| No transcript / 500 from ASR | PCM→WAV fix requires latest `ha_liquidai_custom` |
| Agent / tools issues | [ha_agent](https://github.com/holger81/ha_agent) docs |

## Related

- [ha_agent assist setup](https://github.com/holger81/ha_agent/blob/main/docs/assist-setup.md)
- [PLAN.md](../PLAN.md)
