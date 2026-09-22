from __future__ import annotations

import asyncio

import pytest

from voiceme.conversation import Conversations
from voiceme.streams import prefetch


def test_prefetch_passes_items_through_in_order():
    async def source():
        for i in range(5):
            yield i

    async def run():
        return [i async for i in prefetch(source(), size=2)]

    assert asyncio.run(run()) == [0, 1, 2, 3, 4]


def test_prefetch_re_raises_errors_from_the_source():
    async def source():
        yield 1
        raise ValueError("boom")

    async def run():
        return [i async for i in prefetch(source())]

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(run())


def test_prefetch_stops_the_source_when_the_consumer_quits():
    state = {"closed": False}

    async def source():
        try:
            for i in range(1000):
                yield i
                await asyncio.sleep(0)
        finally:
            state["closed"] = True

    async def run():
        stream = prefetch(source(), size=1)
        assert await stream.__anext__() == 0
        await stream.aclose()
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert state["closed"] is True


def test_conversations_keep_only_recent_turns_and_sessions():
    convo = Conversations(max_turns=2, max_sessions=2)
    for n in range(4):
        convo.add_turn("a", f"q{n}", f"a{n}")
    assert [m["content"] for m in convo.get("a")] == ["q2", "a2", "q3", "a3"]

    convo.add_turn("b", "q", "a")
    convo.add_turn("c", "q", "a")
    assert convo.get("a") == []  # oldest session was evicted
