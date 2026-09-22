from __future__ import annotations

import asyncio

import httpx
import pytest

from voiceme.llm import LLMError, OllamaChat


def _chat(handler) -> OllamaChat:
    return OllamaChat("http://ollama.test", "phi4-mini", transport=httpx.MockTransport(handler))


def _collect(chat: OllamaChat) -> list[str]:
    async def run() -> list[str]:
        return [p async for p in chat.stream([{"role": "user", "content": "hi"}])]

    return asyncio.run(run())


def test_stream_yields_message_pieces_until_done():
    body = (
        b'{"message":{"role":"assistant","content":"Hel"},"done":false}\n'
        b'{"message":{"role":"assistant","content":"lo"},"done":false}\n'
        b'{"message":{"role":"assistant","content":""},"done":true}\n'
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=body)

    assert _collect(_chat(handler)) == ["Hel", "lo"]
    assert seen["url"] == "http://ollama.test/api/chat"


def test_missing_model_gives_a_pull_hint():
    chat = _chat(lambda request: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(LLMError, match="ollama pull phi4-mini"):
        _collect(chat)


def test_offline_server_gives_a_start_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match="ollama serve"):
        _collect(_chat(handler))


def test_error_inside_the_stream_is_raised():
    chat = _chat(lambda request: httpx.Response(200, content=b'{"error":"out of memory"}\n'))
    with pytest.raises(LLMError, match="out of memory"):
        _collect(chat)


def _status(handler):
    return asyncio.run(_chat(handler).status())


def test_status_ready_when_model_is_installed_with_default_tag():
    status = _status(lambda r: httpx.Response(200, json={"models": [{"name": "phi4-mini:latest"}]}))
    assert status.ready


def test_status_reports_missing_model():
    status = _status(lambda r: httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]}))
    assert not status.ready
    assert status.fix == "ollama pull phi4-mini"


def test_status_reports_offline_server():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    status = _status(handler)
    assert not status.ready
    assert status.fix == "ollama serve"
