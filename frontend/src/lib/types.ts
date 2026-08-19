/** Hand-written mirrors of `app/schemas/*` — the v2 socket has no OpenAPI
 *  document, so these are the contract. `meta.describe` publishes the JSON
 *  Schema of every params model if these ever need regenerating.
 */

export const PHASE_ORDER = [
  'queued',
  'structuring',
  'retrieving',
  'ranking',
  'storing',
  'processing',
  'clustering',
  'synthesizing',
  'completed',
  'failed',
] as const

export type Phase = (typeof PHASE_ORDER)[number]

export type QueryStatus =
  | 'pending'
  | 'structuring'
  | 'retrieving'
  | 'processing'
  | 'clustering'
  | 'completed'
  | 'failed'

export type Stance = 'supports' | 'contradicts' | 'neutral'
export type QualityTier = 'high' | 'medium' | 'low' | 'unrated'
export type SourceMatch = 'exact' | 'normalized' | 'fuzzy' | 'none'
export type SourceOrigin = 'full_text' | 'abstract'

/** What a citation chip renders from, without a second request. */
export type ProvKind = 'verified' | 'approximate' | 'abstract' | 'unavailable'

// -- frames -----------------------------------------------------------------

export interface ReadyFrame {
  type: 'ready'
  protocol: string
  heartbeat_seconds: number
  actions: string[]
  resumed_subscriptions: string[]
}

export interface ResultFrame {
  type: 'result'
  id: string | null
  action: string
  data: unknown
}

export interface ErrorFrame {
  type: 'error'
  id: string | null
  action: string | null
  error: { code: string; message: string; detail: Record<string, unknown> }
}

export interface EventFrame {
  type: 'event'
  topic: string
  event: string
  seq: number
  phase: Phase
  timestamp: string
  progress?: number | null
  [key: string]: unknown
}

export interface HeartbeatFrame {
  type: 'heartbeat'
  ts: string
}

export type ServerFrame = ReadyFrame | ResultFrame | ErrorFrame | EventFrame | HeartbeatFrame

// -- resources --------------------------------------------------------------

export interface StructuredQuery {
  topic: string
  outcome_measure?: string | null
  study_type_preferences?: string[]
  date_range_start?: number | null
  date_range_end?: number | null
  core_concepts?: string[]
  search_keywords: string[]
  clarification_needed?: boolean
  clarification_message?: string | null
}

/** What the Interpret button gets back. A verdict other than `ready` is advice:
 *  the pipeline still accepts the question exactly as typed.
 *
 *  `suggested` is the one the client sets itself and the server never returns:
 *  it marks a question taken from Nodus's own list of alternatives, which was
 *  written to be runnable and so is not sent back to be judged again. */
export type QueryVerdict = 'ready' | 'workable' | 'unsuitable' | 'unassessed' | 'suggested'

export interface QueryInterpretation {
  question: string
  verdict: QueryVerdict
  worth_running: boolean
  reason: string
  suggestions: string[]
  structured_query: StructuredQuery
}

export interface QueryRead {
  id: string
  raw_query: string
  structured_query: StructuredQuery | null
  status: QueryStatus
  paper_count: number
  error_message: string | null
  parent_query_id: string | null
  created_at: string
  updated_at: string
}

export interface QueryWithPapers extends QueryRead {
  papers: QueryPaperRead[]
  running?: boolean
}

export interface QueryStats {
  query_id: string
  status: string
  running: boolean
  paper_count: number
  claim_count: number
  cluster_count: number
  report_sections: number
  last_seq?: number
  phase?: Phase
  [key: string]: unknown
}

export interface PaperRead {
  id: string
  semantic_scholar_id: string
  doi: string | null
  title: string
  abstract: string | null
  authors: { name?: string }[]
  publication_year: number | null
  venue: string | null
  citation_count: number
  influential_citation_count: number
  fields_of_study: unknown[]
  open_access_pdf_url: string | null
  tldr: { text?: string } | null
  created_at: string
}

export interface QueryPaperRead {
  paper: PaperRead
  rank: number
  ranking_score: number | null
}

export interface NormalizedPaperRead {
  id: string
  paper_id: string
  study_type: string
  methodology: Record<string, unknown> | null
  sections: Record<string, unknown> | null
  has_full_text: boolean
  processing_status: string
  llm_model_used: string | null
  processed_at: string | null
  created_at: string
}

export interface ClaimSourceFields {
  source_match: SourceMatch
  source_quote: string | null
  source_origin: SourceOrigin | null
  source_section: string | null
  source_page: number | null
  source_start: number | null
  source_end: number | null
}

