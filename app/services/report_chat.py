"""Chat over one finished report — grounded in it and in nothing else.

The report and the clusters behind it are the whole world an answer may come
from. No paper is retrieved, no PDF is re-read, no model knowledge is admitted:
a question this evidence does not settle comes back as "not covered" plus what
the report does establish nearby. That refusal is the feature. An evidence tool
whose chat answers from the model's own recall gives a reader sentences they
cannot trace to a paper, sitting beside sentences they can — and the two are
indistinguishable on screen.

Stateless. The thread lives on the client and is replayed as `history`, so there
is no chat table, no server-side session and no expiry policy to get wrong, and
two readers asking about the same report never see each other's questions.

The material is assembled here rather than by the model: front matter always,
then the report's sections and any cluster that never reached one, ranked by
overlap with the question and trimmed to a character budget. Every block carries
a label, which is what the model cites and what `ChatCitation` resolves back to
a cluster id — so a citation in an answer opens the cluster it came from instead
of leaving a reader to search the report for it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_provider import get_llm_name, get_structured_llm
from app.models.cluster import ClaimCluster
from app.models.report import Report
from app.schemas.chat import (
    ChatAnswerRead,
    ChatCitation,
    ChatGrounding,
    ChatTurn,
    ReportAnswer,
)
from app.services import cluster_edit, report_edit
from app.services.errors import Unavailable
from app.services.prompts import REPORT_CHAT_SYSTEM

logger = logging.getLogger(__name__)

#: Turns of history the model is shown. A thread is a client-side list and may
#: be arbitrarily long; only the tail changes what "it" and "that trial" refer
#: to, and the rest costs context the evidence should be spending.
_HISTORY_TURNS = 6

#: Claim lines carried per block. Enough to cite the section's evidence without
#: pasting a whole cluster: the narrative above them already weighs it.
_CLAIMS_PER_BLOCK = 6

_STOPWORDS = frozenset(
    """
    a about after again against all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers him his how i if in into is it its itself just me more
    most my no nor not of off on once only or other our out over own same she should so some such
    than that the their them then there these they this those through to too under until up very
    was we were what when where which while who whom why will with would you your
    does_it doesn don t s
    """.split()
)


@dataclass(frozen=True)
class _Block:
    """One addressable piece of grounding material."""

    label: str
    kind: str
    heading: str
    cluster_id: UUID | None
    text: str

    def citation(self) -> ChatCitation:
        return ChatCitation(
            label=self.label, kind=self.kind, heading=self.heading, cluster_id=self.cluster_id
        )


# ------------------------------------------------------------------ material


def _terms(text: str) -> set[str]:
    """Content words of a question, for ranking blocks against it."""
    words = re.findall(r"[a-z0-9][a-z0-9\-']+", text.lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _bullets(label: str, values: Any) -> str:
    if not values:
        return ""
    lines = "\n".join(f"- {str(value).strip()}" for value in values if str(value).strip())
    return f"{label}:\n{lines}\n" if lines else ""


def _front_matter_block(report: Report) -> _Block:
    text = (
        f"Report title: {report.title}\n"
        f"Executive summary: {report.executive_summary or 'not written'}\n"
        + _bullets("Key findings", report.key_findings)
        + _bullets("Open questions the evidence cannot settle", report.open_questions)
    )
    return _Block(
        label="R", kind="front_matter", heading=report.title, cluster_id=None, text=text.strip()
    )


def _stance_line(supports: Any, contradicts: Any, neutral: Any) -> str:
    return f"supporting {supports or 0}, contradicting {contradicts or 0}, neutral {neutral or 0}"


def _claim_lines(claims: list[dict[str, Any]]) -> str:
    if not claims:
        return ""
    lines = []
    for claim in claims[:_CLAIMS_PER_BLOCK]:
        text = str(claim.get("claim_text") or "").strip()
        if not text:
            continue
        parts = [f"- [{claim.get('stance', 'supports')}] ({claim.get('citation', 'n.d.')}) {text}"]
        sample = claim.get("sample_size")
        if sample:
            parts.append(f"(n = {sample})")
        lines.append(" ".join(parts))
    dropped = max(0, len(claims) - _CLAIMS_PER_BLOCK)
    tail = f"\n- (+{dropped} further claims in this cluster, not listed)" if dropped else ""
    return ("Claims:\n" + "\n".join(lines) + tail + "\n") if lines else ""


def _drivers(drivers: Any) -> str:
    if not drivers:
        return ""
    lines = []
    for driver in drivers:
        if isinstance(driver, dict):
            kind = driver.get("type", "other")
            lines.append(f"- {kind}: {driver.get('description', '')}".strip())
        else:
            lines.append(f"- {driver}")
    return "Why the papers disagree:\n" + "\n".join(lines) + "\n"


def _section_block(index: int, section: dict[str, Any]) -> _Block:
    heading = str(section.get("heading") or section.get("central_theme") or "Untitled section")
    stances = section.get("stance_counts") or {}
    counts = _stance_line(
        stances.get("supports"), stances.get("contradicts"), stances.get("neutral")
    )
    text = (
        f"Section heading: {heading}\n"
        f"Central theme: {section.get('central_theme') or 'not stated'}\n"
        f"Evidence quality: {section.get('quality_tier', 'unrated')}"
        f" (score {section.get('quality_score')})\n"
        f"Papers: {section.get('paper_count', 0)}; claims {counts}\n"
        f"Narrative:\n{section.get('narrative') or 'not written'}\n"
        + _bullets("Caveats", section.get("caveats"))
        + _drivers(section.get("disagreement_drivers"))
        + _claim_lines(list(section.get("claims") or []))
    )
    cluster_id = section.get("cluster_id")
    return _Block(
        label=f"S{index}",
        kind="section",
        heading=heading,
        cluster_id=UUID(str(cluster_id)) if cluster_id else None,
        text=text.strip(),
    )


def _cluster_block(index: int, cluster: ClaimCluster) -> _Block:
    """A cluster with no report section.

    `max_clusters_per_query` truncates the report to its largest clusters, so
    these exist on a real run and their claims are still this query's evidence.
    A reader asking about one of them should be told what it found, not that the
    report is silent — the report is silent because it was trimmed.
    """
    counts = _stance_line(cluster.support_count, cluster.contradiction_count, cluster.neutral_count)
    text = (
        f"Cluster theme: {cluster.central_theme}\n"
        "This cluster has no section in the report: it fell outside the section cap.\n"
        f"Consensus: {cluster.consensus_summary or 'not written'}\n"
        f"Evidence quality: {cluster.quality_tier} (score {cluster.quality_score})\n"
        f"Claims: {counts}\n" + _drivers(cluster.disagreement_drivers)
    )
    return _Block(
        label=f"C{index}",
        kind="cluster",
        heading=cluster.central_theme,
        cluster_id=cluster.id,
        text=text.strip(),
    )


def build_blocks(report: Report, clusters: list[ClaimCluster]) -> list[_Block]:
    """Every piece of material a question may be answered from, in report order.

    Public for the tests: what is in scope is the whole contract of this module,
    and it is worth asserting on directly rather than through a mocked answer.
    """
    sections = list(report.sections or [])
    blocks = [_front_matter_block(report)]
    blocks += [_section_block(i + 1, section) for i, section in enumerate(sections)]

    covered = {str(section.get("cluster_id")) for section in sections}
    orphans = [cluster for cluster in clusters if str(cluster.id) not in covered]
    blocks += [_cluster_block(i + 1, cluster) for i, cluster in enumerate(orphans)]
    return blocks


def _select(blocks: list[_Block], question: str, budget: int) -> tuple[list[_Block], bool]:
    """Trim the material to a character budget, keeping what the question hits.

    Front matter is never dropped — it is the report's own answer to the
    question that produced it, and it is what a broad question ("what did this
    find?") is asking for. The rest is ranked by how many distinct content words
    of the question it mentions, and a question that matches nothing leaves the
    order alone, which is report order.
    """
    terms = _terms(question)
    head, rest = blocks[0], blocks[1:]

    def score(block: _Block) -> int:
        if not terms:
            return 0
        haystack = f"{block.heading}\n{block.text}".lower()
        return sum(1 for term in terms if term in haystack)

    ranked = sorted(rest, key=lambda block: -score(block))
    kept = [head]
    spent = len(head.text)
    truncated = False
    for block in ranked:
        if spent + len(block.text) > budget:
            truncated = True
            continue
        kept.append(block)
        spent += len(block.text)

    order = {block.label: index for index, block in enumerate(blocks)}
    kept.sort(key=lambda block: order[block.label])
    return kept, truncated


def _render_material(blocks: list[_Block]) -> str:
    return "\n\n".join(f"[{block.label}]\n{block.text}" for block in blocks)


def _render_history(history: list[ChatTurn]) -> str:
    """The thread as a transcript inside the prompt, not as chat messages.

    Folding it in keeps one code path across providers: Gemini decodes against a
    response schema while Anthropic and Ollama use tool calls, and an assistant
    turn that was itself a structured-output call has no clean representation in
    the second shape. A transcript reads the same to all three.
    """
    tail = [turn for turn in history if turn.content.strip()][-_HISTORY_TURNS:]
    if not tail:
        return ""
    lines = "\n".join(
        f"{'Reader' if turn.role == 'user' else 'You'}: {turn.content.strip()}" for turn in tail
    )
    return f"Earlier in this conversation:\n{lines}\n\n"


def _resolve(sources: list[str], blocks: list[_Block]) -> list[ChatCitation]:
    """Labels the model returned, mapped to blocks it was actually given.

    A label that was not in the material is dropped rather than surfaced: it
    cites nothing a reader could open, and passing it through would put a
    citation chip on screen with no evidence behind it.
    """
    by_label = {block.label: block for block in blocks}
    seen: set[str] = set()
    citations = []
    for raw in sources:
        label = str(raw).strip().upper().strip("[]")
        block = by_label.get(label)
        if block and label not in seen:
            seen.add(label)
            citations.append(block.citation())
    return citations


# -------------------------------------------------------------------- answer


async def answer(
    query_id: UUID,
    question: str,
    history: list[ChatTurn],
    db: AsyncSession,
) -> ChatAnswerRead:
    """Answer one question about a query's report, from that report only.

    Raises `NotFound` when the query has no report yet — there is nothing to
    ground an answer in before synthesis has run, and a chat that answers anyway
    is answering from the model.
    """
    report = await report_edit.require_report(query_id, db)
    clusters = await cluster_edit.list_for_query(query_id, db)
    blocks = build_blocks(report, clusters)
    sections_total = len(report.sections or [])
    orphans = len(blocks) - 1 - sections_total

    sent, truncated = _select(blocks, question, settings.report_chat_context_chars)
    grounding = ChatGrounding(
        report_title=report.title,
        sections_total=sections_total,
        clusters_total=len(clusters),
        clusters_without_section=orphans,
        blocks_sent=len(sent),
        truncated=truncated,
    )

    # Every read is done. The provider call below takes seconds and this session
    # would otherwise hold a pooled connection open for all of them — with ten
    # papers' worth of sessions and Supavisor counting clients, that is the
    # difference between a working run and EMAXCONNSESSION.
    await db.commit()

    prompt = (
        f"{_render_history(history)}"
        f"Material — the whole of what you may answer from:\n\n{_render_material(sent)}\n\n"
        f"Reader's question: {question.strip()}"
    )

    agent = get_structured_llm(ReportAnswer, task="synthesis")
    try:
        result: ReportAnswer = await agent.ainvoke(
            [SystemMessage(content=REPORT_CHAT_SYSTEM), HumanMessage(content=prompt)]
        )
    except Exception as exc:  # noqa: BLE001 - reported as a transport-neutral error
        logger.warning("Report chat failed for query %s: %s", query_id, exc)
        raise Unavailable(
            "The answer could not be generated — the language model did not respond",
            query_id=str(query_id),
        ) from exc

    return ChatAnswerRead(
        query_id=query_id,
        question=question.strip(),
        answer=result.answer.strip(),
        covered=result.covered,
        citations=_resolve(result.sources, sent),
        grounding=grounding,
        llm_model_used=get_llm_name(),
    )


__all__ = ["answer", "build_blocks", "ChatAnswerRead", "ChatTurn"]
