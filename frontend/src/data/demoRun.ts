/** The demo run: a report assembled from the corpus, the history rows around it,
 *  and a clock that replays the pipeline so the live-run screen has something to
 *  show without a backend. Timings mirror a real 4-minute run, compressed. */

import type { EventLine, PaperProgress, PaperStage, PhaseStep, RunView, SectionSlot } from '../lib/viewmodels'
import type { Phase, QueryRead, ReportRead, ReportSection } from '../lib/types'
import { PHASE_ORDER } from '../lib/types'
import {
  DEMO_CAVEATS,
  DEMO_CLUSTERS,
  DEMO_FAILURES,
  DEMO_PAPERS,
  DEMO_QUERY_ID,
  DEMO_SECTION_HEADINGS,
} from './demoCorpus'

export const DEMO_QUESTION = 'Does aerobic exercise reduce depression severity?'

// -- report -----------------------------------------------------------------

const NARRATIVES: Record<string, string> = {
  c1: 'Eleven papers estimate the effect of supervised aerobic exercise against non-exercise control conditions in adults meeting diagnostic criteria for depression. Pooled standardised mean differences cluster between −0.62 and −0.79, a moderate effect comparable in magnitude to that reported for first-line pharmacotherapy in the same populations.',
  c2: 'Four papers report that restricting analysis to trials with blinded outcome assessors and intention-to-treat data reduces the pooled effect to a small, sometimes non-significant value. Three papers disagree, holding that the reduction is an artefact of restricting to a handful of small trials. The disagreement is not about the data but about which subset licenses a conclusion.',
  c3: 'Dose is the one moderator that survives across papers. The dedicated dose-response trial found public-health-dose exercise clearly superior to a low dose that performed like the placebo control, and three pooled analyses recover frequency or intensity as a moderator — always confounded with supervision.',
  c4: 'Three papers touch late-life depression. One randomised trial reports larger remission in the exercise arm, and two pooled analyses report age as a non-significant moderator. Neither pooled paper reports an age-stratified estimate, so “comparable” rests on the absence of a moderator effect rather than on a measured one.',
  c5: 'One small trial addresses treatment-resistant depression directly: 33 patients on stable pharmacotherapy, half assigned to walking five days a week. Nothing in the retrieved set replicates or contests it, so the cluster has no corroboration term to score.',
  c6: 'Whether the benefit persists past the intervention period is the least settled question in the retrieved set. The one-year SMILE follow-up reports continued advantage for those who kept exercising, which two papers read as selection rather than effect.',
}

const DEMO_SECTIONS: ReportSection[] = DEMO_CLUSTERS.map((cluster, index) => ({
  cluster_id: cluster.id,
  heading: DEMO_SECTION_HEADINGS[index] ?? cluster.central_theme,
  narrative: NARRATIVES[cluster.id] ?? cluster.consensus_summary ?? '',
  caveats: DEMO_CAVEATS[cluster.id] ?? [],
  central_theme: cluster.central_theme,
  quality_tier: cluster.quality_tier,
  quality_score: cluster.quality_score,
  quality_rationale: cluster.quality_rationale,
  stance_counts: {
    supports: cluster.support_count,
    contradicts: cluster.contradiction_count,
    neutral: cluster.neutral_count,
  },
  paper_count: new Set(cluster.claims.map((claim) => claim.paper_id)).size,
  lineage: cluster.lineage_tree,
  disagreement_drivers: cluster.disagreement_drivers ?? [],
  claims: cluster.claims,
}))

export const DEMO_REPORT: ReportRead = {
  id: 'report-demo',
  query_id: DEMO_QUERY_ID,
  title: 'Aerobic exercise and depression severity: a moderate effect, contested at the method',
  executive_summary:
    'Across seventeen papers the evidence supports a moderate antidepressant effect of aerobic exercise in adults with a depressive disorder, and the papers that dispute it dispute the method rather than the direction. The pooled estimate sits near SMD −0.62 to −0.79 against non-exercise controls, comparable to first-line pharmacotherapy in the same trials. The largest single qualification is assessor blinding: restricting to blinded, intention-to-treat trials cuts the estimate to roughly −0.18, and four of seven papers in that cluster treat this as the defensible number. Dose survives as the one reproducible moderator; durability past the intervention period does not.',
  key_findings: [
    'Seventeen papers report a moderate reduction in depression severity for aerobic exercise against non-exercise control (SMD −0.62 to −0.79).',
    'Restricting to blinded-assessor, intention-to-treat trials reduces the pooled estimate to about SMD −0.18; four papers treat this as the defensible figure and three dispute the restriction.',
    'Frequency of three or more supervised sessions per week is the only moderator recovered by more than two papers, and it is confounded with supervision in all of them.',
    'No cluster supports a claim of maintained benefit twelve months after the intervention ends.',
  ],
  open_questions: [
    'No retrieved trial randomises session frequency independently of supervision, so dose and contact time cannot be separated.',
    'Treatment-resistant depression rests on a single 33-participant trial; the cluster is left unrated for want of corroboration.',
    'Late-life effects are inferred from null moderator tests rather than age-stratified estimates.',
  ],
  sections: DEMO_SECTIONS,
  llm_model_used: 'gpt-5.1',
  user_edited: false,
  created_at: '2026-08-18T09:45:00Z',
  updated_at: '2026-08-18T09:45:00Z',
}

