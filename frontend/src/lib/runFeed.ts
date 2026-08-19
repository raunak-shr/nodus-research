/** Turning the pipeline's event stream into the live-run view.
 *
 *  The run screen is built entirely from events the server actually sent — a
 *  paper appears when `papers_stored` names it, gains a title at
 *  `paper_started`, and moves through its stages as each sub-stage lands. It is
 *  a reduction rather than a poll, so nothing on screen is a guess about work
 *  the server has not reported.
 *
 *  Counts come from the events too where the server publishes them
 *  (`completed`/`total` on `paper_processed`), because the server knows the
 *  denominator and the client only knows what it has seen.
 */

import type { EventFrame, Phase } from './types'
import { PHASE_ORDER } from './types'
import { eventLine, type EventLine, type PaperProgress, type PaperStage, type RunView, type SectionSlot } from './viewmodels'

interface PaperEntry {
  id: string
  title: string
  stage: PaperStage
  label: string
  detail: string
}

const STAGE_BY_EVENT: Record<string, { stage: PaperStage; label: string }> = {
  paper_started: { stage: 'active', label: 'fetching full text' },
  paper_pdf: { stage: 'active', label: 'fetching full text' },
  paper_normalized: { stage: 'active', label: 'normalised' },
  paper_claims_extracted: { stage: 'active', label: 'extracting claims' },
  paper_claims_embedded: { stage: 'active', label: 'embedding claims' },
  paper_processed: { stage: 'done', label: 'processed' },
  paper_failed: { stage: 'failed', label: 'failed' },
}

/** How a paper's full text was reached, for the paper row's detail line. */
const SOURCE_LABELS: Record<string, string> = {
  open_access: 'open access',
  doi: 'via DOI',
  arxiv: 'via arXiv',
}

/** What the database can say about a run, for `RunFeed.reconcile`. */
export interface RunSnapshot {
  phase?: Phase
  paperTotal?: number
  claims?: number
  clusters?: number
  reportAvailable?: boolean
}

/** Mutable state accumulated across one run's events. */
export class RunFeed {
  private phase: Phase = 'queued'
  private papers = new Map<string, PaperEntry>()
  private sections = new Map<string, string>()
  private events: EventLine[] = []
  private claims = 0
  private completedCount: number | null = null
  private totalCount: number | null = null
  private clusterCount: number | null = null
  private reportAvailable = false
  private reportNote: string | null = null
  private errorMessage: string | null = null
  private readonly startedAt = Date.now()

  constructor(
    private queryId: string | null,
    private readonly question: string,
    /** Used only until the server reports a real total. */
    private readonly expectedPapers: number,
  ) {}

  /** Name the run once `queries.create` answers.
   *
   *  `subscribe: true` attaches the stream before the reply comes back, so the
   *  first events land while the id is still unknown. Adopting the id keeps
   *  them, where replacing the feed with a freshly constructed one threw away
   *  everything up to `papers_stored`.
   */
  adopt(queryId: string): void {
    this.queryId = queryId
  }

  /** The run id this feed is following, once it is known. */
  get id(): string | null {
    return this.queryId
  }

  /** Fold in what the database says, for when the event stream cannot be heard.
   *
   *  The progress hub is in-process: on a host that runs more than one instance
   *  a reconnected socket can land somewhere that never saw this run, and the
   *  replay comes back empty. The database is the one account of the run every
   *  instance shares, so it is what the screen falls back to.
   *
   *  Everything here moves forward only. The stored status is coarser than the
   *  phases the events carry — there is no `synthesizing` row in the database —
   *  so taking it at face value would walk a run backwards on screen.
   */
  reconcile(snapshot: RunSnapshot): void {
    if (snapshot.phase && PHASE_ORDER.indexOf(snapshot.phase) > PHASE_ORDER.indexOf(this.phase)) {
      this.phase = snapshot.phase
    }
    if (typeof snapshot.paperTotal === 'number' && snapshot.paperTotal > 0) {
      this.totalCount = Math.max(this.totalCount ?? 0, snapshot.paperTotal)
    }
    if (typeof snapshot.claims === 'number') this.claims = Math.max(this.claims, snapshot.claims)
    if (typeof snapshot.clusters === 'number' && snapshot.clusters > 0) {
      this.clusterCount = Math.max(this.clusterCount ?? 0, snapshot.clusters)
    }
    if (snapshot.reportAvailable) this.reportAvailable = true
  }

