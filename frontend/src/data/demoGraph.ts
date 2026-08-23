/** The demo run, shaped exactly as `graph.get` returns it.
 *
 *  Built from the same fixtures every other demo screen reads, rather than
 *  written out by hand: a second copy of the corpus would let the graph and the
 *  report disagree about the run they are both describing, and the graph is the
 *  one place where that would be invisible.
 */

import { DEMO_CLUSTERS, DEMO_FAILURES, DEMO_PAPERS, DEMO_QUERY_ID } from './demoCorpus'
import { DEMO_QUESTION } from './demoRun'
import type { GraphClusterNode, GraphLineageEdge, GraphPaperNode, GraphRead } from '../lib/types'

/** "Blumenthal, Babyak, Doraiswamy et al." → three names.
 *
 *  The demo fixtures carry an author *line* where the API carries records, so
 *  it is split back apart here. "et al." is dropped rather than kept as a
 *  person, which is the only thing that could go visibly wrong in the authors
 *  view.
 */
function splitAuthors(line: string): string[] {
  return line
    .replace(/\s*et al\.?\s*$/, '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

export function demoGraph(): GraphRead {
  const papers: GraphPaperNode[] = DEMO_PAPERS.map((paper) => ({
    id: paper.id,
    title: paper.title,
    authors: splitAuthors(paper.authors),
    year: paper.year,
    venue: paper.journal,
    study_type: paper.type,
    citation_count: paper.cites,
    rank: paper.rank,
    claim_count: DEMO_FAILURES[paper.id] ? 0 : paper.claims,
    uploaded: false,
    dropped_reason: DEMO_FAILURES[paper.id] ?? null,
  }))

  const known = new Set(papers.map((paper) => paper.id))

  const clusters: GraphClusterNode[] = DEMO_CLUSTERS.map((cluster) => ({
    id: cluster.id,
    theme: cluster.central_theme,
    quality_tier: cluster.quality_tier,
    support_count: cluster.support_count,
    contradiction_count: cluster.contradiction_count,
    neutral_count: cluster.neutral_count,
    paper_count: new Set(cluster.claims.map((claim) => claim.paper_id)).size,
    claims: cluster.claims.map((claim) => ({
      id: claim.claim_id,
      paper_id: claim.paper_id,
      text: claim.claim_text,
      citation: claim.citation,
      stance: claim.stance,
      confidence: claim.confidence_score,
    })),
  }))

  // Consecutive links along each stored chain — the same rule the server
  // applies, so the demo field has the same shape a live one would.
  const lineage: GraphLineageEdge[] = []
  for (const cluster of DEMO_CLUSTERS) {
    const chain = (cluster.lineage_tree?.chain ?? []) as { paper_id?: string; relationship?: string }[]
    let previous: string | null = null
    for (const node of chain) {
      const id = node.paper_id
      if (!id || !known.has(id)) continue
      if (previous && previous !== id) {
        lineage.push({
          cluster_id: cluster.id,
          from_paper_id: previous,
          to_paper_id: id,
          relationship: node.relationship ?? 'extends',
        })
      }
      previous = id
    }
  }

  // Zero, not the arithmetic. Every claim the fixtures carry is in a cluster;
  // the per-paper counts above are the numbers the demo run reports, and the
  // fixture only spells out a few claims per cluster. Subtracting one from the
  // other would report the fixture being abridged as a property of the run.

  return {
    query_id: DEMO_QUERY_ID,
    question: DEMO_QUESTION,
    status: 'completed',
    uploaded_corpus: false,
    papers,
    clusters,
    lineage,
    lineage_basis: 'chronological+stance',
    claims_unclustered: 0,
  }
}
