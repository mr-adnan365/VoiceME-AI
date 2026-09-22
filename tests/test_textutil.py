from __future__ import annotations

import asyncio

from voiceme.textutil import clean_for_speech, sentences, speakable


async def _stream(*pieces: str):
    for piece in pieces:
        yield piece


def _collect(agen) -> list[str]:
    async def run() -> list[str]:
        return [item async for item in agen]

    return asyncio.run(run())


def test_clean_removes_markdown_links_code_and_emoji():
    raw = "## Title\n- **Bold** and _italic_ with `code` and [a link](https://x.io) \U0001f600"
    assert clean_for_speech(raw) == "Title Bold and italic with code and a link"


def test_clean_drops_fenced_code_blocks_and_urls():
    assert clean_for_speech("Try this:\n```py\nprint(1)\n```\nSee https://a.b/c") == "Try this: See"


def test_clean_keeps_snake_case_and_negative_numbers():
    assert clean_for_speech("use snake_case for -5 degrees") == "use snake_case for -5 degrees"


def test_sentences_split_on_terminal_punctuation():
    got = _collect(sentences(_stream("Hello the", "re! How are", " you today? Fine.")))
    assert got == ["Hello there!", "How are you today?", "Fine."]


def test_short_fragments_merge_into_the_next_sentence():
    got = _collect(sentences(_stream("Yes. That is correct, and here is why.")))
    assert got == ["Yes. That is correct, and here is why."]


def test_decimals_do_not_split():
    got = _collect(sentences(_stream("Pi is about 3.14 and e is 2.71 roughly. Done!")))
    assert got == ["Pi is about 3.14 and e is 2.71 roughly.", "Done!"]


def test_speakable_skips_sentences_that_are_only_markup():
    got = _collect(speakable(_stream("Here you go, friend.\n\n---\n\nEnjoy the rest of your day.")))
    assert got == ["Here you go, friend.", "Enjoy the rest of your day."]
