"""Constants for the LiquidAI integration."""

from logging import Logger, getLogger

DOMAIN = "ha_liquidai_custom"

CONF_BASE_URL = "base_url"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_ASR_SYSTEM_PROMPT = "asr_system_prompt"
CONF_TIMEOUT = "timeout"
CONF_SPEAKER_EMBED_ENABLED = "speaker_embed_enabled"
CONF_SPEAKER_EMBED_TIMEOUT = "speaker_embed_timeout"

CONF_MAX_CHUNK_LEN = "max_chunk_len"
CONF_KEEP_EDGE_MS = "keep_edge_ms"
CONF_CHUNK_GAP_MS = "chunk_gap_ms"
CONF_SILENCE_THRESHOLD = "silence_threshold"
CONF_SPEECH_SPEED = "speech_speed"
CONF_STREAM_FIRST_CHUNK_CHARS = "stream_first_chunk_chars"

DEFAULT_URL = "http://192.168.10.31:8811"
DEFAULT_SYSTEM_PROMPT = "Perform TTS. Use the US female voice."
DEFAULT_ASR_SYSTEM_PROMPT = "Perform ASR."
DEFAULT_TIMEOUT = 120
DEFAULT_SPEAKER_EMBED_ENABLED = True
DEFAULT_SPEAKER_EMBED_TIMEOUT = 15

VOICE_TURN_TTL_SECONDS = 5.0
VOICE_TURN_MATCH_WINDOW_SECONDS = 2.0
SPEAKER_EMBED_GRACE_SECONDS = 3.0
DATA_EMBED_UNAVAILABLE = "ha_liquidai_embed_unavailable"
EMBED_SOFT_QUALITIES = frozenset({"too_short", "noisy", "error"})

MAX_CHUNK_LEN = 160
KEEP_EDGE_MS = 100
CHUNK_GAP_MS = 5
SILENCE_THRESHOLD = 350
DEFAULT_SPEECH_SPEED = 1.0
MIN_SPEECH_SPEED = 0.75
MAX_SPEECH_SPEED = 1.5
STREAM_FIRST_CHUNK_CHARS = 15
DEFAULT_SAMPLE_RATE = 24000

SUPPORTED_LANGUAGES = ["en", "en-US"]
DEFAULT_LANGUAGE = "en-US"

LOGGER: Logger = getLogger(__package__)
