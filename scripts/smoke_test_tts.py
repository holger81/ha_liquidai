#!/usr/bin/env python3
"""Smoke test LiquidAI /v1/tts without Home Assistant."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from liquidai_tts.audio import read_sample_rate, sanitize_for_tts
from liquidai_tts.const import DEFAULT_SYSTEM_PROMPT, DEFAULT_URL


async def main() -> int:
    """Run a single TTS request and write the WAV to disk."""
    parser = argparse.ArgumentParser(description="Smoke test LiquidAI TTS")
    parser.add_argument("--url", default=DEFAULT_URL, help="LiquidAI base URL")
    parser.add_argument("--text", default="Hello from ha_liquidai smoke test.")
    parser.add_argument(
        "--system-prompt",
        default=DEFAULT_SYSTEM_PROMPT,
        help="LiquidAI system prompt",
    )
    parser.add_argument(
        "--output",
        default="smoke_test.wav",
        help="Output WAV path",
    )
    args = parser.parse_args()

    text = sanitize_for_tts(args.text) or args.text
    data = aiohttp.FormData()
    data.add_field("text", text)
    data.add_field("system_prompt", args.system_prompt)

    base_url = args.url.rstrip("/")
    async with aiohttp.ClientSession() as session, session.post(
        f"{base_url}/v1/tts",
        data=data,
        timeout=aiohttp.ClientTimeout(total=120),
    ) as response:
        if response.status != 200:
            body = await response.text()
            print(f"TTS failed: HTTP {response.status}\n{body[:500]}", file=sys.stderr)
            return 1
        wav_bytes = await response.read()

    output = Path(args.output)
    output.write_bytes(wav_bytes)
    sample_rate = read_sample_rate(wav_bytes)
    print(f"Wrote {len(wav_bytes)} bytes to {output} ({sample_rate} Hz)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
