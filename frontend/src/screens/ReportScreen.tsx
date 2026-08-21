/** The report: one section per claim cluster, each with the three axes in the
 *  margin — where the evidence came from, where it disagrees, how far it can be
 *  trusted. The prose is synthesised from a whole cluster, so provenance here is
 *  cluster-level and says so; per-sentence attribution would be invented. */

import { useState, type ReactElement } from 'react'

import { CoverageBar, ProvChip, StanceBar, TierChip, coverageText } from '../components/Evidence'
import { LineageRail } from '../components/Lineage'
import { isTierOverridden } from '../lib/evidence'
import { longDate, score } from '../lib/format'
import { claimRef, driverView } from '../lib/viewmodels'
import { useStore } from '../state/store'

export function ReportScreen(): ReactElement {
  const store = useStore()
  const { report } = store
  const [editingSummary, setEditingSummary] = useState(false)
  const [draft, setDraft] = useState('')
  const [openClaims, setOpenClaims] = useState<Record<string, boolean>>({})

  if (!report) {
    // A finished run with no clusters has no report and never will, which is a
    // different thing from not having run yet — and the reader needs to be told
    // which of the two they are looking at.
    const active = store.queries.find((query) => query.id === store.activeQueryId)
    const ranAndFoundNothing = active?.status === 'completed' && store.clusters.length === 0
    return (
      <div className="screen">
        <div className="kicker" style={{ marginBottom: 14 }}>
          Report
        </div>
        <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>
          {ranAndFoundNothing ? 'Nothing to report.' : 'No report yet.'}
        </h2>
        <p className="dim" style={{ maxWidth: 560 }}>
          {ranAndFoundNothing
            ? 'This run finished without forming any claim clusters, so there was no section to write. Its papers and claims are still on the papers screen.'
            : 'A report is written at the end of a run, one section per cluster. Start a query, or open a completed run from history.'}
        </p>
        <button type="button" className="btn btn-primary" onClick={() => store.go('query')} style={{ fontSize: 13 }}>
          New query
        </button>
      </div>
    )
  }

  const failed = store.papers.filter((paper) => paper.failureReason)
  const sections = report.sections ?? []
  const totalPapers = store.papers.length || sections.reduce((t, s) => t + s.paper_count, 0)
  const totalClaims = sections.reduce((total, section) => total + (section.claims?.length ?? 0), 0)

  return (
    <div style={{ padding: '0 0 110px' }}>
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 5,
          background: 'var(--n-bg)',
          borderBottom: '2px solid var(--n-line2)',
          padding: '14px 56px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div className="faint num" style={{ fontSize: 11.5 }}>
          run {shortId(report.query_id)} · {longDate(report.updated_at)} ·{' '}
          {totalPapers - failed.length} of {totalPapers} papers · {sections.length} clusters ·{' '}
          {totalClaims} claims
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="faint" style={{ fontSize: 11, marginRight: 4 }}>
            Export
          </span>
          <button type="button" className="btn btn-ghost dim" style={exportStyle} onClick={() => store.exportReport('markdown')}>
            Markdown
          </button>
          <button type="button" className="btn btn-ghost dim" style={exportStyle} onClick={() => store.exportReport('json')}>
            JSON
          </button>
          <button type="button" className="btn btn-ghost dim" style={exportStyle} onClick={() => store.exportReport('html')}>
            HTML
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ ...exportStyle, color: 'var(--n-text)', borderColor: 'var(--n-line2)' }}
            onClick={store.downloadPdf}
          >
            PDF
          </button>
        </div>
      </div>

      <div style={{ padding: '64px 56px 0', maxWidth: 1180 }}>
        <div style={{ maxWidth: 760 }}>
          <div className="kicker" style={{ marginBottom: 18 }}>
            Report
          </div>
          <h1
            className="pretty"
            style={{ fontSize: 40, lineHeight: 1.1, letterSpacing: '-.025em', margin: '0 0 14px' }}
          >
            {report.title}
          </h1>
          <div className="dim" style={{ fontSize: 13.5, marginBottom: 34 }}>
            In answer to “{store.question}” · {totalPapers - failed.length} papers · generated{' '}
            {longDate(report.created_at)}
          </div>

          {failed.length > 0 ? (
            <div
              style={{
                border: '1px solid var(--n-line2)',
                borderLeft: '2px solid var(--n-con)',
                padding: '16px 18px',
                marginBottom: 40,
                background: 'var(--n-panel)',
              }}
            >
              <div className="kicker-sm" style={{ color: 'var(--n-con)', marginBottom: 8 }}>
                Built on {totalPapers - failed.length} of {totalPapers} retrieved papers
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                {failed.map((paper) => (
                  <div key={paper.id} style={{ display: 'flex', gap: 10, fontSize: 12.5, lineHeight: 1.45 }}>
                    <span className="faint num" style={{ flex: '0 0 30px' }}>
                      {paper.id.slice(0, 3)}
                    </span>
                    <span style={{ flex: 1 }}>{paper.title}</span>
                    <span className="dim" style={{ flex: '0 0 250px' }}>
                      {paper.failureReason}
                    </span>
                  </div>
                ))}
              </div>
              <div className="dim" style={{ fontSize: 12, marginTop: 10 }}>
                {failed.length === 1 ? 'One paper' : `${failed.length} papers`} failed extraction; the
                run continued on the rest. Every count in this report excludes them.
              </div>
            </div>
          ) : null}

          <div style={{ marginBottom: 44 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
              <div className="kicker">Executive summary</div>
              <button
                type="button"
                className="linkish"
                onClick={() => {
                  if (editingSummary) {
                    store.saveExecutiveSummary(draft)
                    setEditingSummary(false)
                  } else {
                    setDraft(report.executive_summary ?? '')
                    setEditingSummary(true)
                  }
                }}
              >
                {editingSummary ? 'Done' : 'Edit'}
              </button>
              {report.user_edited ? (
                <span
                  className="kicker"
                  style={{ color: 'var(--color-accent-400)', letterSpacing: '.04em' }}
                >
                  user_edited · pinned
                </span>
              ) : null}
            </div>
            {editingSummary ? (
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={8}
                style={{
                  width: '100%',
                  background: 'var(--n-panel)',
                  color: 'var(--n-text)',
                  border: '1px solid var(--color-accent)',
                  fontFamily: 'var(--font-body)',
                  fontSize: 17,
                  lineHeight: 1.62,
                  padding: '14px 16px',
                  outline: 'none',
                  resize: 'vertical',
                }}
              />
            ) : (
              <p
                className="pretty"
                style={{ fontSize: 17.5, lineHeight: 1.62, letterSpacing: '-.005em', margin: 0 }}
              >
                {report.executive_summary}
              </p>
            )}
          </div>

          {report.key_findings?.length ? (
            <div style={{ marginBottom: 52 }}>
              <div className="kicker" style={{ marginBottom: 14 }}>
                Key findings
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {report.key_findings.map((finding, index) => (
                  <div
                    key={index}
                    style={{
                      display: 'flex',
                      gap: 14,
                      fontSize: 15.5,
                      lineHeight: 1.55,
                      paddingBottom: 14,
                      borderBottom: '2px solid var(--n-line2)',
                    }}
                  >
                    <span
                      className="num"
                      style={{
                        color: 'var(--color-accent-400)',
                        fontSize: 12,
                        paddingTop: 4,
                        flex: '0 0 18px',
                      }}
                    >
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <span className="pretty">{finding}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="kicker" style={{ marginBottom: 26 }}>
          Sections · one per claim cluster
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {sections.map((section, sectionIndex) => {
            const cluster = store.clusters.find((c) => c.id === section.cluster_id)
            const tier = cluster?.quality_tier ?? section.quality_tier
            const overridden = isTierOverridden(tier, cluster?.quality_rationale ?? section.quality_rationale)
            const claimsOpen = Boolean(openClaims[section.cluster_id])
            const conflict = section.stance_counts.contradicts >= 2
            const drivers = section.disagreement_drivers.map(driverView)
            const claims = cluster?.claims?.length ? cluster.claims : (section.claims ?? [])

            return (
              <div
                key={section.cluster_id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(0, 760px) 300px',
                  gap: 60,
                  padding: '34px 0',
                  borderTop: '2px solid var(--n-line2)',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                    <span className="faint num" style={{ fontSize: 11 }}>
                      {section.cluster_id.slice(0, 8)}
                    </span>
                    {conflict ? (
                      <span
                        style={{
                          fontSize: 11,
                          letterSpacing: '.04em',
                          textTransform: 'uppercase',
                          color: 'var(--n-con)',
                        }}
                      >
                        papers conflict
                      </span>
                    ) : null}
                    {cluster?.user_edited ? (
                      <span
                        style={{
                          fontSize: 11,
                          letterSpacing: '.04em',
                          textTransform: 'uppercase',
                          color: 'var(--color-accent-400)',
                        }}
                      >
                        user_edited · pinned
                      </span>
                    ) : null}
                  </div>
                  <h3
                    className="pretty"
                    style={{ fontSize: 24, lineHeight: 1.2, letterSpacing: '-.02em', margin: '0 0 12px' }}
                  >
                    {cluster?.central_theme ?? section.heading}
                  </h3>
                  <p
                    className="pretty"
                    style={{ fontSize: 15.5, lineHeight: 1.62, color: 'var(--n-text)', margin: '0 0 16px' }}
                  >
                    {section.narrative}
                  </p>

                  {section.caveats.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
                      {section.caveats.map((caveat, index) => (
                        <div
                          key={index}
                          className="dim"
                          style={{ display: 'flex', gap: 9, fontSize: 13, lineHeight: 1.5 }}
                        >
                          <span className="faint">caveat</span>
                          <span className="pretty">{caveat}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {drivers.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
                      {drivers.map((driver, index) => (
                        <div
                          key={index}
                          style={{
                            display: 'flex',
                            gap: 12,
                            fontSize: 13,
                            lineHeight: 1.5,
                            borderLeft: '1px solid var(--n-line2)',
                            paddingLeft: 12,
                          }}
                        >
                          <span
                            style={{
                              color: 'var(--color-accent-400)',
                              flex: '0 0 116px',
                              fontSize: 11.5,
                              letterSpacing: '.03em',
                              paddingTop: 2,
                            }}
                          >
                            {driver.type}
                          </span>
                          <span className="dim pretty">{driver.description}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <button
                    type="button"
                    className={`claims-toggle${claimsOpen ? ' open' : ''}`}
                    aria-expanded={claimsOpen}
                    onClick={() =>
                      setOpenClaims((current) => ({
                        ...current,
                        [section.cluster_id]: !current[section.cluster_id],
                      }))
                    }
                  >
                    <span className="caret" aria-hidden="true">
                      &#9654;
                    </span>
                    <span>
                      {claimsOpen ? 'Hide the ' : 'Show the '}
                      {claims.length} claims behind this section
                    </span>
                  </button>

                  {claimsOpen ? (
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        marginTop: 8,
                        borderTop: '2px solid var(--n-line2)',
                      }}
                    >
                      <div className="faint pretty" style={{ fontSize: 11, lineHeight: 1.55, padding: '10px 0 12px' }}>
                        Provenance here is cluster-level: the narrative above is synthesised from
                        every claim in the cluster, so no single sentence of it is attributed. These
                        are the claims it was written from.
                      </div>
                      {claims.map((claim, claimIndex) => {
                        const ref = claimRef(sectionIndex, claimIndex, claim.claim_id)
                        return (
                          <div
                            key={claim.claim_id}
                            style={{
                              display: 'grid',
                              gridTemplateColumns: 'minmax(0, 1fr) 150px',
                              gap: 14,
                              padding: '12px 0',
                              borderTop: '1px solid var(--n-line2)',
                              alignItems: 'start',
                            }}
                          >
                            <div style={{ minWidth: 0 }}>
                              <div className="pretty" style={{ fontSize: 13.5, lineHeight: 1.5, marginBottom: 4 }}>
                                {claim.claim_text}
                              </div>
                              <div className="faint num" style={{ fontSize: 11 }}>
                                {claim.citation} · claim {ref}
                              </div>
                            </div>
                            <ProvChip
                              claim={claim}
                              active={store.sourceClaimId === claim.claim_id}
                              onOpen={() => store.openSource(claim, ref)}
                            />
                          </div>
                        )
                      })}
                    </div>
                  ) : null}
                </div>

                <div
                  style={{
                    borderLeft: '2px solid var(--n-line2)',
                    paddingLeft: 22,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 18,
                  }}
                >
                  <div>
                    <div className="kicker-sm" style={{ marginBottom: 7 }}>
                      Quality
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <TierChip tier={tier} overridden={overridden} />
                      <span className="dim num" style={{ fontSize: 12 }}>
                        {score(section.quality_score, 2, 'no score')}
                      </span>
                    </div>
                  </div>

                  <div>
                    <div className="kicker-sm" style={{ marginBottom: 7 }}>
                      Stance · {section.paper_count} papers
                    </div>
                    <StanceBar {...section.stance_counts} height={6} />
                    <div className="dim num" style={{ fontSize: 11.5, marginTop: 6 }}>
                      {section.stance_counts.supports} support · {section.stance_counts.contradicts}{' '}
                      contradict · {section.stance_counts.neutral} neutral
                    </div>
                  </div>

                  <div>
                    <div className="kicker-sm" style={{ marginBottom: 9 }}>
                      Lineage
                    </div>
                    <LineageRail lineage={section.lineage} />
                  </div>

                  <div className="dim" style={{ fontSize: 11.5 }}>
                    {drivers.length
                      ? `${drivers.length} disagreement driver${drivers.length > 1 ? 's' : ''}`
                      : 'no disagreement drivers recorded'}
                  </div>

                  <div>
                    <div className="kicker-sm" style={{ marginBottom: 7 }}>
                      Source coverage
                    </div>
                    <CoverageBar claims={claims} height={5} />
                    <div className="dim num" style={{ fontSize: 11.5, marginTop: 6 }}>
                      {coverageText(claims)}
                    </div>
                  </div>

                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => store.openCluster(section.cluster_id)}
                    style={{
                      color: 'var(--n-text)',
                      whiteSpace: 'nowrap',
                      fontSize: 12,
                      padding: '6px 12px',
                      borderColor: 'var(--n-line2)',
                      alignSelf: 'flex-start',
                    }}
                  >
                    Open cluster
                  </button>
                </div>
              </div>
            )
          })}
        </div>

        {report.open_questions?.length ? (
          <div style={{ maxWidth: 760, marginTop: 54, paddingTop: 34, borderTop: '2px solid var(--n-line2)' }}>
            <div className="kicker" style={{ marginBottom: 14 }}>
              Open questions
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {report.open_questions.map((question, index) => (
                <div key={index} className="dim pretty" style={{ fontSize: 15, lineHeight: 1.58 }}>
                  {question}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 30 }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => store.go('chat')}
                style={{ whiteSpace: 'nowrap', fontSize: 13 }}
              >
                Ask the report
              </button>
              <button
                type="button"
                className="btn btn-ghost dim"
                onClick={() => store.go('edits')}
                style={{ whiteSpace: 'nowrap', fontSize: 13 }}
              >
                Review pinned edits
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

const exportStyle = { whiteSpace: 'nowrap', fontSize: 12, padding: '5px 10px' } as const

function shortId(id: string): string {
  return id.replace(/-/g, '').slice(0, 6)
}
