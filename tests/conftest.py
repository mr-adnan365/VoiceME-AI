"""Lightweight stand-ins for Whisper, Ollama and Piper so tests run anywhere, fast."""

from __future__ import annotations

import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from voiceme.config import Settings
from voiceme.llm import LLMError, LLMStatus
from voiceme.main import create_app


def tiny_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * 220)
    return buffer.getvalue()


class FakeTranscriber:
    model_name = "fake-whisper"

    def __init__(self, text: str = "what is two plus two") -> None:
        self.text = text
        self.received: list[bytes] = []

    def load(self) -> None:
        pass

    def transcribe(self, audio: bytes) -> str:
        self.received.append(audio)
        return self.text


class FakeSpeaker:
    voice_name = "fake-voice"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def load(self) -> None:
        pass

    def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return tiny_wav()


class FakeLLM:
    def __init__(self, pieces=None, error: str | None = None, ready: bool = True) -> None:
        self.pieces = pieces or ["Two plus two ", "is four. ", "Anything else?"]
        self.error = error
        self.ready = ready
        self.calls: list[list[dict[str, str]]] = []

    async def status(self) -> LLMStatus:
        if self.ready:
            return LLMStatus(True, "fake-model")
        return LLMStatus(False, "fake-model", "Ollama isn't running.", "ollama serve")

    async def stream(self, messages):
        self.calls.append(messages)
        for piece in self.pieces:
            yield piece
        if self.error:
            raise LLMError(self.error)


@pytest.fixture
def engines():
    return {"transcriber": FakeTranscriber(), "llm": FakeLLM(), "speaker": FakeSpeaker()}


@pytest.fixture
def client(engines, tmp_path):
    settings = Settings(models_dir=tmp_path, max_audio_mb=1)
    with TestClient(create_app(settings, **engines)) as test_client:
        yield test_client


def talk(client: TestClient, session_id: str = "s1", audio: bytes = b"fake-audio"):
    """POST a recording and return the parsed NDJSON events."""
    response = client.post(
        "/api/talk",
        files={"audio": ("speech.webm", audio, "audio/webm")},
        data={"session_id": session_id},
    )
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]
