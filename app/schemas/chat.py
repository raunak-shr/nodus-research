"""Grounded chat over a finished report — LLM output and response shapes.

`ReportAnswer` is the agent's output and is flat on purpose (see the schema
convention in CLAUDE.md); `ChatAnswerRead` is what a caller gets, with the
labels the model cited resolved back to real clusters so a UI can link them.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """One earlier turn of the thread, replayed by the client.

    Nothing about a chat is stored: the thread belongs to the client and is sent
    back with each question. That keeps this path free of a table, a session and
    an expiry policy, and it means two readers asking about the same report
    cannot see each other's questions.
    """

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ReportAnswer(BaseModel):
    """report_chat_agent output — one answer, grounded in supplied material."""

    answer: str = Field(
        description=(
            "The answer, drawn only from the supplied material and citing papers as "
            "[Author, Year]. When the material does not answer the question, say so "
            "and state what it does establish nearby instead."
        )
    )
    covered: bool = Field(
        description="False when the supplied report and clusters do not answer the question"
    )
    sources: list[str] = Field(
        description="Labels of the blocks the answer used, exactly as given (e.g. ['S2', 'C4'])"
    )


class ChatCitation(BaseModel):
    """A block the answer used, resolved to something the caller can open."""

    label: str
    kind: Literal["front_matter", "section", "cluster"]
    heading: str
    #: Present for a section or a cluster, so a client can open the cluster
    #: detail behind the citation rather than re-searching the report for it.
    cluster_id: UUID | None = None


class ChatGrounding(BaseModel):
    """What was in scope for this answer, and whether all of it was sent.

    The material is trimmed to a character budget, so an answer can be grounded
    in less than the report holds. Reporting that is the difference between "the
    report does not say" and "the part of the report we sent does not say".
    """

    report_title: str
    sections_total: int
    clusters_total: int
    #: Clusters with no report section — `max_clusters_per_query` truncates the
    #: report, and their evidence is still fair game for a question.
    clusters_without_section: int
    blocks_sent: int
    truncated: bool


class ChatAnswerRead(BaseModel):
    query_id: UUID
    question: str
    answer: str
    covered: bool
    citations: list[ChatCitation]
    grounding: ChatGrounding
    llm_model_used: str | None = None
