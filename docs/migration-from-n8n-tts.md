# Migration from n8n webhook TTS

This guide moves **TTS only** from the n8n hybrid workflow to the native `ha_liquidai_custom` integration. Agent and STT stay on n8n.

## Before

```
Assist → STT (n8n) → Agent (n8n) → TTS (n8n /webhook/tts) → LiquidAI
```

## After

```
Assist → STT (n8n) → Agent (n8n) → TTS (HA ha_liquidai_custom) → LiquidAI
```

## Steps

### 1. Deploy the integration

Follow [assist-setup.md](./assist-setup.md) to install and configure `ha_liquidai_custom` in Home Assistant.

### 2. Switch the Assist pipeline

1. **Settings → Voice assistants** → edit your pipeline.
2. Change **Text-to-speech** from Webhook TTS to **LiquidAI TTS**.
3. Save and test with a short phrase via Assist.

### 3. Slim the n8n workflow (optional)

In [ha_liquidai_n8n](https://github.com/holger81/ha_liquidai_n8n):

**Option A — remove TTS branch (recommended for daily use)**

- Disable or delete: Webhook TTS → Parse Voice → LiquidAI TTS → TTS Response
- Keep: Webhook STT, Webhook Agent, health checks

**Option B — keep for external testing**

- Leave the TTS webhook active for `curl` tests only
- Do not use it in the Assist pipeline

### 4. Validate

- [ ] Short `tts.speak` automation still works
- [ ] Assist long reply starts audio before agent finishes
- [ ] Agent MCP tools still work (unchanged path)
- [ ] STT unchanged

## Behaviour differences

| Topic | n8n TTS | HA ha_liquidai_custom |
|-------|---------|-----------------|
| Latency | Waits for full agent reply + batch synthesis | Streams per sentence during agent output |
| Long text | Parallel chunk synthesis, merged WAV | Same merge logic for 1-shot; stream for Assist |
| Config | Hard-coded in workflow JS | HA config flow (URL, prompt, tuning) |
| Dependencies | n8n must be up for TTS | Direct HA → LiquidAI |

## Rollback

1. Re-enable Webhook TTS in the Assist pipeline.
2. Re-enable the n8n TTS branch if disabled.
3. Remove or disable the LiquidAI TTS integration.
