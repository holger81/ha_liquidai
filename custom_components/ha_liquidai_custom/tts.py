"""LiquidAI TTS entity."""

from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components import ffmpeg
from homeassistant.components.tts import (
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
    TtsAudioType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audio import (
    concat_wav_buffers,
    extract_pcm,
    make_silence_pcm,
    pcm_has_signal,
    pcm_to_wav,
    pop_complete_sentence,
    pop_early_chunk,
    read_sample_rate,
    rebuild_wav,
    sanitize_for_tts,
    split_for_tts,
    trim_leading_pcm_silence,
    trim_pcm_silence,
)
from .client import LiquidAiClient
from .const import (
    CHUNK_GAP_MS,
    CONF_BASE_URL,
    CONF_CHUNK_GAP_MS,
    CONF_KEEP_EDGE_MS,
    CONF_MAX_CHUNK_LEN,
    CONF_SILENCE_THRESHOLD,
    CONF_SPEECH_SPEED,
    CONF_STREAM_FIRST_CHUNK_CHARS,
    CONF_STREAM_PCM,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_LANGUAGE,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SPEECH_SPEED,
    DEFAULT_STREAM_PCM,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    KEEP_EDGE_MS,
    LOGGER,
    MAX_CHUNK_LEN,
    SILENCE_THRESHOLD,
    STREAM_FIRST_CHUNK_CHARS,
    SUPPORTED_LANGUAGES,
    TTS_MAX_CONCURRENT_REQUESTS,
    TTS_PCM_FIRST_MP3_BYTES,
    TTS_PCM_MP3_BITRATE_K,
    TTS_PCM_PREAMBLE_MS,
)

# HA converts TTS to mp3 for playback; raw pcm breaks ffmpeg conversion.
STREAM_EXTENSION = "mp3"
ONESHOT_EXTENSION = "wav"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LiquidAI TTS from a config entry."""
    async_add_entities([LiquidAiTtsEntity(hass, config_entry)])


class LiquidAiTtsEntity(TextToSpeechEntity):
    """LiquidAI text-to-speech provider."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the TTS entity."""
        self._entry = entry
        self._client = LiquidAiClient(
            async_get_clientsession(hass),
            entry.data[CONF_BASE_URL],
            system_prompt=entry.data.get(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT),
            timeout=entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        )
        self._synth_semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENT_REQUESTS)
        # Encoded inter-sentence silence, keyed by (sample_rate, gap_ms, speed).
        self._gap_mp3_cache: dict[tuple[int, int, float], bytes] = {}
        # Silent keepalive MP3, keyed by (sample_rate, speed, preamble_ms).
        self._preamble_mp3_cache: dict[tuple[int, float, int], bytes] = {}
        self._attr_name = "LiquidAI TTS"
        self._attr_unique_id = entry.entry_id
        self._attr_supported_languages = SUPPORTED_LANGUAGES
        self._attr_default_language = DEFAULT_LANGUAGE

    @property
    def max_chunk_len(self) -> int:
        """Return the maximum chunk length."""
        return int(self._entry.options.get(CONF_MAX_CHUNK_LEN, MAX_CHUNK_LEN))

    @property
    def keep_edge_ms(self) -> int:
        """Return PCM edge padding in milliseconds."""
        return int(self._entry.options.get(CONF_KEEP_EDGE_MS, KEEP_EDGE_MS))

    @property
    def chunk_gap_ms(self) -> int:
        """Return silence gap between streamed sentences."""
        return int(self._entry.options.get(CONF_CHUNK_GAP_MS, CHUNK_GAP_MS))

    @property
    def silence_threshold(self) -> int:
        """Return PCM silence threshold."""
        return int(
            self._entry.options.get(CONF_SILENCE_THRESHOLD, SILENCE_THRESHOLD)
        )

    @property
    def stream_first_chunk_chars(self) -> int:
        """Return minimum chars before the first streaming TTS chunk."""
        return int(
            self._entry.options.get(
                CONF_STREAM_FIRST_CHUNK_CHARS, STREAM_FIRST_CHUNK_CHARS
            )
        )

    @property
    def speech_speed(self) -> float:
        """Return playback speed multiplier (1.0 = normal)."""
        return float(
            self._entry.options.get(CONF_SPEECH_SPEED, DEFAULT_SPEECH_SPEED)
        )

    @property
    def stream_pcm(self) -> bool:
        """Return True when Assist TTS should stream PCM from /ws-audio."""
        return bool(self._entry.options.get(CONF_STREAM_PCM, DEFAULT_STREAM_PCM))

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Synthesize one-shot TTS audio."""
        plain_text = sanitize_for_tts(message) or " ".join(message.split())
        if not plain_text:
            return None, None

        chunks = split_for_tts(plain_text, self.max_chunk_len)
        if not chunks:
            return None, None

        if len(chunks) == 1:
            wav = await self._client.synthesize(chunks[0])
            trimmed = await self._run_blocking(self._trimmed_wav, wav)
            return ONESHOT_EXTENSION, await self._maybe_adjust_wav_speed(trimmed)

        # Bounded concurrency: the server runs a single model, so flooding it
        # with every chunk at once only queues requests and risks timeouts.
        wav_buffers = await asyncio.gather(
            *(self._synthesize_limited(chunk) for chunk in chunks)
        )
        merged = await self._run_blocking(
            concat_wav_buffers,
            list(wav_buffers),
            chunk_gap_ms=self.chunk_gap_ms,
            keep_edge_ms=self.keep_edge_ms,
            threshold=self.silence_threshold,
        )
        return ONESHOT_EXTENSION, await self._maybe_adjust_wav_speed(merged)

    async def _synthesize_limited(self, text: str) -> bytes:
        """Synthesize while holding the concurrency semaphore."""
        async with self._synth_semaphore:
            return await self._client.synthesize(text)

    async def _run_blocking(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run CPU-bound PCM work off the event loop."""
        if kwargs:
            return await self.hass.async_add_executor_job(
                functools.partial(func, *args, **kwargs)
            )
        return await self.hass.async_add_executor_job(func, *args)

    async def async_stream_tts_audio(
        self, request: TTSAudioRequest
    ) -> TTSAudioResponse:
        """Stream TTS audio sentence by sentence."""
        return TTSAudioResponse(
            STREAM_EXTENSION,
            self._audio_gen(request),
        )

    async def _audio_gen(
        self, request: TTSAudioRequest
    ) -> AsyncGenerator[bytes, None]:
        """Yield mp3 chunks for each completed sentence."""
        if self.stream_pcm:
            async for chunk in self._audio_gen_pcm(request):
                yield chunk
            return
        async for chunk in self._audio_gen_http(request):
            yield chunk

    async def _audio_gen_http(
        self, request: TTSAudioRequest
    ) -> AsyncGenerator[bytes, None]:
        """HTTP path: wait for each full WAV, prefetch the next sentence."""
        sentence_iter = self._message_to_sentences(request.message_gen).__aiter__()
        template_wav: bytes | None = None
        sample_rate: int | None = None

        async def pull_sentence() -> str | None:
            try:
                return await sentence_iter.__anext__()
            except StopAsyncIteration:
                return None

        first = await pull_sentence()
        if first is None:
            return

        pending_synth: asyncio.Task[bytes] | None = asyncio.create_task(
            self._client.synthesize(first)
        )

        while pending_synth is not None:
            # Buffer the next segment while LiquidAI synthesizes the current one.
            next_sentence_task = asyncio.create_task(pull_sentence())
            wav = await pending_synth

            if template_wav is None:
                template_wav = wav
                sample_rate = read_sample_rate(wav)

            mp3_task = asyncio.create_task(self._trim_and_encode(wav))
            next_sentence = await next_sentence_task
            pending_synth = (
                asyncio.create_task(self._client.synthesize(next_sentence))
                if next_sentence is not None
                else None
            )

            mp3 = await mp3_task
            if mp3:
                yield mp3

            if (
                pending_synth is not None
                and self.chunk_gap_ms > 0
                and sample_rate is not None
                and template_wav is not None
            ):
                gap_mp3 = await self._gap_mp3(template_wav, sample_rate)
                if gap_mp3:
                    yield gap_mp3

    async def _audio_gen_pcm(
        self, request: TTSAudioRequest
    ) -> AsyncGenerator[bytes, None]:
        """WebSocket path: yield MP3 slices as PCM frames arrive per sentence."""
        # Keepalive: Assist satellites often time out if the HTTP body stays
        # empty while the LLM produces the first sentence / Liquid warms up.
        preamble = await self._silent_mp3_preamble()
        if preamble:
            yield preamble

        sample_rate = DEFAULT_SAMPLE_RATE
        template_wav = pcm_to_wav(b"\x00\x00", sample_rate=sample_rate)
        first_sentence = True

        async for sentence in self._message_to_sentences(request.message_gen):
            if not first_sentence and self.chunk_gap_ms > 0:
                gap_mp3 = await self._gap_mp3(template_wav, sample_rate)
                if gap_mp3:
                    yield gap_mp3
            first_sentence = False

            yielded = False
            try:
                async for mp3 in self._stream_sentence_mp3(sentence):
                    yielded = True
                    yield mp3
            except HomeAssistantError as err:
                if yielded:
                    # Avoid re-synthesizing a sentence the satellite already started.
                    LOGGER.warning(
                        "PCM stream failed mid-sentence after playback started: %s",
                        err,
                    )
                    raise
                LOGGER.warning(
                    "PCM stream failed for sentence, falling back to HTTP: %s",
                    err,
                )
                wav = await self._client.synthesize(sentence)
                sample_rate = read_sample_rate(wav)
                template_wav = wav
                mp3 = await self._trim_and_encode(wav)
                if mp3:
                    yield mp3

    async def _stream_sentence_mp3(
        self, text: str
    ) -> AsyncGenerator[bytes, None]:
        """Yield MP3 as PCM arrives, using one continuous ffmpeg encode.

        HA concatenates yielded chunks into one media stream. Separate MP3
        *files* per slice (each with its own encoder delay) click/warble when
        joined. A single ffmpeg process fed raw s16le PCM produces one
        continuous MP3 bitstream that can be yielded in fragments safely.
        """
        pcm_agen = self._client.synthesize_pcm_stream(text).__aiter__()
        pending: bytearray = bytearray()
        sample_rate = DEFAULT_SAMPLE_RATE
        max_leading = DEFAULT_SAMPLE_RATE * 2 * 2

        # Wait for speech before starting the encoder (skip model lead-in).
        while True:
            try:
                pcm, sample_rate = await pcm_agen.__anext__()
            except StopAsyncIteration:
                return
            max_leading = sample_rate * 2 * 2
            pending.extend(pcm)
            if pcm_has_signal(bytes(pending), threshold=self.silence_threshold):
                pending = bytearray(
                    trim_leading_pcm_silence(
                        bytes(pending),
                        sample_rate,
                        threshold=self.silence_threshold,
                        keep_edge_ms=self.keep_edge_ms,
                    )
                )
                break
            if len(pending) >= max_leading:
                pending.clear()

        # int16 alignment — odd lengths corrupt the encoder mid-stream.
        if len(pending) & 1:
            pending = pending[:-1]

        process = await self._spawn_pcm_mp3_encoder(sample_rate)
        assert process.stdin is not None
        assert process.stdout is not None

        async def _write_pcm() -> None:
            try:
                if pending:
                    process.stdin.write(bytes(pending))
                    await process.stdin.drain()
                async for pcm, _sr in pcm_agen:
                    if not pcm:
                        continue
                    if len(pcm) & 1:
                        pcm = pcm[:-1]
                    if pcm:
                        process.stdin.write(pcm)
                        await process.stdin.drain()
            finally:
                process.stdin.close()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await process.stdin.wait_closed()

        writer = asyncio.create_task(_write_pcm())
        first_buf = bytearray()
        yielded = False
        try:
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                if not yielded:
                    first_buf.extend(chunk)
                    if len(first_buf) < TTS_PCM_FIRST_MP3_BYTES:
                        continue
                    yield bytes(first_buf)
                    first_buf.clear()
                    yielded = True
                else:
                    yield chunk
            if first_buf:
                yield bytes(first_buf)
                yielded = True
            await writer
            stderr = (
                await process.stderr.read() if process.stderr is not None else b""
            )
            code = await process.wait()
            if code:
                detail = stderr.decode(errors="replace").strip()
                raise HomeAssistantError(
                    f"ffmpeg PCM→MP3 stream failed: {detail or code}"
                )
            if not yielded:
                raise HomeAssistantError("ffmpeg PCM→MP3 stream returned no audio")
        except Exception:
            if not writer.done():
                writer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await writer
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            raise

    async def _spawn_pcm_mp3_encoder(
        self, sample_rate: int
    ) -> asyncio.subprocess.Process:
        """Start ffmpeg reading raw s16le mono PCM and writing an MP3 stream."""
        ffmpeg_manager = ffmpeg.get_ffmpeg_manager(self.hass)
        command = [
            ffmpeg_manager.binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-i",
            "pipe:0",
        ]
        if self.speech_speed != 1.0:
            command.extend(["-filter:a", f"atempo={self.speech_speed}"])
        # CBR: Assist satellites / some HA transcoder paths fail intermittently
        # on VBR (-q:a). flush_packets keeps time-to-first-audio low.
        command.extend(
            [
                "-f",
                "mp3",
                "-b:a",
                f"{TTS_PCM_MP3_BITRATE_K}k",
                "-flush_packets",
                "1",
                "pipe:1",
            ]
        )
        return await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _trim_and_encode(self, wav: bytes) -> bytes:
        """Trim silence (off-loop) and encode the sentence to MP3."""
        trimmed = await self._run_blocking(self._trimmed_wav, wav)
        return await self._convert_wav_to_mp3(trimmed, streaming=True)

    async def _gap_mp3(self, template_wav: bytes, sample_rate: int) -> bytes:
        """Return the encoded inter-sentence gap, encoding it only once."""
        key = (sample_rate, self.chunk_gap_ms, self.speech_speed)
        cached = self._gap_mp3_cache.get(key)
        if cached is not None:
            return cached
        gap_wav = rebuild_wav(
            template_wav,
            make_silence_pcm(sample_rate, self.chunk_gap_ms),
        )
        gap_mp3 = await self._convert_wav_to_mp3(gap_wav, streaming=True)
        self._gap_mp3_cache[key] = gap_mp3
        return gap_mp3

    async def _silent_mp3_preamble(self) -> bytes:
        """Return a short silent MP3 used to open the Assist media stream."""
        key = (DEFAULT_SAMPLE_RATE, self.speech_speed, TTS_PCM_PREAMBLE_MS)
        cached = self._preamble_mp3_cache.get(key)
        if cached is not None:
            return cached
        wav = pcm_to_wav(
            make_silence_pcm(DEFAULT_SAMPLE_RATE, TTS_PCM_PREAMBLE_MS),
            sample_rate=DEFAULT_SAMPLE_RATE,
        )
        mp3 = await self._convert_wav_to_mp3(wav, streaming=True)
        self._preamble_mp3_cache[key] = mp3
        return mp3

    def _trimmed_wav(self, wav: bytes) -> bytes:
        """Return a trimmed WAV buffer."""
        sample_rate = read_sample_rate(wav)
        trimmed = trim_pcm_silence(
            extract_pcm(wav),
            sample_rate,
            threshold=self.silence_threshold,
            keep_edge_ms=self.keep_edge_ms,
        )
        if not trimmed:
            return b""
        return rebuild_wav(wav, trimmed)

    async def _maybe_adjust_wav_speed(self, wav: bytes) -> bytes:
        """Apply speech speed to WAV bytes when configured."""
        if not wav or self.speech_speed == 1.0:
            return wav
        return await self._ffmpeg_wav(wav, output_format="wav")

    async def _convert_wav_to_mp3(
        self, wav: bytes, *, streaming: bool = False
    ) -> bytes:
        """Convert WAV bytes to MP3 using Home Assistant ffmpeg."""
        if not wav:
            return b""
        return await self._ffmpeg_wav(wav, output_format="mp3", streaming=streaming)

    async def _ffmpeg_wav(
        self,
        wav: bytes,
        *,
        output_format: str,
        streaming: bool = False,
    ) -> bytes:
        """Run ffmpeg on WAV bytes (speed, optional MP3 encode)."""
        ffmpeg_manager = ffmpeg.get_ffmpeg_manager(self.hass)
        command = [
            ffmpeg_manager.binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
        ]
        if self.speech_speed != 1.0:
            command.extend(["-filter:a", f"atempo={self.speech_speed}"])
        command.extend(["-f", output_format])
        if output_format == "mp3":
            command.extend(["-q:a", "2" if streaming else "0"])
        command.append("pipe:1")
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(wav)
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise HomeAssistantError(
                f"ffmpeg {output_format} conversion failed: {detail}"
            )
        if not stdout:
            raise HomeAssistantError(
                f"ffmpeg {output_format} conversion returned empty audio"
            )
        return stdout

    async def _message_to_sentences(
        self, message_gen: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """Convert a text stream into speakable sentences."""
        buffer = ""
        first_chunk_sent = False
        min_early = self.stream_first_chunk_chars

        async for delta in message_gen:
            buffer += delta
            while True:
                sentence, buffer = pop_complete_sentence(buffer)
                if sentence is None:
                    break
                plain = sanitize_for_tts(sentence)
                if plain:
                    first_chunk_sent = True
                    LOGGER.debug("Streaming sentence (%d chars)", len(plain))
                    yield plain

            if not first_chunk_sent and min_early > 0:
                early, buffer = pop_early_chunk(buffer, min_early)
                if early:
                    plain = sanitize_for_tts(early)
                    if plain:
                        first_chunk_sent = True
                        LOGGER.debug(
                            "Streaming early chunk (%d chars)", len(plain)
                        )
                        yield plain

        while True:
            sentence, buffer = pop_complete_sentence(buffer, at_end=True)
            if sentence is None:
                break
            plain = sanitize_for_tts(sentence)
            if plain:
                LOGGER.debug("Streaming sentence (%d chars)", len(plain))
                yield plain

        tail = sanitize_for_tts(buffer.strip())
        if tail:
            LOGGER.debug("Streaming tail sentence (%d chars)", len(tail))
            yield tail
