from uuid import uuid4

from app.services.lineage import build_lineage_tree


def _entry(year, *, stance="supports", citations=10, title="Paper", confidence=0.8, paper_id=None):
    return {
        "paper_id": paper_id or uuid4(),
        "claim_id": uuid4(),
        "title": title,
        "year": year,
        "citation_count": citations,
        "stance": stance,
        "confidence_score": confidence,
    }


def test_empty_cluster_returns_empty_tree():
    tree = build_lineage_tree([])
    assert tree["root_paper_id"] is None
    assert tree["chain"] == []


def test_root_is_the_earliest_paper():
    entries = [_entry(2021), _entry(2015, title="Origin"), _entry(2019)]
    tree = build_lineage_tree(entries)

    assert tree["chain"][0]["title"] == "Origin"
    assert tree["chain"][0]["relationship"] == "origin"
    assert tree["root_year"] == 2015


def test_chain_is_chronological():
    tree = build_lineage_tree([_entry(2022), _entry(2016), _entry(2019)])
    years = [node["year"] for node in tree["chain"]]
    assert years == sorted(years)


def test_stance_maps_to_relationship():
    entries = [
        _entry(2015, title="Origin"),
        _entry(2018, stance="contradicts", title="Rebuttal"),
        _entry(2020, stance="neutral", title="Adjacent"),
    ]
    chain = build_lineage_tree(entries)["chain"]
    relationships = {node["title"]: node["relationship"] for node in chain}

    assert relationships["Origin"] == "origin"
    assert relationships["Rebuttal"] == "contradicts"
    assert relationships["Adjacent"] == "extends"


def test_one_node_per_paper_even_with_many_claims():
    paper_id = uuid4()
    entries = [
        _entry(2019, paper_id=paper_id, confidence=0.5),
        _entry(2019, paper_id=paper_id, confidence=0.9),
        _entry(2021),
    ]
    tree = build_lineage_tree(entries)

    assert tree["paper_count"] == 2
    assert len(tree["chain"]) == 2


def test_ties_on_year_broken_by_citation_count():
    entries = [
        _entry(2015, citations=5, title="Less cited"),
        _entry(2015, citations=500, title="Seminal"),
    ]
    tree = build_lineage_tree(entries)
    assert tree["chain"][0]["title"] == "Seminal"


def test_missing_years_sort_last_and_span_is_none():
    entries = [_entry(None, title="Undated"), _entry(2020, title="Dated")]
    tree = build_lineage_tree(entries)

    assert tree["chain"][0]["title"] == "Dated"
    assert tree["span_years"] is None


def test_span_years_across_the_chain():
    tree = build_lineage_tree([_entry(2010), _entry(2024)])
    assert tree["span_years"] == 14


def test_basis_is_disclosed():
    """Lineage is reconstructed, not read from citation edges — say so."""
    tree = build_lineage_tree([_entry(2020)])
    assert tree["basis"] == "chronological+stance"
