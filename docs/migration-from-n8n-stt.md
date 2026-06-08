# Migration from n8n webhook STT

This guide moves **STT** from the n8n hybrid workflow to the native `ha_liquidai_custom` integration. Agent and TTS can stay on n8n/HACS until Phase 4–6.

## Before

```
Assist → STT (n8n) → Agent (n8n) → TTS (HA or n8n) → LiquidAI
```

## After

```
Assist → STT (HA ha_liquidai_custom) → Agent (n8n) → TTS (HA or n8n) → LiquidAI
```

## Steps

### 1. Deploy v0.2.0+

Follow [assist-setup.md](./assist-setup.md) to install or upgrade `ha_liquidai_custom`.

### 2. Switch the Assist pipeline

1. **Settings → Voice assistants** → edit your pipeline.
2. Change **Speech-to-text** from Webhook STT to **LiquidAI STT** (`stt.ha_liquidai_custom`).
3. Save and test with a short voice command.

### 3. Slim the n8n workflow (optional)

In [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n):

- Disable or delete: Webhook STT → Extract Audio → LiquidAI ASR → STT Response
- Keep: Webhook Agent, health checks, TTS branch if still used

### 4. Validate

- [ ] Voice command transcribed without n8n
- [ ] Agent still receives the expected text
- [ ] Latency comparable to the old HTTP Request path

## Behaviour differences

| Topic | n8n STT | HA ha_liquidai_custom |
|-------|---------|------------------------|
| Hop | HA → n8n → LiquidAI | HA → LiquidAI direct |
| Config | Hard-coded in workflow | HA config flow (URL, ASR prompt) |
| Formats | WAV + OGG (via mime_type) | WAV + OGG (Assist metadata) |
| Dependencies | n8n must be up for STT | Direct HA → LiquidAI |

## Rollback

1. Re-enable Webhook STT in the Assist pipeline.
2. Re-enable the n8n STT branch if disabled.

## Related

- [migration-from-n8n-tts.md](./migration-from-n8n-tts.md)
- [PLAN.md](../PLAN.md)
