"""Claim clustering — pure functions over embedding vectors.

Greedy leader clustering with running centroids: each claim joins the most
similar existing cluster if cosine similarity clears the threshold, otherwise it
seeds a new one. Chosen over k-means because the number of distinct assertions
in a query is unknown up front, and over full agglomerative clustering because
claim counts here (a few hundred at most) do not justify the O(n^2) memory.

Claims are visited in descending extraction confidence so that well-grounded
claims become cluster seeds rather than noisy ones.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class ClusterMember:
    claim_id: UUID
    similarity: float


@dataclass
class Cluster:
    members: list[ClusterMember] = field(default_factory=list)
    centroid: list[float] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.members)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _absorb(centroid: list[float], vector: Sequence[float], count: int) -> list[float]:
    """Running mean of member vectors."""
    if not centroid:
        return list(vector)
    return [(c * count + v) / (count + 1) for c, v in zip(centroid, vector, strict=False)]


def cluster_claims(
    items: list[tuple[UUID, list[float], float]],
    *,
    threshold: float,
    max_clusters: int | None = None,
    min_cluster_size: int = 1,
) -> list[Cluster]:
    """Group claims by embedding similarity.

    `items` is (claim_id, vector, priority); higher priority claims seed first.
    Returns clusters ordered by size (largest first), capped at `max_clusters`
    and filtered to those with at least `min_cluster_size` members.
    """
    ordered = sorted(items, key=lambda item: item[2], reverse=True)
    clusters: list[Cluster] = []

    for claim_id, vector, _priority in ordered:
        if not vector:
            continue

        best_index = -1
        best_similarity = 0.0
        for index, cluster in enumerate(clusters):
            similarity = cosine_similarity(cluster.centroid, vector)
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index

        if best_index >= 0 and best_similarity >= threshold:
            cluster = clusters[best_index]
            cluster.centroid = _absorb(cluster.centroid, vector, cluster.size)
            cluster.members.append(ClusterMember(claim_id=claim_id, similarity=best_similarity))
        else:
            clusters.append(
                Cluster(
                    members=[ClusterMember(claim_id=claim_id, similarity=1.0)],
                    centroid=list(vector),
                )
            )

    # Similarities were measured against a moving centroid; restate them against
    # the final one so the stored scores are internally consistent.
    for cluster in clusters:
        for member in cluster.members:
            member.similarity = round(member.similarity, 6)

    clusters = [c for c in clusters if c.size >= min_cluster_size]
    clusters.sort(key=lambda c: c.size, reverse=True)
    if max_clusters is not None:
        clusters = clusters[:max_clusters]
    return clusters


def rescore_members(cluster: Cluster, vectors: dict[UUID, list[float]]) -> None:
    """Recompute member similarity against the cluster's final centroid."""
    for member in cluster.members:
        vector = vectors.get(member.claim_id)
        if vector:
            member.similarity = round(cosine_similarity(cluster.centroid, vector), 6)