// -- history ----------------------------------------------------------------

function isoToday(hour: number, minute: number, dayOffset = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + dayOffset)
  d.setHours(hour, minute, 0, 0)
  return d.toISOString()
}

export const DEMO_QUERIES: QueryRead[] = [
  {
    id: DEMO_QUERY_ID,
    raw_query: DEMO_QUESTION,
    structured_query: {
      topic: 'Aerobic exercise as an intervention for depressive disorders',
      outcome_measure: 'Change in depression severity score (HAM-D, BDI-II, PHQ-9), standardised mean difference',
      core_concepts: ['aerobic exercise', 'depression severity', 'randomised controlled trial', 'symptom reduction'],
      search_keywords: [
        'aerobic exercise depression RCT',
        'exercise antidepressant effect',
        'physical activity major depressive disorder',
        'exercise dose response depression',
      ],
      clarification_needed: false,
      clarification_message: null,
    },
    status: 'completed',
    paper_count: 17,
    error_message: null,
    parent_query_id: null,
    created_at: isoToday(9, 41),
    updated_at: isoToday(9, 45),
  },
  {
    id: '7b19d000-0000-4000-8000-000000000002',
    raw_query: 'Does the effect hold in trials with blinded outcome assessment?',
    structured_query: null,
    status: 'completed',
    paper_count: 9,
    error_message: null,
    parent_query_id: DEMO_QUERY_ID,
    created_at: isoToday(10, 6),
    updated_at: isoToday(10, 8),
  },
  {
    id: '6a0e7700-0000-4000-8000-000000000003',
    raw_query: 'Does time-restricted eating improve HbA1c in type 2 diabetes?',
    structured_query: null,
    status: 'processing',
    paper_count: 18,
    error_message: null,
    parent_query_id: null,
    created_at: isoToday(10, 22),
    updated_at: isoToday(10, 24),
  },
  {
    id: '5c88ab00-0000-4000-8000-000000000004',
    raw_query: 'Is exercise good?',
    structured_query: null,
    status: 'failed',
    paper_count: 0,
    error_message: 'upstream 502 from the search provider after 4 attempts (backoff 1s, 2s, 4s, 8s)',
    parent_query_id: null,
    created_at: isoToday(17, 52, -1),
    updated_at: isoToday(17, 52, -1),
  },
]

export const DEMO_STATS: Record<string, { clusters: number; claims: number; duration: string }> = {
  [DEMO_QUERY_ID]: { clusters: 6, claims: 143, duration: '4 m 12 s' },
  '7b19d000-0000-4000-8000-000000000002': { clusters: 2, claims: 24, duration: '1 m 48 s' },
  '6a0e7700-0000-4000-8000-000000000003': { clusters: 0, claims: 61, duration: '2 m 31 s' },
  '5c88ab00-0000-4000-8000-000000000004': { clusters: 0, claims: 0, duration: '0 m 14 s' },
}

// -- the run clock ----------------------------------------------------------

/** Tick at which each phase begins. The run finishes at tick 106. */
const PHASE_AT: { name: Phase; at: number }[] = [
  { name: 'queued', at: 0 },
  { name: 'structuring', at: 3 },
  { name: 'retrieving', at: 9 },
  { name: 'ranking', at: 17 },
  { name: 'storing', at: 21 },
  { name: 'processing', at: 24 },
  { name: 'clustering', at: 74 },
  { name: 'synthesizing', at: 84 },
  { name: 'completed', at: 106 },
]

const SECTION_AT = [86, 90, 93, 96, 99, 102]

export const DEMO_RUN_TICKS = 108
export const DEMO_TICK_MS = 320

function phaseIndexAt(tick: number): number {
  let index = 0
  PHASE_AT.forEach((phase, i) => {
    if (tick >= phase.at) index = i
  })
  return index
}

interface PaperState {
  stage: PaperStage
  label: string
}

function paperStateAt(index: number, tick: number): PaperState {
  const paper = DEMO_PAPERS[index]
  const local = tick - (25 + index * 2.05)
  const failed = DEMO_FAILURES[paper.id] !== undefined

  if (local < 0) return { stage: 'queued', label: 'queued' }
  if (failed && local >= 4.5) return { stage: 'failed', label: 'failed' }
  if (local < 2) return { stage: 'active', label: 'fetching full text' }
  if (local < 4) return { stage: 'active', label: 'normalised' }
  if (local < 6.5) return { stage: 'active', label: 'extracting claims' }
  if (local < 8.5) return { stage: 'active', label: 'embedding claims' }
  return { stage: 'done', label: 'processed' }
}

