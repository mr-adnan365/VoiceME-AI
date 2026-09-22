"""Text to speech with Piper (https://github.com/OHF-Voice/piper1-gpl), fully offline."""

from __future__ import annotations

import io
import logging
import threading
import wave
from pathlib import Path

log = logging.getLogger("voiceme.tts")


def ensure_voice(voice: str, voices_dir: Path) -> Path:
    """Return the path to a Piper voice model, downloading it the first time."""
    model_path = voices_dir / f"{voice}.onnx"
    config_path = voices_dir / f"{voice}.onnx.json"
    if model_path.is_file() and config_path.is_file():
        return model_path

    from piper.download_voices import download_voice

    log.info("Downloading Piper voice '%s' (about 60 MB)...", voice)
    voices_dir.mkdir(parents=True, exist_ok=True)
    try:
        download_voice(voice, voices_dir)
    except Exception as exc:  # network errors, unknown voice names, ...
        raise RuntimeError(
            f"Couldn't download the Piper voice '{voice}': {exc}. "
            "Check your connection and the PIPER_VOICE name."
        ) from exc
    return model_path


class Speaker:
    def __init__(self, voice: str, voices_dir: Path) -> None:
        self.voice_name = voice
        self._voices_dir = voices_dir
        self._voice = None
        self._lock = threading.Lock()

    def load(self) -> None:
        from piper import PiperVoice  # imported lazily: it pulls in onnxruntime

        model_path = ensure_voice(self.voice_name, self._voices_dir)
        self._voice = PiperVoice.load(model_path)
        log.info("Piper voice '%s' ready.", self.voice_name)

    def synthesize(self, text: str) -> bytes:
        """Return a complete WAV file for ``text``. Blocking; run in a thread."""
        if self._voice is None:
            raise RuntimeError("Speaker.load() has not been called")
        buffer = io.BytesIO()
        with self._lock, wave.open(buffer, "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)
        return buffer.getvalue()
