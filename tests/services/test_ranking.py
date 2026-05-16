from datetime import datetime
from unittest.mock import patch

import pytest

from app.services.ranking import rank_papers


@pytest.fixture
def mock_year_2026():
    with patch("app.services.ranking.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 1, 1)
        yield


def test_ranking_formula_exact_scores(mock_year_2026):
    # current_year=2026, max_age=30
    # Paper a: citations=100, influential=10, year=2020, position=0
    # Paper b: citations=0,   influential=0,  year=2000, position=1
    # Paper c: citations=50,  influential=5,  year=2015, position=2
    papers = [
        {"paperId": "a", "citationCount": 100, "influentialCitationCount": 10, "year": 2020},
        {"paperId": "b", "citationCount": 0, "influentialCitationCount": 0, "year": 2000},
        {"paperId": "c", "citationCount": 50, "influentialCitationCount": 5, "year": 2015},
    ]
    ranked = rank_papers(papers, top_k=3)

    # norm_cit:  [1.0, 0.0, 0.5]
    # norm_inf:  [1.0, 0.0, 0.5]
    # recency a: 1 - 6/30  = 0.800
    # recency b: 1 - 26/30 ≈ 0.133
    # recency c: 1 - 11/30 ≈ 0.633
    # rel_rank:  [1.0, 0.667, 0.333]  (1 - i/3)
    # score_a = 0.4*1.0 + 0.3*1.0 + 0.2*0.800 + 0.1*1.0   = 0.96
    # score_c = 0.4*0.5 + 0.3*0.5 + 0.2*0.633 + 0.1*0.333 ≈ 0.510
    # score_b = 0.4*0.0 + 0.3*0.0 + 0.2*0.133 + 0.1*0.667 ≈ 0.093

    assert ranked[0]["paper_data"]["paperId"] == "a"
    assert ranked[1]["paper_data"]["paperId"] == "c"
    assert ranked[2]["paper_data"]["paperId"] == "b"

    assert abs(ranked[0]["score"] - 0.96) < 1e-6
    assert abs(ranked[1]["score"] - 0.51) < 0.01
    assert abs(ranked[2]["score"] - 0.093) < 0.01


def test_ranking_returns_top_k(mock_year_2026):
    papers = [
        {"paperId": str(i), "citationCount": i, "influentialCitationCount": 0, "year": 2020}
        for i in range(50)
    ]
    ranked = rank_papers(papers, top_k=20)
    assert len(ranked) == 20


def test_ranking_assigns_ranks(mock_year_2026):
    papers = [
        {"paperId": "x", "citationCount": 10, "influentialCitationCount": 1, "year": 2022},
        {"paperId": "y", "citationCount": 5, "influentialCitationCount": 0, "year": 2021},
    ]
    ranked = rank_papers(papers, top_k=2)
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2


def test_ranking_handles_none_year(mock_year_2026):
    papers = [
        {"paperId": "a", "citationCount": 50, "influentialCitationCount": 5, "year": None},
        {"paperId": "b", "citationCount": 50, "influentialCitationCount": 5, "year": 2020},
    ]
    ranked = rank_papers(papers, top_k=2)
    # Paper b should outscore a (same everything except b has positive recency)
    assert ranked[0]["paper_data"]["paperId"] == "b"


def test_ranking_all_same_citations(mock_year_2026):
    papers = [
        {"paperId": str(i), "citationCount": 100, "influentialCitationCount": 10, "year": 2020}
        for i in range(5)
    ]
    ranked = rank_papers(papers, top_k=5)
    # All get same norm scores; first position should still win on relevance_rank
    assert ranked[0]["paper_data"]["paperId"] == "0"
    assert all(0.0 <= r["score"] <= 1.0 for r in ranked)


def test_ranking_empty_list():
    assert rank_papers([]) == []