export interface ClaimRead extends ClaimSourceFields {
  id: string
  paper_id: string
  claim_text: string
  evidence_type: string
  causal_classification: string
  methodology_details: Record<string, unknown> | null
  sample_size: string | null
  effect_size: Record<string, unknown> | null
  confidence_score: number
  position_in_paper: number | null
  created_at: string
}

/** `claims.source` — context plus precomputed highlight offsets. Never search
 *  for the quote in the context; the offsets are authoritative. */
export interface ClaimSourceRead {
  claim_id: string
  paper_id: string
  paper_title: string
  citation: string
  claim_text: string
  available: boolean
  match: SourceMatch
  origin: SourceOrigin | null
  reason: string | null
  quote: string | null
  section: string | null
  page: number | null
  start: number | null
  end: number | null
  context: string | null
  context_start: number | null
  highlight_start: number | null
  highlight_end: number | null
  pdf_url: string | null
}

export interface ClusterClaimRead extends ClaimSourceFields {
  claim_id: string
  paper_id: string
  claim_text: string
  citation: string
  stance: Stance
  similarity_score: number | null
  confidence_score: number
  sample_size: string | null
}

export interface LineageNode {
  paper_id?: string
  claim_id?: string
  title?: string
  year?: number | null
  citation_count?: number | null
  relationship?: 'origin' | 'supports' | 'contradicts' | 'extends' | string
  [key: string]: unknown
}

export interface LineageTree {
  root_paper_id?: string
  root_year?: number | null
  span_years?: number | null
  paper_count?: number | null
  chain?: LineageNode[]
  [key: string]: unknown
}

export interface DisagreementDriver {
  driver_type?: string
  type?: string
  description: string
}

export interface ClaimClusterRead {
  id: string
  query_id: string
  central_theme: string
  consensus_summary: string | null
  lineage_tree: LineageTree | null
  support_count: number
  neutral_count: number
  contradiction_count: number
  disagreement_drivers: DisagreementDriver[] | null
  quality_tier: QualityTier
  quality_score: number | null
  quality_rationale: QualityRationale | null
  user_edited: boolean
  created_at: string
}

export interface ClaimClusterDetail extends ClaimClusterRead {
  claims: ClusterClaimRead[]
}

/** Every input to the deterministic quality score, exposed so a reader can see
 *  and override the tier.
 *
 *  `components.conflict_penalty` is subtracted rather than weighted, and its cap
 *  is `weights.conflict_penalty_max`. `thresholds` travels with the score, so
 *  the UI reports the bar the server actually applied instead of a copy that can
 *  drift. Older rows may carry the inputs flat, so both shapes are read. */
export interface QualityRationale {
  components?: Record<string, number>
  weights?: Record<string, number>
  thresholds?: Partial<Record<QualityTier, number>>
  inputs?: QualityInputs
  weighted_sum?: number
  score?: number
  tier?: QualityTier
  overridable?: boolean
  [key: string]: unknown
}

export interface QualityInputs {
  study_types?: string | string[]
  largest_sample_size?: number | string | null
  paper_count?: number
  support_count?: number
  contradiction_count?: number
  [key: string]: unknown
}

export interface ReportSection {
  cluster_id: string
  heading: string
  narrative: string
  caveats: string[]
  central_theme: string
  quality_tier: QualityTier
  quality_score: number | null
  quality_rationale: QualityRationale | null
  stance_counts: { supports: number; contradicts: number; neutral: number }
  paper_count: number
  lineage: LineageTree | null
  disagreement_drivers: DisagreementDriver[]
  claims: ClusterClaimRead[]
}

export interface ReportRead {
  id: string
  query_id: string
  title: string
  executive_summary: string | null
  key_findings: string[] | null
  open_questions: string[] | null
  sections: ReportSection[] | null
  llm_model_used: string | null
  user_edited: boolean
  created_at: string
  updated_at: string
}

export interface RunGate {
  active: number
  limit: number
  runs_today: number
  daily_limit: number
}

export interface LimitsSnapshot {
  runs: RunGate
  active_runs: unknown[]
  rate_limit_enabled: boolean
  budgets: Record<string, { remaining?: number; limit?: number; reset_in?: number }>
}

export interface ServerConfig {
  llm_provider: string
  llm_model: string
  embedding_provider: string
  embedding_model: string
  embedding_dim: number
  auth_enabled: boolean
  max_concurrent_papers: number
  top_k_papers: number
  cluster_similarity_threshold: number
  retrieval_mode: string
  pdf_enabled: boolean
  admin_enabled: boolean
  rate_limit_enabled: boolean
  runs: RunGate
}
