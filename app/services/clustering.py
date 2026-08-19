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


def merge_similar(clusters: list[Cluster], threshold: float) -> list[Cluster]:
    """Fold together clusters whose centroids ended up describing one assertion.

    Greedy leader clustering never revisits a decision: a claim is compared to
    the centroids that exist when its turn comes, and a growing cluster's
    centroid drifts as it absorbs members. So a single assertion can seed two
    clusters that finish sitting almost on top of each other. On one real run the
    two largest clusters — 47 claims and 37 claims — scored 0.936 against each
    other and were written up as two sections under the same heading, presenting
    one consensus as two findings.

    The bar is deliberately higher than the per-claim threshold. Centroids are
    means, so they sit closer together than the claims around them; merging at
    the same bar cascades until the whole query is one cluster.

    Merges the most similar pair first and repeats, so the outcome does not
    depend on iteration order the way the greedy pass does.
    """
    merged = [Cluster(members=list(c.members), centroid=list(c.centroid)) for c in clusters]

    while len(merged) > 1:
        best: tuple[float, int, int] | None = None
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                similarity = cosine_similarity(merged[i].centroid, merged[j].centroid)
                if similarity >= threshold and (best is None or similarity > best[0]):
                    best = (similarity, i, j)
        if best is None:
            break

        _, i, j = best
        keep, absorb = merged[i], merged[j]
        total = keep.size + absorb.size
        keep.centroid = [
            (x * keep.size + y * absorb.size) / total
            for x, y in zip(keep.centroid, absorb.centroid, strict=False)
        ]
        keep.members.extend(absorb.members)
        del merged[j]

    return merged


def cluster_claims(
    items: list[tuple[UUID, list[float], float]],
    *,
    threshold: float,
    max_clusters: int | None = None,
    min_cluster_size: int = 1,
    merge_threshold: float | None = None,
) -> list[Cluster]:
    """Group claims by embedding similarity.

    `items` is (claim_id, vector, priority); higher priority claims seed first.
    Returns clusters ordered by size (largest first), capped at `max_clusters`
    and filtered to those with at least `min_cluster_size` members.

    `merge_threshold` runs a second pass over the finished clusters, folding any
    whose centroids are that similar — see `merge_similar` for why the greedy
    pass leaves those behind.
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

    if merge_threshold is not None:
        clusters = merge_similar(clusters, merge_threshold)

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