const EVENT_FOR_LABEL: Record<string, string> = {
  'fetching full text': 'paper_started',
  normalised: 'paper_normalized',
  'extracting claims': 'paper_claims_extracted',
  'embedding claims': 'paper_claims_embedded',
}

export function simulateRun(tick: number, question: string, outcome: RunView['outcome']): RunView {
  const index = phaseIndexAt(tick)
  const phaseName = PHASE_AT[index].name

  const detail: Partial<Record<Phase, string>> = {
    structuring: '1 call',
    retrieving: '42 hits',
    ranking: 'top 20',
    storing: '20 rows',
    processing:
      index === PHASE_AT.findIndex((p) => p.name === 'processing')
        ? `${Math.min(20, Math.max(0, Math.round((tick - 25) / 2.05)))}/20`
        : '20/20',
    clustering: '6 clusters',
    synthesizing: `${SECTION_AT.filter((at) => tick >= at).length}/6`,
  }

  const phases: PhaseStep[] = PHASE_AT.map((phase, i) => ({
    name: phase.name,
    state: i < index ? 'done' : i === index ? 'active' : 'pending',
    detail: i <= index ? (detail[phase.name] ?? '') : '',
  }))

  const states = DEMO_PAPERS.map((_, i) => paperStateAt(i, tick))
  const papers: PaperProgress[] = DEMO_PAPERS.map((paper, i) => {
    const state = states[i]
    return {
      id: paper.id,
      title: paper.title,
      stage: state.stage,
      label: state.label,
      meta:
        state.stage === 'done'
          ? `${paper.claims} claims · ${paper.year}`
          : state.stage === 'failed'
            ? (DEMO_FAILURES[paper.id] ?? 'failed')
            : `${paper.authors.split(',')[0]} ${paper.year}`,
    }
  })

  const done = DEMO_PAPERS.filter((_, i) => states[i].stage === 'done')
  const failed = DEMO_PAPERS.filter((_, i) => states[i].stage === 'failed')

  const sections: SectionSlot[] = DEMO_SECTION_HEADINGS.map((heading, i) => ({
    ready: tick >= SECTION_AT[i],
    heading,
  }))

  // Collected newest-first; seq is stamped at the end so the column always
  // descends down the panel, the way a real stream reads.
  const events: EventLine[] = []
  const push = (text: string, kind: EventLine['kind'] = 'normal') => {
    events.unshift({ seq: 0, text, kind })
  }

  const recent = DEMO_PAPERS.map((_, i) => i)
    .filter((i) => states[i].stage !== 'queued')
    .slice(-5)
    .reverse()

  for (const i of recent) {
    const state = states[i]
    const paper = DEMO_PAPERS[i]
    if (state.stage === 'failed') {
      push(`paper_failed ${paper.id} ${paper.authors.split(',')[0]} ${paper.year}`, 'fail')
    } else if (state.stage === 'done') {
      push(`paper_processed ${paper.id} claims=${paper.claims}`, 'high')
    } else {
      push(`${EVENT_FOR_LABEL[state.label] ?? 'paper_started'} ${paper.id}`)
    }
  }
  if (tick >= 84) push(`section_ready cluster=c${SECTION_AT.filter((at) => tick >= at).length || 1}`, 'high')
  if (tick >= 106) push('run_completed papers=17/20 clusters=6', 'high')
  if (tick < 25) push(`phase_changed ${phaseName}`, 'high')
  while (events.length < 9) push('heartbeat')

  const head = 1804 + tick * 3
  const stamped = events.slice(0, 9).map((event, index) => ({ ...event, seq: head - index }))

  return {
    queryId: DEMO_QUERY_ID,
    question,
    status: tick >= 106 ? 'completed' : 'processing',
    phase: outcome === 'failed' ? 'failed' : phaseName,
    phaseIndex: index,
    phases,
    elapsedSeconds: tick * 1.9,
    papers,
    paperTotal: DEMO_PAPERS.length,
    processedCount: done.length + failed.length,
    failedCount: failed.length,
    claimsExtracted: done.reduce((total, paper) => total + paper.claims, 0),
    sections,
    sectionTotal: DEMO_SECTION_HEADINGS.length,
    reportAvailable: tick >= 106,
    reportNote: null,
    events: stamped,
    complete: tick >= 106,
    outcome,
    errorMessage: null,
  }
}

export const EMPTY_RUN: RunView = {
  queryId: null,
  question: '',
  status: 'pending',
  phase: 'queued',
  phaseIndex: 0,
  phases: PHASE_ORDER.filter((p) => p !== 'failed').map((name) => ({
    name,
    state: 'pending' as const,
    detail: '',
  })),
  elapsedSeconds: 0,
  papers: [],
  paperTotal: 0,
  processedCount: 0,
  failedCount: 0,
  claimsExtracted: 0,
  sections: [],
  sectionTotal: 0,
  reportAvailable: false,
  reportNote: null,
  events: [],
  complete: false,
  outcome: 'running',
  errorMessage: null,
}
