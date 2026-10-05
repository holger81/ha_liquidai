"""Text cleanup and WAV/PCM helpers ported from ha_liquidai_n8n."""

from __future__ import annotations

import re
import struct
import sys
from array import array

from .const import (
    CHUNK_GAP_MS,
    DEFAULT_SAMPLE_RATE,
    KEEP_EDGE_MS,
    MAX_CHUNK_LEN,
    SILENCE_THRESHOLD,
)

# A sentence ends at terminal punctuation followed by whitespace (or end of
# text). The lookahead keeps decimals ("21.5"), versions ("2026.10.1"), and
# times ("10.30") intact. Abbreviations are handled in _find_sentence_end.
_SENTENCE_END_RE = re.compile(r"[.!?]+(?=\s|$)")
_SENTENCE_END_STREAMING_RE = re.compile(r"[.!?]+(?=\s)")
_ABBREVIATIONS = frozenset(
    {"dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "vs", "e.g", "i.e"}
)
# Block size for the vectorised silence scan; ~43 ms at 24 kHz.
_SCAN_BLOCK_SAMPLES = 1024


def _ends_with_abbreviation(text: str) -> bool:
    """Return True when text ends with a known abbreviation (without the dot)."""
    stripped = text.rstrip()
    if not stripped:
        return False
    last_word = stripped.rsplit(maxsplit=1)[-1]
    return last_word.lower() in _ABBREVIATIONS


def _find_sentence_end(buffer: str, *, at_end: bool) -> int | None:
    """Return the index just past the first sentence terminator, or None.

    When ``at_end`` is False (streaming) a terminator must be followed by
    whitespace so a partial "It is 21." is not split before the "5" arrives.
    """
    pattern = _SENTENCE_END_RE if at_end else _SENTENCE_END_STREAMING_RE
    for match in pattern.finditer(buffer):
        if _ends_with_abbreviation(buffer[: match.start()]):
            continue
        return match.end()
    return None


def iter_sentences(text: str) -> list[str]:
    """Split complete text into sentences (decimal and abbreviation aware)."""
    sentences: list[str] = []
    remainder = text
    while remainder:
        end = _find_sentence_end(remainder, at_end=True)
        if end is None:
            tail = remainder.strip()
            if tail:
                sentences.append(tail)
            break
        sentence = remainder[:end].strip()
        if sentence:
            sentences.append(sentence)
        remainder = remainder[end:]
    return sentences


def sanitize_for_tts(text: str) -> str:
    """Strip markdown and other non-speakable content."""
    cleaned = str(text or "")
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*•→▪]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\d+[.)]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"https?://\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\|{2,}", " ", cleaned)
    cleaned = cleaned.replace("\u2013", " ").replace("\u2014", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def split_for_tts(text: str, max_len: int = MAX_CHUNK_LEN) -> list[str]:
    """Split text into speakable chunks, preferring sentence boundaries."""
    if not text:
        return []

    chunks: list[str] = []

    for sentence in iter_sentences(text):
        if len(sentence) <= max_len:
            chunks.append(sentence)
            continue

        pattern = re.compile(
            rf".{{1,{max_len}}}(?:\s|$)|.{{1,{max_len}}}",
        )
        for part in pattern.findall(sentence):
            trimmed = part.strip()
            if trimmed:
                chunks.append(trimmed)

    return chunks


def pop_complete_sentence(
    buffer: str, *, at_end: bool = False
) -> tuple[str | None, str]:
    """Pop the first complete sentence from the front of a buffer.

    Pass ``at_end=True`` once the text stream is finished so a trailing
    terminator without following whitespace also counts as a sentence end.
    """
    end = _find_sentence_end(buffer, at_end=at_end)
    if end is None:
        return None, buffer
    sentence = buffer[:end].strip()
    if not sentence:
        return None, buffer[end:]
    return sentence, buffer[end:]


def pop_early_chunk(buffer: str, min_chars: int) -> tuple[str | None, str]:
    """Pop a speakable prefix once the buffer reaches min_chars."""
    plain = buffer.lstrip()
    text = plain.rstrip()
    if len(text) < min_chars:
        return None, buffer

    break_at = min_chars
    if len(text) > min_chars:
        space = text.rfind(" ", 0, min(min_chars + 30, len(text)))
        if space >= min_chars // 2:
            break_at = space

    chunk = text[:break_at].strip()
    if not chunk:
        return None, buffer
    # Slice the un-rstripped text so trailing whitespace survives; otherwise
    # the next streamed delta glues onto the last word ("kitchen" + "lights").
    remainder = plain[break_at:].lstrip()
    return chunk, remainder


def is_wav(audio_bytes: bytes) -> bool:
    """Return True when audio_bytes contains a WAV container."""
    return (
        len(audio_bytes) >= 12
        and audio_bytes[:4] == b"RIFF"
        and audio_bytes[8:12] == b"WAVE"
    )


def pcm_to_wav(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int = 1,
    bit_rate: int = 16,
) -> bytes:
    """Wrap raw PCM samples in a WAV container."""
    if bit_rate != 16:
        raise ValueError("Only 16-bit PCM is supported for ASR")
    if channels < 1:
        raise ValueError("At least one channel is required")

    bytes_per_sample = bit_rate // 8
    block_align = channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bit_rate,
        b"data",
        data_size,
    )
    return header + pcm


