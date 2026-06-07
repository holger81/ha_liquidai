"""Text cleanup and WAV/PCM helpers ported from ha_liquidai_n8n."""

from __future__ import annotations

import re
import struct

from .const import (
    CHUNK_GAP_MS,
    DEFAULT_SAMPLE_RATE,
    KEEP_EDGE_MS,
    MAX_CHUNK_LEN,
    SILENCE_THRESHOLD,
)

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
_COMPLETE_SENTENCE_RE = re.compile(r"^\s*([^.!?]+[.!?]+)")


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

    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_RE.findall(text)
        if sentence.strip()
    ]
    chunks: list[str] = []

    for sentence in sentences:
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


def pop_complete_sentence(buffer: str) -> tuple[str | None, str]:
    """Pop the first complete sentence from the front of a buffer."""
    match = _COMPLETE_SENTENCE_RE.match(buffer)
    if not match:
        return None, buffer
    sentence = match.group(1).strip()
    return sentence, buffer[match.end() :]


def pop_early_chunk(buffer: str, min_chars: int) -> tuple[str | None, str]:
    """Pop a speakable prefix once the buffer reaches min_chars."""
    plain = buffer.strip()
    if len(plain) < min_chars:
        return None, buffer

    break_at = min_chars
    if len(plain) > min_chars:
        space = plain.rfind(" ", 0, min(min_chars + 30, len(plain)))
        if space >= min_chars // 2:
            break_at = space

    chunk = plain[:break_at].strip()
    remainder = plain[break_at:].lstrip()
    if not chunk:
        return None, buffer
    return chunk, remainder


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

    def sample_at(index: int) -> int:
        offset = index * 2
        value = pcm[offset] | (pcm[offset + 1] << 8)
        return value - 65536 if value > 32767 else value

    start = 0
    end = num_samples - 1

    for index in range(num_samples):
        if abs(sample_at(index)) > threshold:
            start = max(0, index - keep_edge_samples)
            break

    for index in range(num_samples - 1, -1, -1):
        if abs(sample_at(index)) > threshold:
            end = min(num_samples - 1, index + keep_edge_samples)
            break

    if start >= end:
        return pcm

    return pcm[start * 2 : (end + 1) * 2]


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
