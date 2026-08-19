"""Structuring the same question twice in a row is one call, not two.

The Interpret button structures a question; the run the user starts from that
same screen structures it again seconds later — same model, same prompt, same
answer. Nothing downstream could tell the difference, which is exactly why it
went unnoticed; a metered free tier can.
"""

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.schemas.query import StructuredQuery
from app.services import query_structurer


class _CountingAgent:
    def __init__(self, topic: str = "exercise and depression") -> None:
        self.calls = 0
        self.topic = topic

    async def ainvoke(self, messages):
        self.calls += 1
        return StructuredQuery(topic=self.topic, search_keywords=["exercise", "depression"])


@pytest.fixture(autouse=True)
def _clear():
    query_structurer.clear_memo()
    yield
    query_structurer.clear_memo()


@pytest.mark.asyncio
async def test_the_same_question_is_structured_once():
    agent = _CountingAgent()
    with patch.object(query_structurer, "get_structured_llm", return_value=agent):
        first = await query_structurer.structure_query("Does aerobic exercise help depression?")
        second = await query_structurer.structure_query("Does aerobic exercise help depression?")

    assert agent.calls == 1
    assert first.topic == second.topic


@pytest.mark.asyncio
async def test_a_different_question_is_not_answered_from_the_memo():
    agent = _CountingAgent()
    with patch.object(query_structurer, "get_structured_llm", return_value=agent):
        await query_structurer.structure_query("Does aerobic exercise help depression?")
        await query_structurer.structure_query("Does fasting improve HbA1c?")

    assert agent.calls == 2


@pytest.mark.asyncio
async def test_follow_up_context_is_part_of_the_key():
    """The same question asked *under* a parent is a different prompt, and the
    agent is told to narrow rather than restart — a shared answer would be wrong."""
    agent = _CountingAgent()
    with patch.object(query_structurer, "get_structured_llm", return_value=agent):
        await query_structurer.structure_query("Does it hold for older adults?")
        await query_structurer.structure_query("Does it hold for older adults?", context="parent")

    assert agent.calls == 2


@pytest.mark.asyncio
async def test_the_caller_cannot_edit_what_the_next_caller_gets():
    agent = _CountingAgent()
    with patch.object(query_structurer, "get_structured_llm", return_value=agent):
        first = await query_structurer.structure_query("Does exercise help?")
        first.search_keywords.append("mutated")
        second = await query_structurer.structure_query("Does exercise help?")

    assert "mutated" not in second.search_keywords


@pytest.mark.asyncio
async def test_a_failed_structuring_is_not_pinned():
    """The fallback is the raw query with no keywords — worth retrying on the
    next call, not holding onto for the next quarter of an hour."""
    calls = {"n": 0}

    class _Flaky:
        async def ainvoke(self, messages):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("provider down")
            return StructuredQuery(topic="recovered", search_keywords=["exercise"])

    with patch.object(query_structurer, "get_structured_llm", return_value=_Flaky()):
        first = await query_structurer.structure_query("Does exercise help?")
        second = await query_structurer.structure_query("Does exercise help?")

    assert first.topic == "Does exercise help?"
    assert second.topic == "recovered"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_the_memo_can_be_switched_off():
    agent = _CountingAgent()
    with (
        patch.object(settings, "query_structure_memo_seconds", 0),
        patch.object(query_structurer, "get_structured_llm", return_value=agent),
    ):
        await query_structurer.structure_query("Does exercise help?")
        await query_structurer.structure_query("Does exercise help?")

    assert agent.calls == 2


@pytest.mark.asyncio
async def test_an_expired_entry_is_asked_again():
    agent = _CountingAgent()
    with patch.object(query_structurer, "get_structured_llm", return_value=agent):
        await query_structurer.structure_query("Does exercise help?")
        # Age every entry past the TTL rather than sleeping through it.
        for key, (_, value) in list(query_structurer._MEMO.items()):
            query_structurer._MEMO[key] = (-10_000.0, value)
        await query_structurer.structure_query("Does exercise help?")

    assert agent.calls == 2
