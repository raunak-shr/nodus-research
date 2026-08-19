/** How a claim's provenance is read and displayed.
 *
 *  Four marks, and the difference between them is the whole point: a verified
 *  span was located in the retrieved text, an approximate one was fuzzy-matched
 *  and its boundaries may be wrong, an abstract-only claim has no body text
 *  behind it, and an unlocatable one has a quote and nothing else. Collapsing
 *  them into one "source" link would be a lie about what was checked.
 */

import type {
  ClaimSourceFields,
  ClaimSourceRead,
  ProvKind,
  QualityRationale,
  QualityTier,
  Stance,
} from './types'

export const PROV_GLYPH: Record<ProvKind, string> = {
  verified: '¶',
  approximate: '≈',
  abstract: '§',
  unavailable: '—',
}

export const PROV_CLASS: Record<ProvKind, string> = {
  verified: 'prov prov-verified',
  approximate: 'prov prov-approximate',
  abstract: 'prov prov-abstract',
  unavailable: 'prov prov-unavailable',
}

export function provKind(fields: Pick<ClaimSourceFields, 'source_match' | 'source_origin'>): ProvKind {
  if (fields.source_origin === 'abstract') return 'abstract'
  if (fields.source_match === 'exact' || fields.source_match === 'normalized') return 'verified'
  if (fields.source_match === 'fuzzy') return 'approximate'
  return 'unavailable'
}

export function sourceKind(source: Pick<ClaimSourceRead, 'match' | 'origin'>): ProvKind {
  return provKind({ source_match: source.match, source_origin: source.origin })
}

export function provLabel(fields: ClaimSourceFields, kind = provKind(fields)): string {
  const where = fields.source_section ?? 'source'
  const page = fields.source_page ? ` · p. ${fields.source_page}` : ''
  switch (kind) {
    case 'verified':
      return `${where}${page}`
    case 'approximate':
      return `${where}${page} · approx`
    case 'abstract':
      return 'abstract only'
    default:
      return fields.source_quote ? 'quote, not locatable' : 'no source text'
  }
}

export const KIND_TITLE: Record<ProvKind, string> = {
  verified: 'verified source',
  approximate: 'approximate span',
  abstract: 'abstract only',
  unavailable: 'not locatable',
}

// -- coverage ---------------------------------------------------------------

export interface Coverage {
  counts: Record<ProvKind, number>
  total: number
  /** "9 verified · 2 approximate · 1 abstract-only" */
  text: string
  /** Fraction of claims whose span was actually located. */
  verifiedPct: number
}

export function coverage(claims: ClaimSourceFields[]): Coverage {
  const counts: Record<ProvKind, number> = {
    verified: 0,
    approximate: 0,
    abstract: 0,
    unavailable: 0,
  }
  for (const claim of claims) counts[provKind(claim)] += 1

  const parts: string[] = []
  if (counts.verified) parts.push(`${counts.verified} verified`)
  if (counts.approximate) parts.push(`${counts.approximate} approximate`)
  if (counts.abstract) parts.push(`${counts.abstract} abstract-only`)
  if (counts.unavailable) parts.push(`${counts.unavailable} not locatable`)

  return {
    counts,
    total: claims.length,
    text: parts.join(' · ') || 'no claims',
    verifiedPct: claims.length ? Math.round((counts.verified / claims.length) * 100) : 0,
  }
}

// -- stance and tier --------------------------------------------------------

export function stanceClass(stance: Stance): string {
  return `stance stance-${stance}`
}

export function tierClass(tier: QualityTier, overridden = false): string {
  return `tier tier-${tier}${overridden ? ' tier-overridden' : ''}`
}

export function nextStance(stance: Stance): Stance {
  return stance === 'supports' ? 'contradicts' : stance === 'contradicts' ? 'neutral' : 'supports'
}

export const LINEAGE_COLOR: Record<string, string> = {
  origin: 'var(--color-accent)',
  supports: 'var(--n-sup)',
  extends: 'var(--color-accent-400)',
  contradicts: 'var(--n-con)',
}

export function lineageColor(relationship: string | undefined): string {
  return LINEAGE_COLOR[relationship ?? 'supports'] ?? 'var(--n-sup)'
}

// -- quality arithmetic -----------------------------------------------------

/** Fallbacks for rows written before the rationale carried its own weights. */
const DEFAULT_WEIGHTS: Record<string, number> = {
  design: 0.4,
  sample_size: 0.2,
  corroboration: 0.2,
  extraction_confidence: 0.2,
}

