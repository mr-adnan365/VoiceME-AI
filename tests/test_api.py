from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from voiceme.config import Settings
from voiceme.main import create_app

from .conftest import FakeLLM, talk


def test_health_reports_every_engine(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["stt"]["model"] == "fake-whisper"
    assert body["tts"]["voice"] == "fake-voice"
    assert body["llm"]["ready"] is True


def test_health_explains_how_to_fix_a_missing_llm(client, engines):
    engines["llm"].ready = False
    body = client.get("/api/health").json()
    assert body["ok"] is False
    assert body["llm"]["message"].startswith("Ollama isn't running.")
    assert body["llm"]["fix"] == "ollama serve"


def test_talk_streams_transcript_then_sentences_then_done(client, engines):
    events = talk(client)
    assert [e["type"] for e in events] == ["transcript", "sentence", "sentence", "done"]
    assert events[0]["text"] == "what is two plus two"
    assert [e["text"] for e in events[1:3]] == ["Two plus two is four.", "Anything else?"]
    assert base64.b64decode(events[1]["audio"]).startswith(b"RIFF")
    assert engines["speaker"].spoken == ["Two plus two is four.", "Anything else?"]
    assert engines["transcriber"].received == [b"fake-audio"]


def test_markdown_is_removed_before_speaking(client, engines):
    engines["llm"].pieces = ["**Sure!** Here is a `tip`: ", "check https://example.com now."]
    events = talk(client)
    assert [e["text"] for e in events if e["type"] == "sentence"] == [
        "Sure! Here is a tip: check now."
    ]


def test_silence_reports_no_speech_and_skips_the_llm(client, engines):
    engines["transcriber"].text = ""
    events = talk(client)
    assert [e["type"] for e in events] == ["transcript", "error"]
    assert events[1]["code"] == "no_speech"
    assert engines["llm"].calls == []


def test_llm_errors_reach_the_browser(client, engines):
    engines["llm"] = FakeLLM(pieces=[], error="Can't reach Ollama at http://x. Start it.")
    with TestClient(create_app(Settings(max_audio_mb=1), **engines)) as fresh_client:
        events = talk(fresh_client)
    assert events[-1] == {
        "type": "error",
        "code": "llm",
        "message": "Can't reach Ollama at http://x. Start it.",
    }


def test_conversation_history_is_sent_on_follow_up_turns(client, engines):
    talk(client, session_id="a")
    talk(client, session_id="a")
    second_call = engines["llm"].calls[1]
    roles = [m["role"] for m in second_call]
    assert roles == ["system", "user", "assistant", "user"]
    assert second_call[2]["content"] == "Two plus two is four. Anything else?"


def test_sessions_do_not_share_history(client, engines):
    talk(client, session_id="a")
    talk(client, session_id="b")
    assert [m["role"] for m in engines["llm"].calls[1]] == ["system", "user"]


def test_reset_forgets_the_conversation(client, engines):
    talk(client, session_id="a")
    assert client.post("/api/reset", json={"session_id": "a"}).json() == {"ok": True}
    talk(client, session_id="a")
    assert [m["role"] for m in engines["llm"].calls[1]] == ["system", "user"]


def test_empty_upload_is_rejected(client):
    response = client.post(
        "/api/talk", files={"audio": ("speech.webm", b"", "audio/webm")}, data={"session_id": "a"}
    )
    assert response.status_code == 400


def test_oversized_upload_is_rejected(client):
    too_big = b"0" * (1024 * 1024 + 1)  # the fixture sets a 1 MB limit
    response = client.post(
        "/api/talk",
        files={"audio": ("speech.webm", too_big, "audio/webm")},
        data={"session_id": "a"},
    )
    assert response.status_code == 413


def test_web_ui_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "VoiceMe" in response.text


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/style.css", "text/css"),
        ("/app.js", "javascript"),
        ("/favicon.svg", "image/svg+xml"),
        ("/fonts/bricolage-grotesque-latin-wdth.woff2", "font/woff2"),
    ],
)
def test_static_assets_referenced_by_the_page_are_served(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
