#!/usr/bin/env python3
"""Smoke test LiquidAI /v1/asr without Home Assistant."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))

from ha_liquidai_custom.const import DEFAULT_ASR_SYSTEM_PROMPT, DEFAULT_URL


async def main() -> int:
    """Run a single ASR request against a WAV file."""
    parser = argparse.ArgumentParser(description="Smoke test LiquidAI ASR")
    parser.add_argument("--url", default=DEFAULT_URL, help="LiquidAI base URL")
    parser.add_argument(
        "--audio",
        required=True,
        help="Path to WAV or OGG audio file",
    )
    parser.add_argument(
        "--mime-type",
        default="",
        help="Override MIME type (default: infer from extension)",
    )
    parser.add_argument(
        "--system-prompt",
        default=DEFAULT_ASR_SYSTEM_PROMPT,
        help="LiquidAI ASR system prompt",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.is_file():
        print(f"Audio file not found: {audio_path}", file=sys.stderr)
        return 1

    mime_type = args.mime_type
    if not mime_type:
        mime_type = "audio/ogg" if audio_path.suffix.lower() == ".ogg" else "audio/wav"

    audio_bytes = audio_path.read_bytes()
    form = aiohttp.FormData()
    form.add_field("type", mime_type)
    form.add_field(
        "audio",
        audio_bytes,
        filename=audio_path.name,
        content_type=mime_type,
    )
    form.add_field("system_prompt", args.system_prompt)

    base_url = args.url.rstrip("/")
    async with aiohttp.ClientSession() as session, session.post(
        f"{base_url}/v1/asr",
        data=form,
        timeout=aiohttp.ClientTimeout(total=120),
    ) as response:
        if response.status != 200:
            body = await response.text()
            print(f"ASR failed: HTTP {response.status}\n{body[:500]}", file=sys.stderr)
            return 1
        payload = await response.json(content_type=None)

    text = str(payload.get("text", "")).strip()
    print(f"Transcript ({len(audio_bytes)} bytes in): {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
