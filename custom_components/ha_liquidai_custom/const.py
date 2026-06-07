"""Constants for the LiquidAI TTS integration."""

from logging import Logger, getLogger

DOMAIN = "ha_liquidai_custom"

CONF_BASE_URL = "base_url"
CONF_SYSTEM_PROMPT = "system_prompt"
CONF_TIMEOUT = "timeout"
CONF_MAX_CHUNK_LEN = "max_chunk_len"
CONF_KEEP_EDGE_MS = "keep_edge_ms"
CONF_CHUNK_GAP_MS = "chunk_gap_ms"
CONF_SILENCE_THRESHOLD = "silence_threshold"
CONF_STREAM_FIRST_CHUNK_CHARS = "stream_first_chunk_chars"

DEFAULT_URL = "http://192.168.10.31:8811"
DEFAULT_SYSTEM_PROMPT = "Perform TTS. Use the US female voice."
DEFAULT_TIMEOUT = 120
MAX_CHUNK_LEN = 160
KEEP_EDGE_MS = 100
CHUNK_GAP_MS = 5
SILENCE_THRESHOLD = 350
STREAM_FIRST_CHUNK_CHARS = 40
DEFAULT_SAMPLE_RATE = 24000

SUPPORTED_LANGUAGES = ["en", "en-US"]
DEFAULT_LANGUAGE = "en-US"

LOGGER: Logger = getLogger(__package__)
