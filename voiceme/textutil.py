"""Helpers that turn a raw LLM token stream into short, speakable sentences."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

# A sentence ends at ., !, ? or an ellipsis followed by whitespace, or at a newline.
_BOUNDARY = re.compile(r"(?<=[.!?\u2026])[\"')\]]*\s+|\n+")
_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_RULE = re.compile(r"^\s*[-*_=]{3,}\s*$", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_LIST_MARKER = re.compile(r"^\s*(?:[>#*\u2022]+|-(?=\s))\s*", re.MULTILINE)
_EMPHASIS = re.compile(r"[*~#`]+|(?<!\w)_+|_+(?!\w)")
_EMOJI = re.compile("[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f\u200d]")
_SPACES = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    """Remove markdown, links and emoji so a TTS engine doesn't read them aloud."""
    text = _CODE_BLOCK.sub(" ", text)
    text = _RULE.sub("", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _EMOJI.sub("", text)
    return _SPACES.sub(" ", text).strip()


def _next_boundary(buffer: str, min_chars: int) -> re.Match[str] | None:
    for match in _BOUNDARY.finditer(buffer):
        if match.start() >= min_chars:
            return match
    return None


async def sentences(chunks: AsyncIterator[str], min_chars: int = 12) -> AsyncIterator[str]:
    """Group streamed text chunks into sentences.

    Very short fragments ("Dr.", "Yes.") are merged into the next sentence so the
    voice doesn't stutter.
    """
    buffer = ""
    async for chunk in chunks:
        buffer += chunk
        while (match := _next_boundary(buffer, min_chars)) is not None:
            sentence, buffer = buffer[: match.end()], buffer[match.end() :]
            if sentence.strip():
                yield sentence.strip()
    if buffer.strip():
        yield buffer.strip()


async def speakable(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield cleaned, non-empty sentences ready for text to speech."""
    async for sentence in sentences(chunks):
        cleaned = clean_for_speech(sentence)
        if cleaned:
            yield cleaned
