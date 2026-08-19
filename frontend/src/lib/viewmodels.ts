/** Shapes the screens read. Both data sources — the live socket and the demo
 *  fixtures — produce these, so no screen knows which one it is showing. */

import type {
  ClaimSourceFields,
  DisagreementDriver,
  EventFrame,
  Phase,
  QueryStatus,
} from './types'

export interface ClaimRow extends ClaimSourceFields {
  id: string
  text: string
  citation: string
  /** Cluster this claim ended up in, when it landed in one. */
  clusterId?: string
  ref: string
}

export interface PaperRow {
  id: string
  rank: number
  rankingScore: number | null
  title: string
  authorLine: string
  year: number | null
  venue: string | null
  citationCount: number
  studyType: string | null
  methodology: string | null
  sampleSize: string | null
  claimCount: number
  /** Set when this paper never made it through normalisation or extraction. */
  failureReason: string | null
  claims: ClaimRow[]
}

export interface PhaseStep {
  name: Phase
  state: 'pending' | 'active' | 'done'
  detail: string
}

export type PaperStage = 'queued' | 'active' | 'done' | 'failed'

export interface PaperProgress {
  id: string
  title: string
  stage: PaperStage
  label: string
  meta: string
}

export interface SectionSlot {
  ready: boolean
  heading: string
}

export interface EventLine {
  seq: number
  text: string
  kind: 'normal' | 'high' | 'fail'
}

export interface RunView {
  queryId: string | null
  question: string
  status: QueryStatus
  phase: Phase
  phaseIndex: number
  phases: PhaseStep[]
  elapsedSeconds: number
  papers: PaperProgress[]
  paperTotal: number
  processedCount: number
  failedCount: number
  claimsExtracted: number
  sections: SectionSlot[]
  events: EventLine[]
  complete: boolean
  /** Set when the run stopped early; drives the failure and cancel takeovers. */
  outcome: 'running' | 'completed' | 'failed' | 'cancelled'
  errorMessage: string | null
}

export interface EditEntry {
  field: string
  object: string
  computed: string
  yours: string
  at: string
}

export interface DegradedPaper {
  id: string
  title: string
  reason: string
}

export interface DriverView {
  type: string
  description: string
}

export function driverView(driver: DisagreementDriver): DriverView {
  return {
    type: (driver.driver_type ?? driver.type ?? 'driver').replace(/_/g, ' '),
    description: driver.description,
  }
}

/** "2b · 4f1a90c2…" — a stable, short handle for a claim inside a report.
 *  The marker locates it in the reading order; the id prefix survives a
 *  re-analysis that renumbers the sections. */
export function claimRef(sectionIndex: number, claimIndex: number, claimId: string): string {
  const letters = 'abcdefghijklmnopqrstuvwxyz'
  const marker = `${sectionIndex + 1}${letters[claimIndex] ?? String(claimIndex)}`
  const short = claimId.replace(/-/g, '').slice(0, 8)
  return `${marker} · ${short}…`
}

export function eventLine(frame: EventFrame): EventLine {
  const detail = eventDetail(frame)
  const kind: EventLine['kind'] =
    frame.event === 'paper_failed' || frame.event === 'failed'
      ? 'fail'
      : HIGHLIGHT_EVENTS.has(frame.event)
        ? 'high'
        : 'normal'
  return { seq: frame.seq, text: detail, kind }
}

const HIGHLIGHT_EVENTS = new Set([
  'paper_processed',
  'section_ready',
  'report_ready',
  'clusters_formed',
  'run_completed',
  'pipeline_started',
  'query_structured',
])

function eventDetail(frame: EventFrame): string {
  const bits: string[] = [frame.event]
  for (const key of ['paper_id', 'cluster_id', 'claims', 'count', 'total', 'endpoint', 'title']) {
    const value = frame[key]
    if (value === undefined || value === null) continue
    if (typeof value === 'object') continue
    bits.push(`${key}=${String(value).slice(0, 48)}`)
  }
  return bits.join(' ')
}
