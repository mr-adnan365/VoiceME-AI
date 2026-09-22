"""Small async-iterator utilities."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TypeVar

T = TypeVar("T")

_DONE = object()


class _Failure:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


async def prefetch(source: AsyncIterator[T], size: int = 4) -> AsyncIterator[T]:
    """Run ``source`` in a background task and hand its items over through a queue.

    This lets the language model keep generating the next sentence while the
    consumer is busy turning the previous one into audio. Closing this iterator
    (for example when the browser disconnects) cancels the background task.
    """
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=size)

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
            await queue.put(_DONE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # forwarded to the consumer
            await queue.put(_Failure(exc))
        finally:
            # Make sure the source (e.g. an open HTTP stream) is released promptly.
            if aclose := getattr(source, "aclose", None):
                await aclose()

    task = asyncio.create_task(pump())
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                return
            if isinstance(item, _Failure):
                raise item.exc
            yield item  # type: ignore[misc]
    finally:
        task.cancel()
