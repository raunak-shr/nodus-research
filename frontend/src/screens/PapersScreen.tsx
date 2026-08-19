/** The retrieved set, in the order it was ranked.
 *
 *  Rank comes from the structured query — concept overlap, recency and study
 *  design — not from citation count, so the score is shown next to the rank
 *  rather than left implicit. A paper that failed is still listed, dimmed, with
 *  the reason: a silent 17-of-20 would read as a complete search. */

import { useState, type ReactElement } from 'react'

import { CoverageBar, ProvChip, coverageText } from '../components/Evidence'
import { num, score as fmtScore } from '../lib/format'
import { useStore } from '../state/store'

export function PapersScreen(): ReactElement {
  const store = useStore()
  const [openPaper, setOpenPaper] = useState<string | null>(null)

  const read = store.papers.filter((paper) => !paper.failureReason).length

  return (
    <div className="screen">
      <div className="kicker" style={{ marginBottom: 14 }}>
        Papers
      </div>
      <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>
        {store.papers.length} retrieved, ranked, {read} read
      </h2>
      <p className="dim" style={{ maxWidth: 640, margin: '0 0 34px' }}>
        Ranking score comes from the structured query, not from citation count: concept overlap,
        recency and study design. Study type and methodology are read out of the paper during
        normalisation.
      </p>

      {store.papers.length === 0 ? (
        <div className="dim" style={{ maxWidth: 560 }}>
          No papers retrieved yet.
        </div>
      ) : (
        <>
          <div
            className="kicker-sm"
            style={{
              display: 'grid',
              gridTemplateColumns: '52px minmax(0, 1fr) 190px 96px 74px',
              gap: 22,
              paddingBottom: 10,
              borderBottom: '1px solid var(--n-line2)',
            }}
          >
            <div>rank</div>
            <div>title · authors · methodology</div>
            <div>study type</div>
            <div>sample</div>
            <div>claims</div>
          </div>

          {store.papers.map((paper) => {
            const expanded = openPaper === paper.id
            return (
              <div key={paper.id} style={{ display: 'flex', flexDirection: 'column' }}>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '52px minmax(0, 1fr) 190px 96px 74px',
                    gap: 22,
                    padding: '18px 0',
                    borderBottom: '2px solid var(--n-line2)',
                    opacity: paper.failureReason ? 0.55 : 1,
                  }}
                >
                  <div>
                    <div className="num" style={{ fontSize: 13 }}>
                      {String(paper.rank).padStart(2, '0')}
                    </div>
                    <div className="faint num" style={{ fontSize: 11 }}>
                      {fmtScore(paper.rankingScore)}
                    </div>
                    <div
                      style={{
                        height: 2,
                        background: 'var(--color-accent-600)',
                        width: `${((paper.rankingScore ?? 0) * 100).toFixed(0)}%`,
                        marginTop: 5,
                      }}
                    />
                  </div>

                  <div style={{ minWidth: 0 }}>
                    <div className="pretty" style={{ fontSize: 14.5, lineHeight: 1.4, marginBottom: 4 }}>
                      {paper.title}
                    </div>
                    <div className="dim" style={{ fontSize: 12, marginBottom: 5 }}>
                      {paper.authorLine} · {paper.year ?? '—'} · {paper.venue ?? 'venue not recorded'} ·{' '}
                      {num(paper.citationCount)} citations
                    </div>
                    {paper.methodology ? (
                      <div
                        className="faint pretty clamp-3"
                        style={{ fontSize: 12.5, lineHeight: 1.45 }}
                        title={paper.methodology}
                      >
                        {paper.methodology}
                      </div>
                    ) : null}
                    {paper.failureReason ? (
                      <div style={{ fontSize: 12, color: 'var(--n-con)', marginTop: 5 }}>
                        {paper.failureReason}
                      </div>
                    ) : null}
                  </div>

                  <div className="dim" style={{ fontSize: 12.5 }}>
                    {paper.studyType ?? '—'}
                  </div>
                  <div
                    className="dim num clamp-3"
                    style={{ fontSize: 12.5 }}
                    title={paper.sampleSize ?? undefined}
                  >
                    {paper.sampleSize ?? '—'}
                  </div>

                  <div>
                    <div
                      className="num"
                      style={{
                        fontSize: 12,
                        color: paper.failureReason ? 'var(--n-con)' : 'var(--n-dim)',
                      }}
                    >
                      {paper.failureReason ? '—' : `${paper.claimCount} claims`}
                    </div>
                    <div style={{ margin: '6px 0 5px' }}>
                      <CoverageBar claims={paper.claims} height={4} />
                    </div>
                    <div className="faint num" style={{ fontSize: 10.5, lineHeight: 1.4 }}>
                      {paper.claims.length
                        ? coverageText(paper.claims)
                        : paper.failureReason
                          ? 'no claims extracted'
                          : 'provenance not indexed for this paper'}
                    </div>
                    {paper.claims.length ? (
                      <button
                        type="button"
                        className="linkish"
                        style={{ color: 'var(--color-accent-700)', fontSize: 11, paddingTop: 6 }}
                        onClick={() => setOpenPaper(expanded ? null : paper.id)}
                      >
                        {expanded ? 'Hide claim sources' : 'Claim sources'}
                      </button>
                    ) : null}
                  </div>
                </div>

                {expanded ? (
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      padding: '0 0 18px 74px',
                      borderBottom: '2px solid var(--n-line2)',
                    }}
                  >
                    {paper.claims.map((claim) => (
                      <div
                        key={claim.id}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'minmax(0, 1fr) 170px',
                          gap: 16,
                          padding: '12px 0',
                          borderTop: '1px solid var(--n-line2)',
                          alignItems: 'start',
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div className="pretty" style={{ fontSize: 13.5, lineHeight: 1.5, marginBottom: 4 }}>
                            {claim.text}
                          </div>
                          <div className="faint num" style={{ fontSize: 11 }}>
                            claim {claim.ref}
                            {claim.clusterId ? ` · in cluster ${claim.clusterId.slice(0, 8)}` : ''}
                          </div>
                        </div>
                        <ProvChip
                          claim={claim}
                          active={store.sourceClaimId === claim.id}
                          onOpen={() =>
                            store.openSource(
                              {
                                claim_id: claim.id,
                                paper_id: paper.id,
                                claim_text: claim.text,
                                citation: claim.citation,
                                stance: 'supports',
                                similarity_score: null,
                                confidence_score: 0,
                                sample_size: null,
                                source_match: claim.source_match,
                                source_quote: claim.source_quote,
                                source_origin: claim.source_origin,
                                source_section: claim.source_section,
                                source_page: claim.source_page,
                                source_start: claim.source_start,
                                source_end: claim.source_end,
                              },
                              claim.ref,
                            )
                          }
                        />
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}
