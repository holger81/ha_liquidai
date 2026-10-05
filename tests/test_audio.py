"""Unit tests for audio helpers."""

from __future__ import annotations

import struct

import pytest

from conftest import load_component_module

audio = load_component_module("audio")

sanitize_for_tts = audio.sanitize_for_tts
split_for_tts = audio.split_for_tts
iter_sentences = audio.iter_sentences
pop_complete_sentence = audio.pop_complete_sentence
pop_early_chunk = audio.pop_early_chunk
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


def _naive_trim(
    pcm: bytes, sample_rate: int, *, threshold: int, keep_edge_ms: int
) -> bytes:
    """Reference per-sample implementation to compare the fast path against."""
    keep = max(1, (sample_rate * keep_edge_ms) // 1000)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: (len(pcm) // 2) * 2])
    loud = [i for i, s in enumerate(samples) if abs(s) > threshold]
    if not loud:
        return pcm
    start = max(0, loud[0] - keep)
    end = min(len(samples) - 1, loud[-1] + keep)
    if start >= end:
        return pcm
    return pcm[start * 2 : (end + 1) * 2]


def test_sanitize_for_tts_strips_markdown() -> None:
    raw = "**Hello** [world](https://example.com) `code`"
    assert sanitize_for_tts(raw) == "Hello world code"


def test_split_for_tts_one_sentence_per_chunk() -> None:
    text = "First sentence. Second sentence! Third?"
    chunks = split_for_tts(text, max_len=160)
    assert chunks == ["First sentence.", "Second sentence!", "Third?"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It is 21.5 degrees outside.", ["It is 21.5 degrees outside."]),
        (
            "Version 2026.10.1 is installed. Update later.",
            ["Version 2026.10.1 is installed.", "Update later."],
        ),
        ("Dr. Smith called. Call back.", ["Dr. Smith called.", "Call back."]),
        ("Use e.g. the kitchen light. Done.", ["Use e.g. the kitchen light.", "Done."]),
        ("Wait... really?! Yes.", ["Wait...", "really?!", "Yes."]),
        ("No trailing punctuation", ["No trailing punctuation"]),
    ],
)
def test_iter_sentences_keeps_decimals_and_abbreviations(
    text: str, expected: list[str]
) -> None:
    assert iter_sentences(text) == expected


def test_pop_complete_sentence() -> None:
    sentence, remainder = pop_complete_sentence("Hello world. More text")
    assert sentence == "Hello world."
    assert remainder == " More text"


def test_pop_complete_sentence_waits_for_whitespace_while_streaming() -> None:
    """A terminator at the very end may be mid-number; hold it until more arrives."""
    sentence, remainder = pop_complete_sentence("It is 21.")
    assert sentence is None
    assert remainder == "It is 21."

    sentence, remainder = pop_complete_sentence("It is 21.5 degrees. Nice")
    assert sentence == "It is 21.5 degrees."
    assert remainder == " Nice"


def test_pop_complete_sentence_at_end_accepts_trailing_terminator() -> None:
    sentence, remainder = pop_complete_sentence("It is warm.", at_end=True)
    assert sentence == "It is warm."
    assert remainder == ""


def test_pop_complete_sentence_skips_abbreviation() -> None:
    sentence, remainder = pop_complete_sentence("Ask Dr. Who about it. Then go")
    assert sentence == "Ask Dr. Who about it."
    assert remainder == " Then go"


def test_pop_early_chunk() -> None:
    chunk, remainder = pop_early_chunk("Hello world this is a long buffer", 12)
    assert chunk == "Hello world this is a long"
    assert remainder == "buffer"


def test_pop_early_chunk_keeps_word_separator_at_buffer_end() -> None:
    """Trailing whitespace must survive so the next delta starts a new word."""
    chunk, remainder = pop_early_chunk("Turning on the kitchen ", 10)
    assert chunk == "Turning on the"
    assert remainder == "kitchen "

    chunk, remainder = pop_early_chunk("Turning on the kitchen", 10)
    assert chunk == "Turning on the"
    assert remainder == "kitchen"


