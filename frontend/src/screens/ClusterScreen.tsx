/** One cluster, in full: the claims that were grouped, why they disagree, and
 *  the arithmetic behind the quality tier. Every input to the score is shown so
 *  the tier can be argued with — and overridden, with the computed value kept. */

import { useState, type ReactElement } from 'react'

import { CoverageBar, ProvChip, ProvLegend, StanceBar, TierChip, coverageText } from '../components/Evidence'
import { LineageChain } from '../components/Lineage'
import { isTierOverridden, nextStance, qualityBreakdown } from '../lib/evidence'
import { num, score as fmtScore } from '../lib/format'
import { claimRef, driverView } from '../lib/viewmodels'
import type { QualityTier } from '../lib/types'
import { useStore } from '../state/store'

const TIERS: QualityTier[] = ['high', 'medium', 'low', 'unrated']

export function ClusterScreen(): ReactElement {
  const store = useStore()
  const [tierPanelOpen, setTierPanelOpen] = useState(false)

  const cluster =
    store.clusters.find((c) => c.id === store.activeClusterId) ?? store.clusters[0] ?? null

  if (!cluster) {
    return (
      <div className="screen">
        <div className="kicker" style={{ marginBottom: 14 }}>
          Cluster
        </div>
        <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>
          No clusters yet.
        </h2>
        <p className="dim" style={{ maxWidth: 560 }}>
          Clusters are formed after every paper has been read, so they appear at the end of a run.
        </p>
      </div>
    )
  }

  const clusterIndex = store.clusters.findIndex((c) => c.id === cluster.id)
  const breakdown = qualityBreakdown(cluster.quality_rationale)
  const overridden = isTierOverridden(cluster.quality_tier, cluster.quality_rationale)
  const drivers = (cluster.disagreement_drivers ?? []).map(driverView)
  const claims = cluster.claims ?? []
  const panelOpen = Boolean(store.source || store.sourceClaimId)

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '250px minmax(0, 1fr)', minHeight: '100vh' }}>
      <div
        className="n-scroll"
        style={{
          borderRight: '2px solid var(--n-line2)',
          padding: '26px 0',
          position: 'sticky',
          top: 0,
          height: '100vh',
          overflow: 'auto',
        }}
      >
        <div className="kicker-sm" style={{ padding: '0 14px', marginBottom: 12 }}>
          Clusters · {store.clusters.length}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {store.clusters.map((item) => (
            <button
              key={item.id}
              type="button"
              className="hover-row"
              onClick={() => store.openCluster(item.id)}
              style={{
                textAlign: 'left',
                border: 0,
                background: item.id === cluster.id ? 'var(--n-panel2)' : 'transparent',
                borderLeft: `2px solid ${item.id === cluster.id ? 'var(--color-accent)' : 'transparent'}`,
                color: item.id === cluster.id ? 'var(--n-text)' : 'var(--n-dim)',
                fontFamily: 'var(--font-body)',
                fontSize: 12.5,
                lineHeight: 1.35,
                padding: '9px 12px',
                cursor: 'pointer',
                width: '100%',
              }}
            >
              {item.central_theme}
            </button>
          ))}
        </div>
      </div>

      <div
        className="cluster-body"
        style={{
          padding: '52px 56px 110px',
          maxWidth: panelOpen ? 1440 : 1000,
          paddingRight: panelOpen ? 'calc(clamp(320px, 26vw, 440px) + 56px)' : 56,
        }}
      >
        <div className="kicker" style={{ marginBottom: 16 }}>
          Cluster {cluster.id.slice(0, 8)} · {new Set(claims.map((c) => c.paper_id)).size} papers
        </div>
        <textarea
          className="title-input"
          rows={1}
          value={cluster.central_theme}
          onChange={(event) => store.renameCluster(cluster.id, event.target.value)}
          ref={(node) => {
            // A theme runs to a full sentence, so the field grows to fit rather
            // than scrolling a one-line input the reader cannot see the end of.
            if (!node) return
            node.style.height = 'auto'
            node.style.height = `${node.scrollHeight}px`
          }}
        />
        <div className="faint" style={{ fontSize: 11.5, marginBottom: 26 }}>
          Click the heading to retitle it. An edited cluster is pinned and survives re-analysis.
        </div>
        <p className="pretty" style={{ fontSize: 16, lineHeight: 1.62, maxWidth: 760, margin: '0 0 46px' }}>
          {cluster.consensus_summary}
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: panelOpen ? '1fr' : '1fr 1fr',
            gap: 44,
            marginBottom: 52,
          }}
        >
          <div>
            <div className="kicker" style={{ marginBottom: 16 }}>
              Disagreement
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 10 }}>
              <div className="num" style={{ fontSize: 29, letterSpacing: '-.02em' }}>
                {cluster.support_count} / {cluster.contradiction_count} / {cluster.neutral_count}
              </div>
              <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.4 }}>
                supports / contradicts
                <br />/ neutral
              </div>
            </div>
            <div style={{ marginBottom: 22 }}>
              <StanceBar
                supports={cluster.support_count}
                contradicts={cluster.contradiction_count}
                neutral={cluster.neutral_count}
                height={8}
              />
            </div>

            {drivers.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {drivers.map((driver, index) => (
                  <div key={index}>
                    <div
                      style={{
                        fontSize: 11.5,
                        letterSpacing: '.05em',
                        textTransform: 'uppercase',
                        color: 'var(--color-accent-400)',
                        marginBottom: 5,
                      }}
                    >
                      {driver.type}
                    </div>
                    <div className="dim pretty" style={{ fontSize: 13.5, lineHeight: 1.55 }}>
                      {driver.description}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div
                className="dim"
                style={{
                  border: '1px dashed var(--n-line2)',
                  padding: '16px 18px',
                  fontSize: 13.5,
                  lineHeight: 1.55,
                }}
              >
                No disagreement drivers were recorded. The papers in this cluster do not conflict on
                method, population or metric — they simply do not overlap enough to conflict. Read the
                quality tier, not agreement, as the finding here.
              </div>
            )}
          </div>

          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 16,
              }}
            >
              <div className="kicker">Quality · deterministic</div>
              <button type="button" className="linkish" onClick={() => setTierPanelOpen((v) => !v)}>
                Override tier
              </button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <TierChip tier={cluster.quality_tier} overridden={overridden} />
              <span className="num" style={{ fontSize: 29, letterSpacing: '-.02em' }}>
                {fmtScore(cluster.quality_score)}
              </span>
            </div>

            {overridden ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  borderLeft: '2px solid var(--color-accent)',
                  padding: '8px 0 8px 12px',
                  marginBottom: 16,
                }}
              >
                <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                  The model said {cluster.quality_rationale?.tier}
                  {typeof breakdown.score === 'number' ? ` (${breakdown.score.toFixed(2)})` : ''}. You
                  said {cluster.quality_tier}.
                  <br />
                  <span className="faint">
                    The computed value is kept beside yours; nothing is overwritten. user_edited ·
                    pinned
                  </span>
                </div>
                <button
                  type="button"
                  className="linkish dim"
                  onClick={() => store.clearTierOverride(cluster.id)}
                  style={{ flex: '0 0 auto' }}
                >
                  Revert
                </button>
              </div>
            ) : null}

            {tierPanelOpen ? (
              <div
                style={{
                  border: '1px solid var(--n-line2)',
                  background: 'var(--n-panel)',
                  padding: '14px 16px',
                  marginBottom: 16,
                }}
              >
                <div className="dim" style={{ fontSize: 12, marginBottom: 10 }}>
                  Set the tier by hand. The computed score stays on record.
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {TIERS.map((tier) => (
                    <button
                      key={tier}
                      type="button"
                      onClick={() => {
                        store.overrideTier(cluster.id, tier)
                        setTierPanelOpen(false)
                      }}
                      style={{
                        border: `1px solid ${cluster.quality_tier === tier ? 'var(--color-accent)' : 'var(--n-line2)'}`,
                        background: 'transparent',
                        color: cluster.quality_tier === tier ? 'var(--n-text)' : 'var(--n-dim)',
                        padding: '6px 12px',
                        fontFamily: 'var(--font-body)',
                        fontSize: 12.5,
                        cursor: 'pointer',
                      }}
                    >
                      {tier}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {breakdown.rows.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 18 }}>
                {breakdown.rows.map((row) => (
                  <div key={row.key}>
                    <div
                      className="num"
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'baseline',
                        fontSize: 12,
                        marginBottom: 5,
                      }}
                    >
                      <span>
                        {row.name} <span className="faint">× {row.weight.toFixed(2)}</span>
                      </span>
                      <span className="dim">
                        {row.value.toFixed(2)} → {row.contribution.toFixed(3)}
                      </span>
                    </div>
                    <div style={{ height: 6, background: 'var(--n-panel2)', width: '100%', overflow: 'hidden' }}>
                      <div
                        style={{
                          height: 6,
                          background: 'var(--color-accent-600)',
                          width: `${(row.value * 100).toFixed(0)}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
                <div
                  className="num"
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 12,
                    paddingTop: 10,
                    borderTop: '2px solid var(--n-line2)',
                  }}
                >
                  <span className="dim">weighted sum</span>
                  <span>{fmtScore(breakdown.weightedSum, 3)}</span>
                </div>
                {breakdown.penalty !== null ? (
                  <div className="num" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span className="dim">
                      conflict_penalty
                      {breakdown.penaltyCap === null ? '' : ` (max ${fmtScore(breakdown.penaltyCap)})`}
                    </span>
                    <span style={{ color: breakdown.penalty > 0 ? 'var(--n-con)' : 'var(--n-dim)' }}>
                      − {fmtScore(breakdown.penalty)}
                    </span>
                  </div>
                ) : null}
                <div
                  className="num"
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 13,
                    paddingTop: 10,
                    borderTop: '1px solid var(--n-line2)',
                  }}
                >
                  <span>quality_score</span>
                  <span>{fmtScore(breakdown.score)}</span>
                </div>
                <div className="faint num" style={{ fontSize: 11.5 }}>
                  {breakdown.thresholds.length
                    ? `thresholds — ${breakdown.thresholds
                        .map((t) => `${t.tier} ≥ ${fmtScore(t.at)}`)
                        .join(' · ')} · `
                    : ''}
                  computed tier {breakdown.computedTier ?? '—'}
                </div>
              </div>
            ) : (
              <div className="dim" style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 18 }}>
                No score was computed for this cluster. With one paper there is no corroboration term,
                so Nodus leaves the tier unrated rather than inferring one.
              </div>
            )}

            {breakdown.inputs.length ? (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '170px 1fr',
                  gap: 1,
                  borderTop: '2px solid var(--n-line2)',
                  fontSize: 12.5,
                }}
              >
                {breakdown.inputs.map((input) => (
                  <div key={input.key} style={{ display: 'contents' }}>
                    <div
                      className="faint"
                      style={{ padding: '8px 0', borderBottom: '2px solid var(--n-line2)', fontSize: 11.5 }}
                    >
                      {input.key}
                    </div>
                    <div className="dim" style={{ padding: '8px 0', borderBottom: '2px solid var(--n-line2)' }}>
                      {input.value}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <div style={{ marginBottom: 52 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 22 }}>
            <div className="kicker">Lineage</div>
            <div className="faint num" style={{ fontSize: 11.5 }}>
              {cluster.lineage_tree
                ? `root ${cluster.lineage_tree.root_paper_id ?? '—'} · ${cluster.lineage_tree.root_year ?? '—'} · span ${cluster.lineage_tree.span_years ?? '—'} years · ${cluster.lineage_tree.paper_count ?? cluster.lineage_tree.chain?.length ?? 0} papers`
                : ''}
            </div>
          </div>
          {cluster.lineage_tree ? (
            <LineageChain lineage={cluster.lineage_tree} />
          ) : (
            <div
              className="dim"
              style={{
                border: '1px dashed var(--n-line2)',
                padding: '18px 20px',
                maxWidth: 620,
                fontSize: 13.5,
                lineHeight: 1.6,
              }}
            >
              One paper, so there is no chain to draw and no corroboration term to score. Nodus
              records the origin and stops:{' '}
              <span style={{ color: 'var(--n-text)' }}>
                {claims[0]?.paper_id} · {claims[0]?.citation} · origin
              </span>
              . Nothing in the retrieved set cites, replicates or contests it.
            </div>
          )}
        </div>

        <div>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              marginBottom: 10,
              gap: 16,
              flexWrap: 'wrap',
            }}
          >
            <div className="kicker">Member claims</div>
            <div className="faint" style={{ fontSize: 11.5 }}>
              Click a stance to flip it · click a source mark to read the sentence it came from
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              marginBottom: 16,
              paddingBottom: 12,
              borderBottom: '2px solid var(--n-line2)',
              flexWrap: 'wrap',
            }}
          >
            <div className="kicker-sm" style={{ whiteSpace: 'nowrap' }}>
              Source coverage
            </div>
            <CoverageBar claims={claims} height={6} width={180} />
            <div className="dim num" style={{ fontSize: 11.5 }}>
              {coverageText(claims)}
            </div>
            <div className="faint num" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
              {claims.length} claims
            </div>
          </div>

          <ProvLegend />

          <div
            className="kicker-sm"
            style={{
              display: 'grid',
              gridTemplateColumns: claimColumns(panelOpen),
              gap: 16,
              padding: '0 0 8px',
              borderBottom: '1px solid var(--n-line2)',
            }}
          >
            <div>claim_text · citation</div>
            <div>stance · source</div>
            {panelOpen ? null : (
              <>
                <div style={{ textAlign: 'right' }}>confidence</div>
                <div style={{ textAlign: 'right' }}>sample</div>
              </>
            )}
            <div />
          </div>

          {claims.map((claim, index) => {
            const ref = claimRef(clusterIndex, index, claim.claim_id)
            return (
              <div
                key={claim.claim_id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: claimColumns(panelOpen),
                  gap: 16,
                  alignItems: 'start',
                  padding: '16px 0',
                  borderBottom: '2px solid var(--n-line2)',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div className="pretty" style={{ fontSize: 14.5, lineHeight: 1.5, marginBottom: 5 }}>
                    {claim.claim_text}
                  </div>
                  <div className="faint num" style={{ fontSize: 11.5 }}>
                    {claim.citation} · claim {ref}
                    {claim.similarity_score == null
                      ? ''
                      : ` · similarity ${fmtScore(claim.similarity_score)}`}
                    {panelOpen
                      ? ` · confidence ${fmtScore(claim.confidence_score)} · ${claim.sample_size ?? 'sample not reported'}`
                      : ''}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
                  <button
                    type="button"
                    className={`stance stance-${claim.stance}`}
                    onClick={() => store.flipStance(cluster.id, claim.claim_id, nextStance(claim.stance))}
                  >
                    {claim.stance}
                  </button>
                  <ProvChip
                    claim={claim}
                    active={store.sourceClaimId === claim.claim_id}
                    onOpen={() => store.openSource(claim, ref)}
                  />
                </div>
                {panelOpen ? null : (
                  <>
                    <div className="dim num" style={{ fontSize: 12.5, textAlign: 'right' }}>
                      {fmtScore(claim.confidence_score)}
                    </div>
                    <div className="dim num" style={{ fontSize: 12.5, textAlign: 'right' }}>
                      {claim.sample_size ?? '—'}
                    </div>
                  </>
                )}
                <button
                  type="button"
                  className="icon-btn"
                  title="Move this claim to another cluster"
                  onClick={() => store.setFlag('moved')}
                >
                  ⇄
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {store.flag === 'moved' ? <MoveClaimSheet /> : null}
    </div>
  )
}

function claimColumns(panelOpen: boolean): string {
  return panelOpen ? 'minmax(240px, 1fr) 152px 30px' : 'minmax(0, 1fr) 152px 96px 84px 30px'
}

function MoveClaimSheet(): ReactElement {
  const store = useStore()
  const target = store.clusters.find((c) => c.id !== store.activeClusterId)
  return (
    <div
      className="elev-lg"
      style={{
        position: 'fixed',
        bottom: 26,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 30,
        background: 'var(--n-panel)',
        border: '1px solid var(--n-line2)',
        padding: '16px 18px',
        width: 520,
        maxWidth: 'calc(100vw - 48px)',
      }}
    >
      <div className="kicker-sm" style={{ marginBottom: 8 }}>
        Move claim
      </div>
      <div style={{ fontSize: 13.5, lineHeight: 1.5, marginBottom: 12 }}>
        Reassign this claim to another cluster, or pull it out into a cluster of its own. Both objects
        are marked <span style={{ color: 'var(--color-accent-400)' }}>user_edited</span> and pinned,
        and the clusters&rsquo; scores recompute from the new membership.
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => store.setFlag(null)}
          style={{ whiteSpace: 'nowrap', fontSize: 12 }}
        >
          Move to {target ? `${target.id.slice(0, 6)} — ${target.central_theme.slice(0, 28)}…` : 'another cluster'}
        </button>
        <button type="button" className="btn btn-ghost dim" onClick={() => store.setFlag(null)} style={{ fontSize: 12 }}>
          New cluster
        </button>
        <button type="button" className="btn btn-ghost dim" onClick={() => store.setFlag(null)} style={{ fontSize: 12 }}>
          Cancel
        </button>
      </div>
      <div className="faint num" style={{ fontSize: 11, marginTop: 10 }}>
        {num(store.clusters.length)} clusters in this run
      </div>
    </div>
  )
}
