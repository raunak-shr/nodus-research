from datetime import datetime
from typing import Any

_MAX_AGE = 30  # papers older than this get recency score of 0


def _minmax(values: list[float]) -> list[float]:
    mn = min(values)
    mx = max(values)
    if mx == mn:
        return [1.0] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def rank_papers(
    papers: list[dict[str, Any]],
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Score and rank papers using a composite formula.

    Returns up to top_k dicts with keys: score, rank (1-based), paper_data.
    """
    if not papers:
        return []

    current_year = datetime.now().year
    n = len(papers)

    citations = [float(p.get("citationCount") or 0) for p in papers]
    influential = [float(p.get("influentialCitationCount") or 0) for p in papers]

    norm_cit = _minmax(citations)
    norm_inf = _minmax(influential)

    scored: list[tuple[float, dict[str, Any]]] = []
    for i, paper in enumerate(papers):
        year = paper.get("year")
        if year is not None:
            recency = max(0.0, min(1.0, 1.0 - (current_year - year) / _MAX_AGE))
        else:
            recency = 0.0

        relevance_rank = 1.0 - (i / n)

        score = (
            0.4 * norm_cit[i]
            + 0.3 * norm_inf[i]
            + 0.2 * recency
            + 0.1 * relevance_rank
        )
        scored.append((score, paper))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    return [
        {"score": score, "rank": rank + 1, "paper_data": paper}
        for rank, (score, paper) in enumerate(top)
    ]
