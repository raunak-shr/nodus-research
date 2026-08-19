/** Where a claim came from and what happened to it since.
 *
 *  Two renderings of one structure: a rail small enough for the report margin,
 *  and the full chain on the cluster screen. A single-paper cluster draws
 *  neither — there is no chain, and pretending otherwise would read as
 *  corroboration that does not exist.
 */

import type { ReactElement } from 'react'

import { lineageColor } from '../lib/evidence'
import { num } from '../lib/format'
import type { LineageTree } from '../lib/types'

export function LineageRail({ lineage }: { lineage: LineageTree | null }): ReactElement {
  const chain = lineage?.chain ?? []
  if (chain.length === 0) {
    return <div className="dim num" style={{ fontSize: 11.5 }}>single paper — no lineage</div>
  }
  const rootYear = lineage?.root_year ?? chain[0]?.year ?? null
  const span = lineage?.span_years ?? null

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 7 }}>
        {chain.map((node, index) => (
          <div
            key={`${node.paper_id ?? index}-${index}`}
            style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0 }}
          >
            <div
              style={{
                height: 1,
                flex: 1,
                background: index === 0 ? 'transparent' : 'var(--n-line2)',
                minWidth: 14,
              }}
            />
            <div
              style={{
                width: 9,
                height: 9,
                flex: '0 0 9px',
                background: lineageColor(node.relationship),
              }}
              title={`${node.relationship ?? 'supports'} · ${node.year ?? ''}`}
            />
          </div>
        ))}
      </div>
      <div className="dim num" style={{ fontSize: 11.5 }}>
        {lineage?.paper_count ?? chain.length} papers
        {rootYear !== null && span !== null ? `, ${rootYear}–${rootYear + span}` : ''}
      </div>
    </>
  )
}

export function LineageChain({ lineage }: { lineage: LineageTree }): ReactElement {
  const chain = lineage.chain ?? []
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {chain.map((node, index) => {
        const color = lineageColor(node.relationship)
        const isLast = index === chain.length - 1
        const cites = typeof node.citation_count === 'number' ? node.citation_count : 0
        return (
          <div
            key={`${node.paper_id ?? index}-${index}`}
            style={{ display: 'grid', gridTemplateColumns: '56px 24px 1fr', minHeight: 78 }}
          >
            <div className="dim num" style={{ fontSize: 12.5, paddingTop: 1 }}>
              {node.year ?? '—'}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div
                style={{
                  width: 11,
                  height: 11,
                  flex: '0 0 11px',
                  background: node.relationship === 'origin' ? color : 'var(--n-bg)',
                  border: `2px solid ${color}`,
                  zIndex: 1,
                }}
              />
              <div
                style={{
                  width: 1,
                  flex: 1,
                  background: isLast ? 'transparent' : 'var(--n-line2)',
                  margin: '2px 0',
                }}
              />
            </div>
            <div style={{ padding: '0 0 26px 16px', minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    padding: '2px 7px',
                    fontSize: 10.5,
                    letterSpacing: '.04em',
                    textTransform: 'uppercase',
                    color,
                    border: `1px solid ${color}`,
                  }}
                >
                  {node.relationship ?? 'supports'}
                </span>
                <span className="faint num" style={{ fontSize: 11 }}>
                  {node.paper_id ?? '—'}
                  {node.claim_id ? ` · claim ${String(node.claim_id).slice(0, 12)}` : ''}
                </span>
              </div>
              <div className="pretty" style={{ fontSize: 14.5, lineHeight: 1.4, marginBottom: 7 }}>
                {node.title ?? 'Untitled'}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, maxWidth: 340 }}>
                <div
                  style={{
                    height: 3,
                    background: color,
                    opacity: 0.5,
                    width: `${Math.max(6, Math.min(100, cites / 25)).toFixed(0)}%`,
                  }}
                />
                <span className="faint num" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                  {num(cites)} citations
                </span>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
