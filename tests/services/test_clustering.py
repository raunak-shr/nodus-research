import math
from uuid import uuid4

from app.services.clustering import (
    Cluster,
    ClusterMember,
    cluster_claims,
    cosine_similarity,
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
