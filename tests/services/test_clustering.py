import math
from uuid import uuid4

from app.services.clustering import (
    Cluster,
    ClusterMember,
    cluster_claims,
    cosine_similarity,
    merge_similar,
    rescore_members,
)


def _unit(*values: float) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def test_cosine_similarity_identical_vectors():
    vector = _unit(1.0, 2.0, 3.0)
    assert abs(cosine_similarity(vector, vector) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal_vectors():
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_similarity_zero_vector_is_zero_not_error():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_similar_claims_group_together():
    a, b, c = uuid4(), uuid4(), uuid4()
    items = [
        (a, [1.0, 0.0, 0.0], 0.9),
        (b, [0.99, 0.14, 0.0], 0.8),  # ~cos 0.99 with a
        (c, [0.0, 0.0, 1.0], 0.7),  # orthogonal
    ]
    clusters = cluster_claims(items, threshold=0.72)

    assert len(clusters) == 2
    largest = clusters[0]
    assert {m.claim_id for m in largest.members} == {a, b}


def test_threshold_controls_granularity():
    a, b = uuid4(), uuid4()
    items = [(a, [1.0, 0.0], 1.0), (b, _unit(1.0, 1.0), 0.9)]  # cos = 0.707

    assert len(cluster_claims(items, threshold=0.6)) == 1
    assert len(cluster_claims(items, threshold=0.9)) == 2


def test_highest_confidence_claim_seeds_the_cluster():
    weak, strong = uuid4(), uuid4()
    items = [(weak, [1.0, 0.0], 0.1), (strong, [0.0, 1.0], 0.95)]
    clusters = cluster_claims(items, threshold=0.99)

    # Both are singletons, but the strong claim was visited first.
    assert clusters[0].members[0].claim_id == strong


def test_max_clusters_keeps_largest():
    ids = [uuid4() for _ in range(6)]
    items = [
        (ids[0], [1.0, 0.0, 0.0], 0.9),
        (ids[1], [1.0, 0.01, 0.0], 0.9),
        (ids[2], [1.0, 0.02, 0.0], 0.9),
        (ids[3], [0.0, 1.0, 0.0], 0.9),
        (ids[4], [0.0, 0.0, 1.0], 0.9),
        (ids[5], [0.0, 0.0, -1.0], 0.9),
    ]
    clusters = cluster_claims(items, threshold=0.9, max_clusters=2)

    assert len(clusters) == 2
    assert clusters[0].size == 3


def test_min_cluster_size_drops_singletons():
    ids = [uuid4() for _ in range(3)]
    items = [
        (ids[0], [1.0, 0.0], 0.9),
        (ids[1], [1.0, 0.01], 0.9),
        (ids[2], [0.0, 1.0], 0.9),
    ]
    clusters = cluster_claims(items, threshold=0.9, min_cluster_size=2)

    assert len(clusters) == 1
    assert clusters[0].size == 2


def test_empty_input_and_empty_vectors():
    assert cluster_claims([], threshold=0.7) == []
    assert cluster_claims([(uuid4(), [], 1.0)], threshold=0.7) == []


def test_rescore_members_uses_final_centroid():
    claim_id = uuid4()
    cluster = Cluster(
        members=[ClusterMember(claim_id=claim_id, similarity=1.0)], centroid=[1.0, 0.0]
    )
    rescore_members(cluster, {claim_id: _unit(1.0, 1.0)})

    assert abs(cluster.members[0].similarity - 0.707107) < 1e-5


# ------------------------------------------------------- the merge pass


def _cluster(size: int, *centroid: float) -> Cluster:
    return Cluster(
        members=[ClusterMember(claim_id=uuid4(), similarity=1.0) for _ in range(size)],
        centroid=_unit(*centroid),
    )


def test_clusters_describing_one_assertion_are_folded_together():
    """The greedy pass never revisits a split; this is what closes it."""
    a = _cluster(4, 1.0, 0.05, 0.0)
    b = _cluster(2, 1.0, 0.06, 0.0)
    merged = merge_similar([a, b], 0.90)

    assert len(merged) == 1
    assert merged[0].size == 6


def test_distinct_clusters_are_left_alone():
    apart = merge_similar([_cluster(3, 1.0, 0.0), _cluster(3, 0.0, 1.0)], 0.90)
    assert [c.size for c in apart] == [3, 3]


def test_the_merged_centroid_is_weighted_by_size():
    """A 40-member cluster absorbing one claim should barely move."""
    big = _cluster(40, 1.0, 0.0)
    small = _cluster(1, 0.0, 1.0)
    merged = merge_similar([big, small], 0.0)

    assert len(merged) == 1
    # Weighted toward the larger cluster, not the midpoint an unweighted mean
    # would have produced.
    assert merged[0].centroid[0] > merged[0].centroid[1]
    assert cosine_similarity(merged[0].centroid, _unit(1.0, 0.0)) > 0.95


def test_merging_repeats_until_nothing_qualifies():
    """Three clusters on the same assertion collapse to one, not two."""
    clusters = [_cluster(2, 1.0, 0.01), _cluster(2, 1.0, 0.02), _cluster(2, 1.0, 0.03)]
    merged = merge_similar(clusters, 0.90)

    assert len(merged) == 1
    assert merged[0].size == 6


def test_a_single_cluster_survives_the_pass():
    assert len(merge_similar([_cluster(3, 1.0, 0.0)], 0.5)) == 1
    assert merge_similar([], 0.5) == []


def test_cluster_claims_leaves_merging_off_by_default():
    """Callers opt in; the pass is a behaviour change, not a silent default."""
    items = [
        (uuid4(), _unit(1.0, 0.05, 0.0), 0.9),
        (uuid4(), _unit(0.05, 1.0, 0.0), 0.8),
    ]
    # A threshold too high to group them, so two clusters form either way.
    assert len(cluster_claims(items, threshold=0.95)) == 2
    assert len(cluster_claims(items, threshold=0.95, merge_threshold=None)) == 2
    # ...and a merge bar low enough to fold them proves the hook is wired. These
    # two sit at ~0.0998, so the bar has to be under that, not at it.
    assert len(cluster_claims(items, threshold=0.95, merge_threshold=0.05)) == 1