const DEFAULT_THRESHOLDS: Partial<Record<QualityTier, number>> = { high: 0.7, medium: 0.45, low: 0.25 }

/** Subtracted from the weighted sum, never weighted into it. */
const PENALTY_KEY = 'conflict_penalty'

export interface QualityRow {
  key: string
  name: string
  weight: number
  value: number
  contribution: number
}

export interface QualityBreakdown {
  rows: QualityRow[]
  weightedSum: number | null
  penalty: number | null
  penaltyCap: number | null
  score: number | null
  computedTier: QualityTier | null
  /** "high >= 0.70 · medium >= 0.45", as the server set them. */
  thresholds: { tier: QualityTier; at: number }[]
  inputs: { key: string; value: string }[]
}

export function qualityBreakdown(rationale: QualityRationale | null): QualityBreakdown {
  const empty: QualityBreakdown = {
    rows: [],
    weightedSum: null,
    penalty: null,
    penaltyCap: null,
    score: null,
    computedTier: null,
    thresholds: [],
    inputs: [],
  }
  if (!rationale) return empty

  const components = rationale.components ?? {}
  const weights = rationale.weights ?? DEFAULT_WEIGHTS

  const rows: QualityRow[] = Object.entries(components)
    .filter(([key, value]) => key !== PENALTY_KEY && typeof value === 'number')
    .map(([key, value]) => {
      const weight = weights[key] ?? DEFAULT_WEIGHTS[key] ?? 0
      return { key, name: key, weight, value, contribution: value * weight }
    })

  const penalty = typeof components[PENALTY_KEY] === 'number' ? components[PENALTY_KEY] : null
  const penaltyCap =
    typeof weights.conflict_penalty_max === 'number' ? weights.conflict_penalty_max : null

  const weightedSum =
    typeof rationale.weighted_sum === 'number'
      ? rationale.weighted_sum
      : rows.length
        ? rows.reduce((total, row) => total + row.contribution, 0)
        : null

  const score =
    typeof rationale.score === 'number'
      ? rationale.score
      : weightedSum === null
        ? null
        : Math.max(0, weightedSum - (penalty ?? 0))

  const thresholds = rationale.thresholds ?? DEFAULT_THRESHOLDS

  return {
    rows,
    weightedSum,
    penalty,
    penaltyCap,
    score,
    computedTier: rationale.tier ?? (score === null ? null : tierFor(score, thresholds)),
    thresholds: (['high', 'medium', 'low'] as QualityTier[])
      .filter((tier) => typeof thresholds[tier] === 'number')
      .map((tier) => ({ tier, at: thresholds[tier] as number })),
    inputs: rationaleInputs(rationale),
  }
}

/** The tier the score lands in, against whichever bars the server sent. */
export function tierFor(
  score: number,
  thresholds: Partial<Record<QualityTier, number>> = DEFAULT_THRESHOLDS,
): QualityTier {
  if (score >= (thresholds.high ?? 0.7)) return 'high'
  if (score >= (thresholds.medium ?? 0.45)) return 'medium'
  return 'low'
}

const INPUT_KEYS = [
  'study_types',
  'largest_sample_size',
  'paper_count',
  'support_count',
  'contradiction_count',
] as const

function rationaleInputs(rationale: QualityRationale): { key: string; value: string }[] {
  // Newer rows nest these under `inputs`; older ones carry them flat.
  const source: Record<string, unknown> = {
    ...(rationale as Record<string, unknown>),
    ...(rationale.inputs ?? {}),
  }
  const inputs: { key: string; value: string }[] = []
  for (const key of INPUT_KEYS) {
    const raw = source[key]
    if (raw === undefined || raw === null) continue
    inputs.push({ key, value: formatInput(raw) })
  }
  return inputs
}

/** study_types arrives as one entry per claim, so "observational × 4" rather
 *  than the same word repeated four times. */
function formatInput(raw: unknown): string {
  if (Array.isArray(raw)) {
    const counts = new Map<string, number>()
    for (const item of raw) {
      const label = String(item)
      counts.set(label, (counts.get(label) ?? 0) + 1)
    }
    return [...counts]
      .map(([label, count]) => (count > 1 ? `${count} × ${label}` : label))
      .join(', ')
  }
  if (typeof raw === 'number') return raw.toLocaleString('en-US')
  return String(raw)
}

/** Whether the stored tier differs from the one the arithmetic produced. */
export function isTierOverridden(tier: QualityTier, rationale: QualityRationale | null): boolean {
  const computed = rationale?.tier
  return Boolean(computed && computed !== tier)
}
