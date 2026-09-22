"""Runtime settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

DEFAULT_SYSTEM_PROMPT = (
    "You are VoiceMe, a friendly voice assistant. Everything you write is spoken "
    "aloud, so answer in one to three short sentences of plain conversational "
    "English. Never use markdown, bullet points, emojis, or code blocks. "
    "If you don't know something, say so briefly."
)


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from ``path`` into ``os.environ`` without overriding."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Web server
    host: str = "127.0.0.1"
    port: int = 8000

    # Speech to text (faster-whisper)
    whisper_model: str = "base.en"
    whisper_device: str = "auto"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = "en"

    # Language model (Ollama)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "phi4-mini"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 200
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # Text to speech (Piper)
    piper_voice: str = "en_US-lessac-medium"

    # Storage and limits
    models_dir: Path = ROOT / "models"
    max_history_turns: int = 8
    max_audio_mb: int = 15

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(ROOT / ".env")
        env = os.environ.get
        language = env("WHISPER_LANGUAGE", "en").strip()
        return cls(
            host=env("VOICEME_HOST", cls.host),
            port=_int("VOICEME_PORT", cls.port),
            whisper_model=env("WHISPER_MODEL", cls.whisper_model),
            whisper_device=env("WHISPER_DEVICE", cls.whisper_device),
            whisper_compute_type=env("WHISPER_COMPUTE_TYPE", cls.whisper_compute_type),
            whisper_language=None if language.lower() in {"", "auto"} else language,
            ollama_url=env("OLLAMA_URL", cls.ollama_url).rstrip("/"),
            ollama_model=env("OLLAMA_MODEL", cls.ollama_model),
            llm_temperature=_float("LLM_TEMPERATURE", cls.llm_temperature),
            llm_max_tokens=_int("LLM_MAX_TOKENS", cls.llm_max_tokens),
            system_prompt=env("VOICEME_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
            piper_voice=env("PIPER_VOICE", cls.piper_voice),
            models_dir=Path(env("VOICEME_MODELS_DIR", str(cls.models_dir))),
            max_history_turns=_int("MAX_HISTORY_TURNS", cls.max_history_turns),
            max_audio_mb=_int("MAX_AUDIO_MB", cls.max_audio_mb),
        )