  apply(frame: EventFrame): void {
    this.phase = frame.phase
    this.events = [eventLine(frame), ...this.events].slice(0, 9)

    const paperId = str(frame.paper_id)
    const stage = STAGE_BY_EVENT[frame.event]
    if (paperId) {
      const entry = this.papers.get(paperId) ?? {
        id: paperId,
        title: shortId(paperId),
        stage: 'queued' as PaperStage,
        label: 'queued',
        detail: '',
      }
      // A failed paper still gets a `paper_processed` after its `paper_failed`,
      // because the pipeline counts it as done with the run either way. Letting
      // that overwrite the failure would report a clean 20 of 20 and hide the
      // degradation the report is built on.
      if (stage && entry.stage !== 'failed') {
        entry.stage = stage.stage
        entry.label = stage.label
      }
      const title = str(frame.title)
      if (title) entry.title = title
      if (frame.event === 'paper_normalized') {
        // Naming the route matters for arXiv specifically: a paper whose
        // publisher gave nothing still reads as 'full text', and only the
        // source says the fallback is what found it.
        const source = SOURCE_LABELS[str(frame.full_text_source) ?? '']
        entry.detail = [
          str(frame.study_type),
          frame.full_text ? (source ? `full text · ${source}` : 'full text') : 'abstract only',
        ]
          .filter(Boolean)
          .join(' · ')
      }
      if (frame.event === 'paper_claims_extracted' && typeof frame.claims === 'number') {
        entry.detail = `${frame.claims} claims`
      }
      if (
        frame.event === 'paper_processed' &&
        typeof frame.claims === 'number' &&
        entry.stage !== 'failed'
      ) {
        entry.detail = `${frame.claims} claims`
      }
      if (frame.event === 'paper_failed') {
        entry.detail = str(frame.reason) ?? 'failed'
      }
      this.papers.set(paperId, entry)
    }

    switch (frame.event) {
      case 'papers_stored': {
        // The one event that names the whole set, so the grid can show every
        // paper as queued instead of growing one row at a time.
        const ids = Array.isArray(frame.paper_ids) ? frame.paper_ids : []
        for (const raw of ids) {
          const id = str(raw)
          if (!id || this.papers.has(id)) continue
          this.papers.set(id, { id, title: shortId(id), stage: 'queued', label: 'queued', detail: '' })
        }
        if (typeof frame.count === 'number') this.totalCount = frame.count
        break
      }
      case 'paper_processed':
        if (typeof frame.claims === 'number') this.claims += frame.claims
        if (typeof frame.completed === 'number') this.completedCount = frame.completed
        if (typeof frame.total === 'number') this.totalCount = frame.total
        break
      case 'extraction_complete':
        if (typeof frame.claims === 'number') this.claims = frame.claims
        break
      case 'clusters_formed':
      case 'clustering_complete':
        // `clusters_formed` is the clustering step's own count; the pipeline
        // republishes it as `clustering_complete`. Reading both means the phase
        // shows a number even if the first was missed.
        if (typeof frame.clusters === 'number') this.clusterCount = frame.clusters
        break
      case 'section_ready': {
        const clusterId = str(frame.cluster_id)
        if (clusterId) this.sections.set(clusterId, str(frame.heading) ?? 'section ready')
        if (typeof frame.total === 'number') this.clusterCount = frame.total
        break
      }
      case 'section_retitled': {
        // Sections are narrated concurrently, so two can land on the same
        // heading; the server settles it afterwards. Keyed by cluster id, so this
        // corrects the row already on screen rather than adding another.
        const clusterId = str(frame.cluster_id)
        const heading = str(frame.heading)
        if (clusterId && heading && this.sections.has(clusterId)) {
          this.sections.set(clusterId, heading)
        }
        break
      }
      case 'report_ready':
        this.reportAvailable = true
        this.reportNote = null
        break
      case 'report_skipped':
        // A run can finish with nothing to write about. Saying so is the whole
        // point of the event: without it the panel waits on sections that are
        // never coming, and offers to open a report that was never written.
        this.reportAvailable = false
        this.reportNote = str(frame.reason) ?? 'This run produced no report.'
        break
      case 'failed':
        this.errorMessage = str(frame.error) ?? 'The run failed.'
        break
    }
  }

  view(): RunView {
    const papers: PaperProgress[] = [...this.papers.values()].map((entry) => ({
      id: entry.id,
      title: entry.title,
      stage: entry.stage,
      label: entry.label,
      meta: entry.detail,
    }))

    const failedCount = papers.filter((p) => p.stage === 'failed').length
    const seenDone = papers.filter((p) => p.stage === 'done' || p.stage === 'failed').length
    const total = this.totalCount ?? (papers.length || this.expectedPapers)
    const phaseIndex = Math.max(0, PHASE_ORDER.indexOf(this.phase))

    const readyHeadings = [...this.sections.values()]
    const slotCount = Math.max(this.clusterCount ?? 0, readyHeadings.length)
    const sections: SectionSlot[] = Array.from({ length: slotCount }, (_, index) => ({
      ready: index < readyHeadings.length,
      heading: readyHeadings[index] ?? '—',
    }))

    return {
      queryId: this.queryId,
      question: this.question,
      status: this.phase === 'completed' ? 'completed' : this.phase === 'failed' ? 'failed' : 'processing',
      phase: this.phase,
      phaseIndex,
      phases: PHASE_ORDER.filter((name) => name !== 'failed').map((name) => {
        const index = PHASE_ORDER.indexOf(name)
        return {
          name,
          state: index < phaseIndex ? 'done' : index === phaseIndex ? 'active' : 'pending',
          detail: this.phaseDetail(name, total),
        }
      }),
      elapsedSeconds: (Date.now() - this.startedAt) / 1000,
      papers,
      paperTotal: total,
      processedCount: this.completedCount ?? seenDone,
      failedCount,
      claimsExtracted: this.claims,
      sections,
      sectionTotal: slotCount,
      reportAvailable: this.reportAvailable,
      reportNote: this.reportNote,
      events: this.events,
      complete: this.phase === 'completed',
      outcome:
        this.phase === 'failed' ? 'failed' : this.phase === 'completed' ? 'completed' : 'running',
      errorMessage: this.errorMessage,
    }
  }

  private phaseDetail(name: Phase, total: number): string {
    switch (name) {
      case 'storing':
        return this.papers.size ? `${this.papers.size} rows` : ''
      case 'processing': {
        const done = this.completedCount ?? 0
        return total ? `${done}/${total}` : ''
      }
      case 'clustering':
        return this.clusterCount === null ? '' : `${this.clusterCount} clusters`
      case 'synthesizing': {
        const ready = this.sections.size
        return this.clusterCount ? `${ready}/${this.clusterCount}` : ready ? `${ready}` : ''
      }
      default:
        return ''
    }
  }
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

/** Until `paper_started` supplies the title, the id is what is known. */
function shortId(id: string): string {
  return `paper ${id.replace(/-/g, '').slice(0, 8)}`
}