def read_sample_rate(wav_bytes: bytes) -> int:
    """Read the sample rate from a WAV header."""
    offset = 12
    while offset + 8 <= len(wav_bytes):
        chunk_id = wav_bytes[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
        if chunk_id == b"fmt ":
            return struct.unpack_from("<I", wav_bytes, offset + 12)[0]
        offset += 8 + chunk_size
    return DEFAULT_SAMPLE_RATE


def extract_pcm(wav_bytes: bytes) -> bytes:
    """Extract PCM data from a WAV file."""
    offset = 12
    while offset + 8 <= len(wav_bytes):
        chunk_id = wav_bytes[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
        if chunk_id == b"data":
            return wav_bytes[offset + 8 : offset + 8 + chunk_size]
        offset += 8 + chunk_size
    return wav_bytes[44:]


def trim_pcm_silence(
    pcm: bytes,
    sample_rate: int,
    *,
    threshold: int = SILENCE_THRESHOLD,
    keep_edge_ms: int = KEEP_EDGE_MS,
) -> bytes:
    """Trim leading and trailing silence while keeping a short edge."""
    if not pcm:
        return pcm

    keep_edge_samples = max(1, (sample_rate * keep_edge_ms) // 1000)
    num_samples = len(pcm) // 2
    if num_samples == 0:
        return pcm

    samples = _pcm16_to_samples(pcm[: num_samples * 2])
    first = _first_loud_index(samples, threshold)
    if first is None:
        return pcm
    last = _last_loud_index(samples, threshold)
    if last is None:
        return pcm

    start = max(0, first - keep_edge_samples)
    end = min(num_samples - 1, last + keep_edge_samples)
    if start >= end:
        return pcm

    return pcm[start * 2 : (end + 1) * 2]


def _pcm16_to_samples(pcm: bytes) -> array:
    """Decode little-endian 16-bit PCM into a signed-short array."""
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _first_loud_index(samples: array, threshold: int) -> int | None:
    """Return the first sample index above threshold using block scanning.

    ``max(map(abs, block))`` runs in C, so this is roughly two orders of
    magnitude faster than a per-sample Python loop on multi-second clips.
    """
    total = len(samples)
    for block_start in range(0, total, _SCAN_BLOCK_SAMPLES):
        block = samples[block_start : block_start + _SCAN_BLOCK_SAMPLES]
        if max(map(abs, block)) <= threshold:
            continue
        for offset, value in enumerate(block):
            if abs(value) > threshold:
                return block_start + offset
    return None


def _last_loud_index(samples: array, threshold: int) -> int | None:
    """Return the last sample index above threshold using block scanning."""
    total = len(samples)
    block_start = ((total - 1) // _SCAN_BLOCK_SAMPLES) * _SCAN_BLOCK_SAMPLES
    while block_start >= 0:
        block = samples[block_start : block_start + _SCAN_BLOCK_SAMPLES]
        if max(map(abs, block)) > threshold:
            for offset in range(len(block) - 1, -1, -1):
                if abs(block[offset]) > threshold:
                    return block_start + offset
        block_start -= _SCAN_BLOCK_SAMPLES
    return None


def pcm_has_signal(
    pcm: bytes, *, threshold: int = SILENCE_THRESHOLD
) -> bool:
    """Return True when any 16-bit sample exceeds the silence threshold."""
    if len(pcm) < 2:
        return False
    samples = _pcm16_to_samples(pcm[: len(pcm) - (len(pcm) % 2)])
    return _first_loud_index(samples, threshold) is not None


def make_silence_pcm(sample_rate: int, ms: int) -> bytes:
    """Create silent PCM data."""
    samples = max(0, (sample_rate * ms) // 1000)
    return bytes(samples * 2)


def rebuild_wav(template_wav: bytes, pcm: bytes) -> bytes:
    """Rebuild a WAV file using PCM from another buffer."""
    header = bytearray(template_wav)
    offset = 12
    while offset + 8 <= len(header):
        chunk_id = header[offset : offset + 4]
        if chunk_id == b"data":
            header_end = offset + 8
            output = bytes(header[:header_end]) + pcm
            output = bytearray(output)
            struct.pack_into("<I", output, 4, len(output) - 8)
            struct.pack_into("<I", output, offset + 4, len(pcm))
            return bytes(output)
        chunk_size = struct.unpack_from("<I", header, offset + 4)[0]
        offset += 8 + chunk_size

    return bytes(header[:44]) + pcm


def concat_wav_buffers(
    buffers: list[bytes],
    *,
    chunk_gap_ms: int = CHUNK_GAP_MS,
    keep_edge_ms: int = KEEP_EDGE_MS,
    threshold: int = SILENCE_THRESHOLD,
) -> bytes:
    """Merge multiple WAV buffers into one file."""
    if not buffers:
        raise ValueError("No WAV buffers to concatenate")

    if len(buffers) == 1:
        sample_rate = read_sample_rate(buffers[0])
        trimmed = trim_pcm_silence(
            extract_pcm(buffers[0]),
            sample_rate,
            threshold=threshold,
            keep_edge_ms=keep_edge_ms,
        )
        return rebuild_wav(buffers[0], trimmed)

    sample_rate = read_sample_rate(buffers[0])
    gap_pcm = make_silence_pcm(sample_rate, chunk_gap_ms)
    pcm_parts: list[bytes] = []

    for index, buffer in enumerate(buffers):
        pcm_parts.append(
            trim_pcm_silence(
                extract_pcm(buffer),
                sample_rate,
                threshold=threshold,
                keep_edge_ms=keep_edge_ms,
            )
        )
        if index < len(buffers) - 1:
            pcm_parts.append(gap_pcm)

    return rebuild_wav(buffers[0], b"".join(pcm_parts))
