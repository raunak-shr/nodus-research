/** Shapes the screens read. Both data sources — the live socket and the demo
 *  fixtures — produce these, so no screen knows which one it is showing. */

import type {
  ChatCitation,
  ChatGrounding,
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
  /** Whether there is a run to show at all.
   *
   *  True from the moment one is asked for, which is before `queryId` is known:
   *  `queries.create` takes a moment to answer, and keying "is there a run" off
   *  the id flashed the no-run screen over a run that had just been started. */
  started: boolean
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
  /** How many sections the server said to expect; 0 while that is unknown. */
  sectionTotal: number
  /** Whether a report was actually written, and so is there to open. */
  reportAvailable: boolean
  /** Why there is no report, when the run finished without writing one. */
  reportNote: string | null
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

/** One turn in the thread on the Ask-the-report screen.
 *
 *  Answers carry where they came from: the blocks cited, whether the report
 *  covered the question at all, and — when there was no backend to answer — that
 *  the passages were matched out of the report rather than written about it. A
 *  reader has to be able to tell those two apart at a glance, so nothing here
 *  is allowed to be inferred from the prose.
 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  at: string
  /** Assistant turns only. False when the report does not answer the question. */
  covered?: boolean
  citations?: ChatCitation[]
  grounding?: ChatGrounding
  /** Quoted out of the report by lexical match, with no model involved. */
  matched?: boolean
  /** The turn is in flight, or the request for it failed. */
  pending?: boolean
  failed?: string | null
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
  'report_skipped',
  'clusters_formed',
  'run_completed',
  'pipeline_started',
  'query_structured',
])

function eventDetail(frame: EventFrame): string {
  const bits: string[] = [frame.event]
  // `reason` and `error` carry why a step produced nothing, which is the one
  // thing worth reading in the stream when a run ends without a report.
  const keys = ['paper_id', 'cluster_id', 'claims', 'count', 'total', 'endpoint', 'title', 'heading', 'stored', 'reason', 'error']
  for (const key of keys) {
    const value = frame[key]
    if (value === undefined || value === null) continue
    if (typeof value === 'object') continue
    bits.push(`${key}=${String(value).slice(0, 48)}`)
  }
  return bits.join(' ')
}