def test_pcm_has_signal_detects_loud_samples() -> None:
    silence = b"\x00\x00" * 100
    speech = silence + struct.pack("<h", 2000) + silence
    assert audio.pcm_has_signal(silence, threshold=350) is False
    assert audio.pcm_has_signal(speech, threshold=350) is True


def test_trim_leading_pcm_silence_keeps_trailing() -> None:
    silence = b"\x00\x00" * 1000
    speech = struct.pack("<h", 5000) * 200
    trailing = b"\x00\x00" * 800
    pcm = silence + speech + trailing
    trimmed = audio.trim_leading_pcm_silence(
        pcm, 24000, threshold=350, keep_edge_ms=0
    )
    assert trimmed.startswith(speech[:4]) or struct.pack("<h", 5000) in trimmed[:4]
    # Trailing silence must survive — more PCM may still arrive.
    assert trimmed.endswith(trailing)


def test_trim_pcm_silence_preserves_edges() -> None:
    sample_rate = 24000
    silence = b"\x00\x00" * 3000
    signal = b"\xff\x7f" * 200
    pcm = silence + signal + silence
    trimmed = trim_pcm_silence(pcm, sample_rate, keep_edge_ms=100)
    assert len(trimmed) < len(pcm)
    assert len(trimmed) >= len(signal)


@pytest.mark.parametrize("threshold", [0, 350, 5000])
@pytest.mark.parametrize(
    "layout",
    [
        (0, 10, 0),
        (5000, 300, 7000),
        (1023, 1, 1024),
        (1024, 2048, 1),
        (3, 0, 3),
    ],
)
def test_trim_pcm_silence_matches_reference(
    threshold: int, layout: tuple[int, int, int]
) -> None:
    """Block-scanning trim must agree with the per-sample reference."""
    lead, loud, trail = layout
    pcm = (
        struct.pack("<h", 100) * lead
        + struct.pack("<h", -20000) * loud
        + struct.pack("<h", -100) * trail
    )
    for keep_edge_ms in (0, 10, 100):
        assert trim_pcm_silence(
            pcm, 24000, threshold=threshold, keep_edge_ms=keep_edge_ms
        ) == _naive_trim(pcm, 24000, threshold=threshold, keep_edge_ms=keep_edge_ms)


def test_trim_pcm_silence_handles_min_int16() -> None:
    pcm = b"\x00\x00" * 2000 + struct.pack("<h", -32768) + b"\x00\x00" * 2000
    trimmed = trim_pcm_silence(pcm, 24000, threshold=350, keep_edge_ms=0)
    # keep_edge is clamped to at least one sample on each side.
    assert trimmed == b"\x00\x00" + struct.pack("<h", -32768) + b"\x00\x00"


def test_trim_pcm_silence_all_silent_returns_input() -> None:
    pcm = b"\x00\x00" * 5000
    assert trim_pcm_silence(pcm, 24000) == pcm


def test_concat_wav_buffers_merges_two_chunks() -> None:
    pcm_a = b"\x10\x00" * 100
    pcm_b = b"\x20\x00" * 100
    wav_a = _make_wav(pcm_a)
    wav_b = _make_wav(pcm_b)
    merged = concat_wav_buffers([wav_a, wav_b], chunk_gap_ms=0)
    assert merged.startswith(b"RIFF")
    assert len(merged) > len(wav_a)


def test_pcm_to_wav_wraps_raw_pcm() -> None:
    pcm = b"\x00\x00" * 1600
    wav = audio.pcm_to_wav(pcm, sample_rate=16000, channels=1, bit_rate=16)
    assert audio.is_wav(wav)
    assert audio.extract_pcm(wav) == pcm


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("Short.", ["Short."]),
    ],
)
def test_split_for_tts_edge_cases(text: str, expected: list[str]) -> None:
    assert split_for_tts(text) == expected
