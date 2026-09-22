"""VoiceMe web server.

One voice turn is a single HTTP request:

    browser audio  ->  Whisper (text)  ->  Ollama (reply, streamed)  ->  Piper (audio)

The reply is streamed back as newline-delimited JSON, one event per sentence, so the
browser can start speaking after the *first* sentence instead of waiting for all of it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import WEB_DIR, Settings
from .conversation import Conversations
from .llm import LLMError, OllamaChat
from .streams import prefetch
from .stt import Transcriber
from .textutil import speakable
from .tts import Speaker

log = logging.getLogger("voiceme")


class ResetRequest(BaseModel):
    session_id: str


def _event(**payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def create_app(
    settings: Settings | None = None,
    *,
    transcriber: Any = None,
    llm: Any = None,
    speaker: Any = None,
) -> FastAPI:
    """Build the app. The three engines can be swapped out (the tests do exactly that)."""
    settings = settings or Settings.from_env()
    transcriber = transcriber or Transcriber(
        settings.whisper_model,
        settings.models_dir / "whisper",
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        language=settings.whisper_language,
    )
    llm = llm or OllamaChat(
        settings.ollama_url,
        settings.ollama_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    speaker = speaker or Speaker(settings.piper_voice, settings.models_dir / "voices")
    conversations = Conversations(max_turns=settings.max_history_turns)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await asyncio.to_thread(transcriber.load)
        await asyncio.to_thread(speaker.load)
        status = await llm.status()
        if not status.ready:
            log.warning("%s Fix: %s", status.message, status.fix)
        log.info("VoiceMe is ready at http://%s:%s", settings.host, settings.port)
        yield

    app = FastAPI(title="VoiceMe", lifespan=lifespan)

    async def run_turn(session_id: str, audio: bytes) -> AsyncIterator[bytes]:
        # 1. Speech to text
        try:
            text = await asyncio.to_thread(transcriber.transcribe, audio)
        except Exception:
            log.exception("Transcription failed")
            yield _event(
                type="error", code="stt", message="Couldn't read that recording. Try again."
            )
            return

        yield _event(type="transcript", text=text)
        if not text:
            yield _event(
                type="error",
                code="no_speech",
                message="Didn't catch that. Try again, a little closer to the microphone.",
            )
            return

        # 2. Language model, streamed and cut into sentences
        # 3. Text to speech, one sentence at a time
        messages = [
            {"role": "system", "content": settings.system_prompt},
            *conversations.get(session_id),
            {"role": "user", "content": text},
        ]
        spoken: list[str] = []
        try:
            async with aclosing(prefetch(speakable(llm.stream(messages)))) as sentences:
                async for sentence in sentences:
                    wav = await asyncio.to_thread(speaker.synthesize, sentence)
                    spoken.append(sentence)
                    yield _event(
                        type="sentence",
                        text=sentence,
                        audio=base64.b64encode(wav).decode("ascii"),
                    )
        except LLMError as exc:
            yield _event(type="error", code="llm", message=str(exc))
            return
        except Exception:
            log.exception("Voice turn failed")
            yield _event(
                type="error",
                code="server",
                message="Something went wrong while answering. Check the server log.",
            )
            return
        finally:
            # Also runs when the browser hangs up mid-reply (the user interrupted).
            if spoken:
                conversations.add_turn(session_id, text, " ".join(spoken))

        yield _event(type="done")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        llm_status = await llm.status()
        return {
            "ok": llm_status.ready,
            "stt": {"ready": True, "model": transcriber.model_name},
            "tts": {"ready": True, "voice": speaker.voice_name},
            "llm": asdict(llm_status),
        }

    @app.post("/api/talk")
    async def talk(
        audio: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form(max_length=64)] = "default",
    ) -> StreamingResponse:
        limit = settings.max_audio_mb * 1024 * 1024
        data = await audio.read(limit + 1)
        if not data:
            raise HTTPException(status_code=400, detail="No audio was received.")
        if len(data) > limit:
            raise HTTPException(
                status_code=413, detail=f"Recording is larger than {settings.max_audio_mb} MB."
            )
        return StreamingResponse(
            run_turn(session_id, data),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/reset")
    async def reset(body: ResetRequest) -> dict[str, bool]:
        conversations.reset(body.session_id)
        return {"ok": True}

    # The static web UI must be mounted last so it doesn't shadow the API routes.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
