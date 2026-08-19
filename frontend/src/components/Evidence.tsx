/** The small pieces that carry meaning: what a claim's source is worth, which
 *  way a paper leans, how far a cluster can be trusted. They are shared because
 *  they must read identically wherever they appear — report, cluster, papers. */

import type { CSSProperties, ReactElement } from 'react'

import {
  PROV_CLASS,
  PROV_GLYPH,
  coverage,
  provKind,
  provLabel,
  stanceClass,
  tierClass,
} from '../lib/evidence'
import type { ClaimSourceFields, QualityTier, Stance } from '../lib/types'

export function Kicker({ children, style }: { children: React.ReactNode; style?: CSSProperties }): ReactElement {
  return (
    <div className="kicker" style={style}>
      {children}
    </div>
  )
}

export function ProvChip({
  claim,
  active = false,
  onOpen,
}: {
  claim: ClaimSourceFields
  active?: boolean
  onOpen?: () => void
}): ReactElement {
  const kind = provKind(claim)
  return (
    <button
      type="button"
      className={`${PROV_CLASS[kind]}${active ? ' active' : ''}`}
      onClick={onOpen}
      title={provLabel(claim, kind)}
      // A mark, not a bar: it hugs its label even when the grid cell is wider.
      style={{ justifySelf: 'start' }}
    >
      <span aria-hidden="true">{PROV_GLYPH[kind]}</span>
      <span>{provLabel(claim, kind)}</span>
    </button>
  )
}

export function ProvLegend(): ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 14,
        alignItems: 'center',
        marginBottom: 16,
        fontSize: 10.5,
        color: 'var(--n-faint)',
      }}
    >
      <span className="prov prov-verified" style={{ cursor: 'default' }}>¶ verified</span>
      <span className="prov prov-approximate" style={{ cursor: 'default' }}>≈ approximate span</span>
      <span className="prov prov-abstract" style={{ cursor: 'default' }}>§ abstract only</span>
      <span className="prov prov-unavailable" style={{ cursor: 'default' }}>— not locatable</span>
    </div>
  )
}

export function StanceChip({
  stance,
  onFlip,
}: {
  stance: Stance
  onFlip?: () => void
}): ReactElement {
  return (
    <button
      type="button"
      className={stanceClass(stance)}
      onClick={onFlip}
      style={onFlip ? undefined : { cursor: 'default' }}
      title={onFlip ? 'Click to correct this stance' : undefined}
    >
      {stance}
    </button>
  )
}

export function TierChip({
  tier,
  overridden = false,
}: {
  tier: QualityTier
  overridden?: boolean
}): ReactElement {
  return <span className={tierClass(tier, overridden)}>{tier}</span>
}

export function StanceBar({
  supports,
  contradicts,
  neutral,
  height = 6,
}: {
  supports: number
  contradicts: number
  neutral: number
  height?: number
}): ReactElement {
  return (
    <div className="stance-bar" style={{ height }}>
      <i className="sup" style={{ flex: supports }} />
      <i className="con" style={{ flex: contradicts }} />
      <i className="neu" style={{ flex: neutral }} />
    </div>
  )
}

export function CoverageBar({
  claims,
  height = 5,
  width,
}: {
  claims: ClaimSourceFields[]
  height?: number
  width?: number | string
}): ReactElement {
  const { counts } = coverage(claims)
  const seg = (value: number) => ({ flex: value, minWidth: value ? 3 : 0 })
  return (
    <div className="coverage" style={{ height, width }}>
      <div className="cov-verified" style={seg(counts.verified)} />
      <div className="cov-approximate" style={seg(counts.approximate)} />
      <div className="cov-abstract" style={seg(counts.abstract)} />
      <div className="cov-none" style={seg(counts.unavailable)} />
    </div>
  )
}

export function coverageText(claims: ClaimSourceFields[]): string {
  return coverage(claims).text
}
