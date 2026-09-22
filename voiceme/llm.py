"""A minimal streaming client for a local Ollama server (https://ollama.com)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx


class LLMError(RuntimeError):
    """Raised with a message that is safe and useful to show to the user."""


@dataclass
class LLMStatus:
    ready: bool
    model: str
    message: str = ""
    fix: str = ""


class OllamaChat:
    def __init__(
        self,
        url: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 200,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._transport = transport

    def _client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _offline(self) -> LLMError:
        return LLMError(
            f"Can't reach Ollama at {self.url}. Open the Ollama app or run: ollama serve"
        )

    def _missing(self) -> LLMError:
        return LLMError(f"The model {self.model} isn't installed. Run: ollama pull {self.model}")

    async def status(self) -> LLMStatus:
        """Check that Ollama is running and that the configured model is installed."""
        try:
            async with self._client(httpx.Timeout(3.0)) as client:
                response = await client.get(f"{self.url}/api/tags")
                response.raise_for_status()
                names = {m.get("name", "") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError):
            return LLMStatus(
                False,
                self.model,
                "Ollama isn't running. Open the Ollama app or run",
                "ollama serve",
            )

        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in names and self.model not in names:
            return LLMStatus(
                False,
                self.model,
                f"The model {self.model} isn't installed. Run",
                f"ollama pull {self.model}",
            )
        return LLMStatus(True, self.model)

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield the reply text piece by piece as the model generates it."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": "30m",
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
        }
        timeout = httpx.Timeout(120.0, connect=5.0)
        try:
            async with self._client(timeout) as client:
                async with client.stream("POST", f"{self.url}/api/chat", json=payload) as response:
                    if response.status_code == 404:
                        raise self._missing()
                    if response.status_code != 200:
                        detail = (await response.aread()).decode("utf-8", "replace")[:200]
                        raise LLMError(
                            f"Ollama returned an error: {detail or response.status_code}"
                        )
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if error := data.get("error"):
                            raise LLMError(f"Ollama returned an error: {error}")
                        if piece := data.get("message", {}).get("content", ""):
                            yield piece
                        if data.get("done"):
                            return
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise self._offline() from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Ollama took too long to answer. Try a smaller model.") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Ollama sent a reply VoiceMe couldn't read.") from exc
