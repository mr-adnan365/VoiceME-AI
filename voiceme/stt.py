"""Speech to text with faster-whisper, running locally on CPU or GPU."""

from __future__ import annotations

import io
import logging
import threading
from pathlib import Path

log = logging.getLogger("voiceme.stt")


class Transcriber:
    def __init__(
        self,
        model: str,
        download_dir: Path,
        device: str = "auto",
        compute_type: str = "int8",
        language: str | None = "en",
    ) -> None:
        self.model_name = model
        self.language = language
        self._download_dir = download_dir
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model, downloading it on first use (about 150 MB for base.en)."""
        from faster_whisper import WhisperModel  # imported lazily: it is a heavy import

        log.info("Loading Whisper model '%s' (first run downloads it)...", self.model_name)
        self._model = WhisperModel(
            self.model_name,
            device=self._device,
            compute_type=self._compute_type,
            download_root=str(self._download_dir),
        )
        log.info("Whisper ready.")

    def transcribe(self, audio: bytes) -> str:
        """Turn a recording (webm, ogg, mp4, wav...) into text. Blocking; run in a thread."""
        if self._model is None:
            raise RuntimeError("Transcriber.load() has not been called")
        with self._lock:
            segments, _info = self._model.transcribe(
                io.BytesIO(audio),
                language=self.language,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
