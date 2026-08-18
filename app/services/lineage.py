"""Axis 1 — evidence lineage.

Builds the `lineage_tree` for a claim cluster: which paper stated the claim
first, and how each later paper relates to it. Semantic Scholar's bulk search
does not return citation edges, so lineage is reconstructed from publication
chronology plus the stance the cross-paper agent assigned to each claim. That
is an approximation, and the payload says so via `basis`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

_RELATIONSHIP_BY_STANCE = {
    "supports": "supports",
    "contradicts": "contradicts",
    "neutral": "extends",
}


def build_lineage_tree(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble a lineage tree from per-claim entries.

    Each entry needs: paper_id, title, year, citation_count, stance, claim_id.
    The root is the earliest paper (ties broken by citation count), and the
    chain runs chronologically from there.
    """
    if not entries:
        return {"root_paper_id": None, "chain": [], "basis": "chronological+stance"}

    # One node per paper: the earliest, most-cited claim represents its paper.
    by_paper: dict[UUID, dict[str, Any]] = {}
    for entry in entries:
        paper_id = entry["paper_id"]
        current = by_paper.get(paper_id)
        if current is None or _rank(entry) < _rank(current):
            by_paper[paper_id] = entry

    nodes = sorted(by_paper.values(), key=_sort_key)
    root = nodes[0]

    chain = [
        {
            "paper_id": str(node["paper_id"]),
            "claim_id": str(node["claim_id"]),
            "title": node["title"],
            "year": node["year"],
            "citation_count": node["citation_count"],
            "relationship": (
                "origin"
                if node is root
                else _RELATIONSHIP_BY_STANCE.get(node.get("stance", "neutral"), "extends")
            ),
        }
        for node in nodes
    ]

    return {
        "root_paper_id": str(root["paper_id"]),
        "root_year": root["year"],
        "span_years": _span(nodes),
        "paper_count": len(nodes),
        "chain": chain,
        "basis": "chronological+stance",
    }


def _rank(entry: dict[str, Any]) -> tuple[float, float]:
    """Lower is better: prefer supporting claims, then higher confidence."""
    stance_rank = 0 if entry.get("stance") == "supports" else 1
    return (stance_rank, -float(entry.get("confidence_score") or 0.0))


def _sort_key(entry: dict[str, Any]) -> tuple[int, int]:
    year = entry.get("year")
    return (year if year is not None else 9999, -int(entry.get("citation_count") or 0))


def _span(nodes: list[dict[str, Any]]) -> int | None:
    years = [n["year"] for n in nodes if n.get("year")]
    if len(years) < 2:
        return None
    return max(years) - min(years)
