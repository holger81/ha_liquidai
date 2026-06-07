"""Unit tests for audio helpers."""

from __future__ import annotations

import importlib.util
import struct
import sys
import types
from pathlib import Path

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "ha_liquidai_custom"
)


def _load_component_module(name: str):
    """Load a ha_liquidai_custom submodule without importing Home Assistant."""
    module_name = f"ha_liquidai_custom.{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    if "ha_liquidai_custom" not in sys.modules:
        package = types.ModuleType("ha_liquidai_custom")
        package.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules["ha_liquidai_custom"] = package

    path = COMPONENT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load_component_module("const")
audio = _load_component_module("audio")

sanitize_for_tts = audio.sanitize_for_tts
split_for_tts = audio.split_for_tts
pop_complete_sentence = audio.pop_complete_sentence
trim_pcm_silence = audio.trim_pcm_silence
concat_wav_buffers = audio.concat_wav_buffers


def _make_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm


def test_sanitize_for_tts_strips_markdown() -> None:
    raw = "**Hello** [world](https://example.com) `code`"
    assert sanitize_for_tts(raw) == "Hello world code"


def test_split_for_tts_one_sentence_per_chunk() -> None:
    text = "First sentence. Second sentence! Third?"
    chunks = split_for_tts(text, max_len=160)
    assert chunks == ["First sentence.", "Second sentence!", "Third?"]


def test_pop_complete_sentence() -> None:
    sentence, remainder = pop_complete_sentence("Hello world. More text")
    assert sentence == "Hello world."
    assert remainder == " More text"


def test_trim_pcm_silence_preserves_edges() -> None:
    sample_rate = 24000
    silence = b"\x00\x00" * 3000
    signal = b"\xff\x7f" * 200
    pcm = silence + signal + silence
    trimmed = trim_pcm_silence(pcm, sample_rate, keep_edge_ms=100)
    assert len(trimmed) < len(pcm)
    assert len(trimmed) >= len(signal)


def test_concat_wav_buffers_merges_two_chunks() -> None:
    pcm_a = b"\x10\x00" * 100
    pcm_b = b"\x20\x00" * 100
    wav_a = _make_wav(pcm_a)
    wav_b = _make_wav(pcm_b)
    merged = concat_wav_buffers([wav_a, wav_b], chunk_gap_ms=0)
    assert merged.startswith(b"RIFF")
    assert len(merged) > len(wav_a)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("Short.", ["Short."]),
    ],
)
def test_split_for_tts_edge_cases(text: str, expected: list[str]) -> None:
    assert split_for_tts(text) == expected
