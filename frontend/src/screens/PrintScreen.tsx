/** The print variant: the same report, set for A4.
 *
 *  It is deliberately its own layout rather than a scaled screenshot of the
 *  screen view — justified measure, footnote marks, and the source list that a
 *  printed page needs because it has no panel to open. The PDF export renders
 *  this same HTML in Chromium, so what is on this page is what prints. */

import type { ReactElement } from 'react'

import { PROV_GLYPH, provKind } from '../lib/evidence'
import { longDate, score } from '../lib/format'
import { claimRef } from '../lib/viewmodels'
import { useStore } from '../state/store'

const INK = '#16181f'
const MUTED = '#5c6070'
const LABEL = '#6a6e7a'
const RULE = '#c9ccd4'
const HAIRLINE = '#dfe1e7'

export function PrintScreen(): ReactElement {
  const store = useStore()
  const report = store.report
  const sections = report?.sections ?? []
  const shown = sections.slice(0, 2)
  const failed = store.papers.filter((paper) => paper.failureReason)
  const pages = Math.max(1, Math.ceil(sections.length * 1.5))

  return (
    <div style={{ padding: '44px 56px 110px', background: 'var(--n-panel2)', minHeight: '100vh' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 26,
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div className="kicker" style={{ marginBottom: 6 }}>
            Print variant
          </div>
          <div style={{ fontSize: 19, letterSpacing: '-.015em' }}>
            A4 · 18 mm margins · the same HTML the PDF export prints
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={store.downloadPdf}
            style={{ color: 'var(--n-text)', whiteSpace: 'nowrap', fontSize: 12, borderColor: 'var(--n-line2)' }}
          >
            Download PDF
          </button>
          <button
            type="button"
            className="btn btn-ghost dim"
            onClick={() => store.exportReport('html')}
            style={{ whiteSpace: 'nowrap', fontSize: 12 }}
          >
            Print-ready HTML
          </button>
        </div>
      </div>

      {!report ? (
        <div className="dim">No report to print yet.</div>
      ) : (
        <div
          style={{
            width: 794,
            maxWidth: '100%',
            minHeight: 1123,
            background: '#ffffff',
            color: INK,
            boxShadow: '0 18px 40px rgba(0,0,0,.35)',
            padding: 68,
            fontSize: '10.5pt',
            lineHeight: 1.5,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              gap: 20,
              whiteSpace: 'nowrap',
              fontSize: '7pt',
              letterSpacing: '.08em',
              textTransform: 'uppercase',
              color: LABEL,
              borderBottom: `.5pt solid ${RULE}`,
              paddingBottom: 8,
              marginBottom: 26,
            }}
          >
            <span>Nodus · run {report.query_id.replace(/-/g, '').slice(0, 6)}</span>
            <span>
              {store.papers.length - failed.length} of {store.papers.length} papers · {sections.length}{' '}
              clusters
            </span>
            <span>
              {longDate(report.updated_at)} · page 1 of {pages}
            </span>
          </div>

          <div
            style={{
              fontFamily: 'var(--font-heading)',
              fontSize: '20pt',
              lineHeight: 1.15,
              letterSpacing: '-.02em',
              marginBottom: 8,
            }}
          >
            {report.title}
          </div>
          <div style={{ fontSize: '8.5pt', color: MUTED, marginBottom: 24 }}>
            {store.question} · {store.papers.length - failed.length} papers
          </div>

          <SheetLabel>Executive summary</SheetLabel>
          <div style={{ marginBottom: 22, textAlign: 'justify', hyphens: 'auto' }}>
            {report.executive_summary}
          </div>

          {failed.length ? (
            <div
              style={{
                border: `.5pt solid ${RULE}`,
                padding: '10px 12px',
                marginBottom: 24,
                fontSize: '8.5pt',
                color: '#3d414d',
              }}
            >
              <strong style={{ fontWeight: 600 }}>
                Built on {store.papers.length - failed.length} of {store.papers.length} retrieved
                papers.
              </strong>{' '}
              {failed.map((paper) => `${paper.id} (${paper.failureReason})`).join(', ')} failed
              extraction; the run continued without them.
            </div>
          ) : null}

          {shown.map((section, index) => (
            <div key={section.cluster_id}>
              <SheetLabel>
                {index + 1} · {section.heading}
              </SheetLabel>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(0, 1fr) 150px',
                  gap: 20,
                  paddingBottom: 16,
                  borderBottom: `.5pt solid ${HAIRLINE}`,
                  marginBottom: 16,
                }}
              >
                <div style={{ textAlign: 'justify', hyphens: 'auto' }}>{section.narrative}</div>
                <div style={{ fontSize: '8pt', color: '#3d414d' }}>
                  <div
                    style={{
                      border: `.5pt solid ${INK}`,
                      display: 'inline-block',
                      padding: '1px 6px',
                      letterSpacing: '.06em',
                      textTransform: 'uppercase',
                      fontSize: '6.5pt',
                      whiteSpace: 'nowrap',
                      marginBottom: 8,
                    }}
                  >
                    quality {section.quality_tier}
                    {section.quality_score == null ? '' : ` · ${score(section.quality_score)}`}
                  </div>
                  <div style={{ display: 'flex', height: 4, marginBottom: 5 }}>
                    <div style={{ flex: section.stance_counts.supports, background: '#33735a' }} />
                    <div style={{ flex: section.stance_counts.contradicts, background: '#a05437' }} />
                    <div style={{ flex: section.stance_counts.neutral, background: '#8b8fa3' }} />
                  </div>
                  <div>
                    {section.stance_counts.supports} support · {section.stance_counts.contradicts}{' '}
                    contradict
                    {section.stance_counts.neutral ? ` · ${section.stance_counts.neutral} neutral` : ''}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    {section.lineage?.chain?.length
                      ? `Lineage ${section.lineage.root_year}→${(section.lineage.root_year ?? 0) + (section.lineage.span_years ?? 0)}, ${section.lineage.paper_count ?? section.lineage.chain.length} papers`
                      : 'Single paper — no lineage'}
                  </div>
                  <div>
                    {section.disagreement_drivers.length
                      ? `${section.disagreement_drivers.length} disagreement drivers`
                      : 'no disagreement drivers'}
                  </div>
                </div>
              </div>
            </div>
          ))}

          <div
            style={{
              fontSize: '7.5pt',
              letterSpacing: '.09em',
              textTransform: 'uppercase',
              color: LABEL,
              borderTop: `.5pt solid ${RULE}`,
              paddingTop: 10,
              marginBottom: 8,
            }}
          >
            Sources for sections 1–{shown.length}
          </div>
          <div
            style={{
              fontSize: '8pt',
              lineHeight: 1.45,
              color: '#3d414d',
              display: 'flex',
              flexDirection: 'column',
              gap: 7,
              marginBottom: 18,
            }}
          >
            {shown.flatMap((section, sectionIndex) =>
              section.claims.map((claim, claimIndex) => {
                const kind = provKind(claim)
                const ref = claimRef(sectionIndex, claimIndex, claim.claim_id)
                return (
                  <div key={claim.claim_id}>
                    <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 600 }}>
                      {ref.split(' · ')[0]}
                    </span>{' '}
                    <span
                      style={{
                        border: kind === 'approximate' ? `.5pt dashed ${LABEL}` : `.5pt solid ${INK}`,
                        borderLeft: kind === 'abstract' ? `1.5pt solid ${INK}` : undefined,
                        borderBottom: kind === 'unavailable' ? `.5pt dotted ${LABEL}` : undefined,
                        padding: kind === 'unavailable' ? 0 : '0 3px',
                        fontSize: '6.5pt',
                        letterSpacing: '.06em',
                        textTransform: 'uppercase',
                      }}
                    >
                      {PROV_GLYPH[kind]} {kind}
                    </span>{' '}
                    {claim.citation}
                    {claim.source_section ? ` · ${claim.source_section}` : ''}
                    {claim.source_page ? `, p. ${claim.source_page}` : ''}
                    {claim.source_quote ? ` — “${claim.source_quote}”` : ''}
                  </div>
                )
              }),
            )}
          </div>

          <div style={{ fontSize: '8pt', color: MUTED, borderTop: `.5pt solid ${RULE}`, paddingTop: 8 }}>
            Sections {shown.length + 1}–{sections.length}, member claims, lineage chains and quality
            arithmetic continue on the following pages. Overridden values are printed beside the
            computed ones, and every claim carries its source footnote in the same four marks used
            above.
          </div>
        </div>
      )}
    </div>
  )
}

function SheetLabel({ children }: { children: React.ReactNode }): ReactElement {
  return (
    <div
      style={{
        fontSize: '7.5pt',
        letterSpacing: '.09em',
        textTransform: 'uppercase',
        color: LABEL,
        marginBottom: 9,
      }}
    >
      {children}
    </div>
  )
}
