/** One store for the whole app.
 *
 *  It hides which data source is behind a screen: the live socket, or the demo
 *  corpus when there is no backend to reach. Both produce the same view models,
 *  so no screen branches on it — only the banner in the sidebar says which.
 *
 *  Edits are recorded here as they are made, computed value beside the new one.
 *  The server marks an object `user_edited` and pins it, but it does not keep a
 *  per-change ledger, and a reader needs to see what a person changed.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react'

import { NodusError, NodusSocket, resolveSocketUrl, type SocketGap, type SocketStatus } from '../lib/ws'
import type {
  ClaimClusterDetail,
  ClaimClusterRead,
  ClaimSourceRead,
  ClusterClaimRead,
  EventFrame,
  NormalizedPaperSummary,
  QualityTier,
  QueryInterpretation,
  Phase,
  QueryRead,
  QueryStats,
  QueryStatus,
  QueryWithPapers,
  ReportRead,
  ReportSection,
  ServerConfig,
  Stance,
  StructuredQuery,
} from '../lib/types'
import { RunFeed } from '../lib/runFeed'
import { claimRef, type EditEntry, type PaperRow, type RunView } from '../lib/viewmodels'
import {
  DEMO_CLUSTERS,
  DEMO_FAILURES,
  DEMO_PAPERS,
  DEMO_QUERY_ID,
  demoClaimSource,
} from '../data/demoCorpus'
import {
  DEMO_QUERIES,
  DEMO_QUESTION,
  DEMO_REPORT,
  DEMO_RUN_TICKS,
  DEMO_TICK_MS,
  EMPTY_RUN,
  simulateRun,
} from '../data/demoRun'

export type Screen =
  | 'landing'
  | 'query'
  | 'run'
  | 'report'
  | 'cluster'
  | 'papers'
  | 'edits'
  | 'followup'
  | 'history'
  | 'states'
  | 'print'

/** A designed screen the run can be in, rather than a thrown error. */
export type Flag = null | 'seqgap' | 'failed' | 'cancelled' | 'busy' | 'moved'

export type Mode = 'live' | 'demo'

interface Store {
  mode: Mode
  theme: 'light' | 'dark'
  screen: Screen
  flag: Flag
  socketStatus: SocketStatus
  seq: number
  connectionNote: string | null
  /** The last action that failed, kept so a screen can say so instead of
   *  rendering an empty list that reads like "nothing here". */
  lastError: { action: string; message: string } | null
  config: ServerConfig | null

  question: string
  structured: StructuredQuery | null
  /** The last verdict on the question in the box, or null before Interpret has
   *  been pressed on it. Cleared the moment the question is edited: a verdict
   *  on text that is no longer there is worse than no verdict. */
  interpretation: QueryInterpretation | null
  interpreting: boolean

  queries: QueryRead[]
  activeQueryId: string | null
  run: RunView
  report: ReportRead | null
  clusters: ClaimClusterDetail[]
  activeClusterId: string | null
  papers: PaperRow[]
  gap: SocketGap | null

  source: ClaimSourceRead | null
  sourceClaimId: string | null
  sourceRef: string

  edits: EditEntry[]
  followupQuestion: string

  setTheme(theme: 'light' | 'dark'): void
  go(screen: Screen, flag?: Flag): void
  setFlag(flag: Flag): void
  setQuestion(value: string): void
  setFollowupQuestion(value: string): void
  /** Ask the server how it reads the question and whether running it is worth
   *  the five minutes. Never starts a run. `draft` overrides the box, for a
   *  caller that is setting the question and interpreting it in one go — the
   *  state update would not be visible to this callback yet. */
  interpret(draft?: string): void
  useSuggestedQuestion(question: string): void
  editQuestion(): void
  /** Start the run. `draft` runs that text instead of what is in the box —
   *  for a suggestion applied and run in one click. */
  startRun(draft?: string): void
  cancelRun(): void
  skipToEnd(): void
  reloadRun(): void
  /** Stage a representative gap so the recovery screen can be inspected
   *  without waiting for the socket to actually drop events. */
  simulateGap(): void
  openQuery(queryId: string): void
  openCluster(clusterId: string): void
  openSource(claim: ClusterClaimRead, ref: string): void
  closeSource(): void
  renameCluster(clusterId: string, title: string): void
  overrideTier(clusterId: string, tier: QualityTier): void
  clearTierOverride(clusterId: string): void
  flipStance(clusterId: string, claimId: string, next: Stance): void
  saveExecutiveSummary(text: string): void
  runFollowup(): void
  exportReport(format: 'markdown' | 'json' | 'html'): void
  downloadPdf(): void
}

const StoreContext = createContext<Store | null>(null)

export function useStore(): Store {
  const store = useContext(StoreContext)
  if (!store) throw new Error('useStore called outside StoreProvider')
  return store
}

// -- demo view models -------------------------------------------------------

function demoPaperRows(): PaperRow[] {
  const claimsByPaper = new Map<string, PaperRow['claims']>()
  DEMO_CLUSTERS.forEach((cluster, clusterIndex) => {
    cluster.claims.forEach((claim, claimIndex) => {
      const rows = claimsByPaper.get(claim.paper_id) ?? []
      rows.push({
        id: claim.claim_id,
        text: claim.claim_text,
        citation: claim.citation,
        clusterId: cluster.id,
        ref: claimRef(clusterIndex, claimIndex, claim.claim_id),
        source_match: claim.source_match,
        source_quote: claim.source_quote,
        source_origin: claim.source_origin,
        source_section: claim.source_section,
        source_page: claim.source_page,
        source_start: claim.source_start,
        source_end: claim.source_end,
      })
      claimsByPaper.set(claim.paper_id, rows)
    })
  })

  return DEMO_PAPERS.map((paper) => ({
    id: paper.id,
    rank: paper.rank,
    rankingScore: paper.score,
    title: paper.title,
    authorLine: paper.authors,
    year: paper.year,
    venue: paper.journal,
    citationCount: paper.cites,
    studyType: paper.type,
    methodology: paper.method,
    sampleSize: `n = ${paper.n.toLocaleString('en-US')}`,
    claimCount: DEMO_FAILURES[paper.id] ? 0 : paper.claims,
    failureReason: DEMO_FAILURES[paper.id] ?? null,
    claims: claimsByPaper.get(paper.id) ?? [],
  }))
}

// -- provider ---------------------------------------------------------------

const DEMO_ENV = import.meta.env.VITE_NODUS_DEMO === '1'

/** The stored status of a run, as a phase the run screen understands. It is the
 *  coarser of the two vocabularies — there is no `synthesizing` row in the
 *  database — which is why `RunFeed.reconcile` only ever moves forward. */
const statusPhase: Record<string, Phase> = {
  pending: 'queued',
  structuring: 'structuring',
  retrieving: 'retrieving',
  processing: 'processing',
  clustering: 'clustering',
  completed: 'completed',
  failed: 'failed',
}

/** How often to check on a run the stream has gone quiet about, and how long
 *  the silence has to last first. A healthy run publishes every few seconds, so
 *  neither timer fires while the socket is doing its job. */
const RECONCILE_EVERY_MS = 10_000
const STREAM_QUIET_MS = 20_000

export function StoreProvider({ children }: { children: ReactNode }): ReactElement {
  const [mode, setMode] = useState<Mode>(DEMO_ENV ? 'demo' : 'live')
  const [theme, setThemeState] = useState<'light' | 'dark'>('light')
  // The landing page is the entry point: a first visit has no query, no run and
  // no report, so every other screen would open on its empty state.
  const [screen, setScreen] = useState<Screen>('landing')
  const [flag, setFlag] = useState<Flag>(null)
  const [socketStatus, setSocketStatus] = useState<SocketStatus>(DEMO_ENV ? 'idle' : 'connecting')
  const [seq, setSeq] = useState(0)
  const [connectionNote, setConnectionNote] = useState<string | null>(null)
  const [lastError, setLastError] = useState<{ action: string; message: string } | null>(null)
  const [config, setConfig] = useState<ServerConfig | null>(null)

  // Empty, deliberately: a question already in the box is a question somebody
  // is one click away from running by accident. The demo build is the exception
  // — there the corpus *is* one question, so pre-filling it is the demo.
  const [question, setQuestion] = useState(DEMO_ENV ? DEMO_QUESTION : '')
  // Null until Interpret has been pressed, in every mode: the reading of a
  // question is a thing the server produced, and showing one nobody asked for
  // makes the box look like it has already been submitted.
  const [structured, setStructured] = useState<StructuredQuery | null>(null)
  const [interpretation, setInterpretation] = useState<QueryInterpretation | null>(null)
  const [interpreting, setInterpreting] = useState(false)

  const [queries, setQueries] = useState<QueryRead[]>(DEMO_ENV ? DEMO_QUERIES : [])
  const [activeQueryId, setActiveQueryId] = useState<string | null>(DEMO_ENV ? DEMO_QUERY_ID : null)
  const [run, setRun] = useState<RunView>(EMPTY_RUN)
  const [report, setReport] = useState<ReportRead | null>(DEMO_ENV ? DEMO_REPORT : null)
  const [clusters, setClusters] = useState<ClaimClusterDetail[]>(DEMO_ENV ? DEMO_CLUSTERS : [])
  const [activeClusterId, setActiveClusterId] = useState<string | null>(DEMO_ENV ? 'c2' : null)
  const [papers, setPapers] = useState<PaperRow[]>(DEMO_ENV ? demoPaperRows() : [])
  const [gap, setGap] = useState<SocketGap | null>(null)

  const [source, setSource] = useState<ClaimSourceRead | null>(null)
  const [sourceClaimId, setSourceClaimId] = useState<string | null>(null)
  const [sourceRef, setSourceRef] = useState('')

  const [edits, setEdits] = useState<EditEntry[]>([])
  const [followupQuestion, setFollowupQuestion] = useState(
    'Does the effect hold once trials with blinded outcome assessment are separated out?',
  )

  const socketRef = useRef<NodusSocket | null>(null)
  const tickRef = useRef<number | null>(null)
  const feedRef = useRef<RunFeed | null>(null)
  /** When the live stream last delivered anything. A run whose socket was cut
   *  and re-made somewhere else goes quiet without closing, so silence — not a
   *  disconnect — is the signal that the screen has stopped being told. */
  const lastEventAtRef = useRef(0)
  /** Topic the run screen is showing. `null` while a submission is in flight and
   *  its id is not back yet. */
  const activeTopicRef = useRef<string | null>(null)

  // -- theme ---------------------------------------------------------------

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // -- demo fallback -------------------------------------------------------

  const fallToDemo = useCallback((note: string) => {
    setMode('demo')
    setConnectionNote(note)
    setQueries(DEMO_QUERIES)
    setActiveQueryId(DEMO_QUERY_ID)
    setReport(DEMO_REPORT)
    setClusters(DEMO_CLUSTERS)
    setActiveClusterId((current) => current ?? 'c2')
    setPapers(demoPaperRows())
    // The demo corpus answers exactly one question, so falling back to it with
    // an empty box would offer screens that do not match what was asked.
    setQuestion((current) => current.trim() || DEMO_QUESTION)
  }, [])

  // -- socket --------------------------------------------------------------

  useEffect(() => {
    if (DEMO_ENV) {
      fallToDemo('Demo data — VITE_NODUS_DEMO is set, so no socket was opened.')
      return
    }

    const socket = new NodusSocket({
      url: resolveSocketUrl(),
      apiKey: import.meta.env.VITE_NODUS_API_KEY,
      maxRetries: 3,
      // Short: a real Nodus socket sends `ready` on the same round trip as the
      // upgrade, so waiting longer only leaves a reader looking at a blank app.
      readyTimeoutMs: 2500,
    })
    socketRef.current = socket

    // A handshake that 404s will 404 again, so the first failed *initial*
    // connection is enough to know there is no backend here. A drop after a
    // successful session is different: that one is worth retrying.
    let everOpened = false
    const offStatus = socket.onStatus((status, info) => {
      setSocketStatus(status)
      if (info) setSeq(info.seq)
      if (status === 'open') {
        const reconnected = everOpened
        everOpened = true
        setMode('live')
        setConnectionNote(null)
        // A reconnect re-subscribes, but the instance that answers may never
        // have seen this run. Ask the database where it actually got to.
        if (reconnected) {
          const resumed = feedRef.current?.id
          if (resumed) void reconcileRun(resumed)
        }
        void socket
          .request<ServerConfig>('meta.config')
          .then(setConfig)
          .catch((error: unknown) => setLastError(describe('meta.config', error)))
        void socket
          .request<QueryRead[]>('queries.list', { limit: 50 })
          .then((rows) => {
            setQueries(rows)
            setLastError(null)
          })
          .catch((error: unknown) => setLastError(describe('queries.list', error)))
      }
      if (status === 'closed' && !everOpened) {
        fallToDemo(
          'No backend reachable at this origin — showing the demo corpus. Every screen is the real UI on fixture data.',
        )
      }
    })

    const offGap = socket.onGap((detected) => {
      setGap(detected)
      setFlag('seqgap')
    })

    const offEvent = socket.onEventFrame((frame) => {
      setSeq(frame.seq)
      lastEventAtRef.current = Date.now()
      applyLiveEvent(frame)
    })

    socket.connect()

    return () => {
      offStatus()
      offGap()
      offEvent()
      socket.close()
      socketRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fallToDemo])

  const applyLiveEvent = useCallback((frame: EventFrame) => {
    const feed = feedRef.current
    if (!feed) return

    // Only the run on screen. The server admits concurrent runs and the socket
    // stays subscribed to each, so without this both streams reduce into one
    // feed: two 25-cluster runs eight seconds apart produced a panel of 50
    // sections, one run's headings interleaved with the other's.
    //
    // `null` means the run was only just submitted and its id has not come back.
    // The previous run is unsubscribed before a new one starts, so nothing else
    // is streaming by then and those first frames can only be its own.
    const topic = activeTopicRef.current
    if (topic !== null && frame.topic !== topic) return

    feed.apply(frame)
    setRun(feed.view())

    // The pipeline signals completion as a status event, and the artifacts are
    // only queryable once it has.
    if (frame.phase === 'completed') {
      void loadQueryArtifacts(frame.topic.replace(/^query:/, ''))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadQueryArtifacts = useCallback(async (queryId: string) => {
    const socket = socketRef.current
    if (!socket) return

    // `clusters.list` returns summaries without their member claims, and
    // `report.get` is absent until synthesis has run. Each is fetched and
    // failed independently, so a run that got as far as papers but no further
    // still shows its papers instead of a blank app.
    const [detail, clusterList, reportDoc] = await Promise.all([
      socket.request<QueryWithPapers>('queries.get', { query_id: queryId }).catch((error: unknown) => {
        setLastError(describe('queries.get', error))
        return null
      }),
      socket
        .request<ClaimClusterRead[]>('clusters.list', { query_id: queryId })
        .catch(() => [] as ClaimClusterRead[]),
      socket.request<ReportRead>('report.get', { query_id: queryId }).catch(() => null),
    ])

    setActiveQueryId(queryId)
    if (detail) {
      setStructured(detail.structured_query)
      setQuestion(detail.raw_query)
    }
    setReport(reportDoc)

    // Claims come from the report's sections, which already carry them; the
    // cluster screen fills in the rest on demand via `clusters.get`.
    const summaries: ClaimClusterDetail[] = clusterList.map((cluster) => ({
      ...cluster,
      claims: reportDoc?.sections?.find((s) => s.cluster_id === cluster.id)?.claims ?? [],
    }))
    setClusters(summaries)
    setActiveClusterId((current) =>
      current && summaries.some((c) => c.id === current) ? current : (summaries[0]?.id ?? null),
    )

    if (detail) {
      setPapers(livePaperRows(detail, reportDoc?.sections ?? []))
    }
  }, [])

  /** Catch the run screen up from the database.
   *
   *  The progress hub lives in the process that is running the pipeline, and a
   *  deployment that runs more than one instance can hand a reconnected socket
   *  to a different one — which has no history to replay and will publish this
   *  run's remaining events somewhere this client is not listening. The stored
   *  status and counts are the same on every instance, so they are what the
   *  screen falls back to. `RunFeed.reconcile` only moves forward, so this can
   *  never undo something the events already showed.
   */
  const reconcileRun = useCallback(
    async (queryId: string) => {
      const socket = socketRef.current
      const feed = feedRef.current
      if (!socket || !feed || feed.id !== queryId) return

      const stats = await socket
        .request<QueryStats>('queries.stats', { query_id: queryId })
        .catch(() => null)
      if (!stats || feedRef.current !== feed) return

      const status = String(stats.status)
      const finished = status === 'completed' || status === 'failed'
      feed.reconcile({
        // `phase` is present only when this instance is the one running the
        // pipeline. Otherwise the stored status stands in, which is coarser.
        phase: (stats.phase as Phase | undefined) ?? (statusPhase[status] ?? undefined),
        paperTotal: stats.paper_count,
        claims: stats.claim_count,
        clusters: stats.cluster_count,
        reportAvailable: (stats.report_sections ?? 0) > 0,
      })
      setRun(feed.view())

      if (finished) void loadQueryArtifacts(queryId)
    },
    [loadQueryArtifacts],
  )

  /** Pull a cluster's member claims when it is opened, if they are not in hand. */
  const ensureClusterClaims = useCallback(async (clusterId: string) => {
    const socket = socketRef.current
    if (!socket) return
    try {
      const detail = await socket.request<ClaimClusterDetail>('clusters.get', {
        cluster_id: clusterId,
      })
      setClusters((current) =>
        current.map((cluster) =>
          cluster.id === clusterId ? { ...detail, claims: detail.claims ?? [] } : cluster,
        ),
      )
    } catch (error: unknown) {
      setLastError(describe('clusters.get', error))
    }
  }, [])

  // -- demo run clock ------------------------------------------------------

  const stopClock = useCallback(() => {
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current)
      tickRef.current = null
    }
  }, [])

  const runDemoClock = useCallback(
    (fromTick: number, text?: string) => {
      // `text` for a run started from a question that was set this tick — the
      // state update is not visible to this callback yet.
      const asked = text ?? question
      stopClock()
      let tick = fromTick
      setRun(simulateRun(tick, asked, 'running'))
      tickRef.current = window.setInterval(() => {
        tick += 1
        if (tick >= DEMO_RUN_TICKS) {
          stopClock()
          setRun(simulateRun(DEMO_RUN_TICKS, asked, 'completed'))
          return
        }
        setRun(simulateRun(tick, asked, 'running'))
      }, DEMO_TICK_MS)
    },
    [question, stopClock],
  )

  useEffect(() => stopClock, [stopClock])

  // -- keeping a live run on screen ----------------------------------------

  // A socket that is cut and re-made — a host that caps how long one may live
  // does this to every run longer than the cap — resumes its subscriptions, but
  // the replay is only as good as the instance that answers. So a run that has
  // heard nothing for a while is checked against the database instead of being
  // left on the last frame that arrived. While the stream is healthy this
  // costs nothing: `lastEventAtRef` is refreshed every few seconds and the
  // check never fires.
  useEffect(() => {
    if (mode !== 'live') return
    const queryId = run.queryId
    if (!queryId || run.complete) return

    const timer = window.setInterval(() => {
      if (Date.now() - lastEventAtRef.current < STREAM_QUIET_MS) return
      void reconcileRun(queryId)
    }, RECONCILE_EVERY_MS)
    return () => window.clearInterval(timer)
  }, [mode, reconcileRun, run.complete, run.queryId])

  // The elapsed clock. Events arrive in bursts and Stage 3 is minutes of LLM
  // calls between them, so reading the feed only when a frame lands left the
  // clock standing still and then jumping; this re-reads it once a second.
  // The feed is what computes elapsed and it stops at the run's own end, so
  // this interval carries no time of its own — it is only what redraws it.
  useEffect(() => {
    if (mode !== 'live' || !run.started) return
    if (run.complete || run.outcome !== 'running' || flag === 'cancelled') return

    const timer = window.setInterval(() => {
      const feed = feedRef.current
      if (feed) setRun(feed.view())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [flag, mode, run.complete, run.outcome, run.started])

  // -- actions -------------------------------------------------------------

  const go = useCallback((next: Screen, nextFlag: Flag = null) => {
    setScreen(next)
    setFlag(nextFlag)
  }, [])

  /** Ask the server to read the question back and judge it.
   *
   *  This is the whole point of the button: a run is twenty papers and several
   *  minutes, and the pipeline refuses nothing, so "is exercise good?" produces
   *  a report just as readily as a question that names an outcome — and the
   *  reader only finds out how loose it was at the end. The verdict is advice,
   *  never a gate: every path from here still leads to Run analysis.
   */
  const interpret = useCallback(
    (override?: string) => {
      const draft = (override ?? question).trim()
      if (draft.length < 3) return

      const socket = socketRef.current
      if (mode === 'demo' || !socket) {
        const verdict = demoInterpretation(draft)
        setInterpretation(verdict)
        setStructured(verdict.structured_query)
        return
      }

      setInterpreting(true)
      setLastError(null)
      socket
        .request<QueryInterpretation>('queries.interpret', { query: draft })
        .then((result) => {
          setInterpretation(result)
          setStructured(result.structured_query)
        })
        .catch((error: unknown) => {
          const described = describe('queries.interpret', error)
          setLastError(described)
          // The check failing is not a verdict on the question. Say what happened
          // and leave the run available rather than showing a warning the server
          // never gave.
          setInterpretation({
            question: draft,
            verdict: 'unassessed',
            worth_running: true,
            reason: `The suitability check did not run (${described.message}), so this question has not been assessed. You can still run it.`,
            suggestions: [],
            structured_query: { topic: draft, search_keywords: [draft] },
          })
        })
        .finally(() => setInterpreting(false))
    },
    [mode, question],
  )

  /** Stop the run currently on screen from streaming.
   *
   *  Ignoring its events client-side is not enough: a live run keeps publishing,
   *  and every frame still crosses the socket and gets buffered per subscriber.
   *  Dropping the subscription is what makes the previous run go quiet.
   */
  const releaseRun = useCallback(() => {
    const previous = activeTopicRef.current
    activeTopicRef.current = null
    if (previous && socketRef.current) {
      void socketRef.current.unsubscribe(previous.replace(/^query:/, ''))
    }
  }, [])

  const startRun = useCallback(
    (draft?: string) => {
      const asked = (draft ?? question).trim()
      if (!asked) return
      // A run started from one of Nodus's own suggestions passes the text
      // directly, because the question was set in this same tick.
      if (draft !== undefined) setQuestion(asked)

      setFlag(null)
      setScreen('run')
      // The quiet check measures silence since the last frame; without this the
      // first tick would count from the epoch and reconcile a healthy run.
      lastEventAtRef.current = Date.now()

      if (mode === 'demo' || !socketRef.current) {
        feedRef.current = null
        runDemoClock(0, asked)
        return
      }

      const expected = config?.top_k_papers ?? 20
      releaseRun()
      feedRef.current = new RunFeed(null, asked, expected)
      setRun(feedRef.current.view())

      void socketRef.current
        .request<{ query: QueryRead }>('queries.create', { query: asked, subscribe: true })
        .then((created) => {
          // The reply wraps the query; `subscribe: true` has already attached the
          // stream, so re-subscribing here would only duplicate it. The feed is
          // adopted rather than replaced, which keeps the events that arrived
          // while the id was still unknown.
          const id = created.query.id
          activeTopicRef.current = `query:${id}`
          setActiveQueryId(id)
          // The server attached the stream, but this client has to record it
          // too: a reconnect resumes only the subscriptions it knows about.
          socketRef.current?.adopt(id)
          feedRef.current?.adopt(id)
          setRun((current) => feedRef.current?.view() ?? current)
        })
        .catch((error: unknown) => {
          const code = (error as { code?: string }).code
          if (code === 'too_many_requests' || code === 'busy' || code === 'unavailable') {
            setFlag('busy')
            return
          }
          setLastError(describe('queries.create', error))
          setRun((current) => ({
            ...current,
            outcome: 'failed',
            errorMessage: error instanceof Error ? error.message : String(error),
          }))
          setFlag('failed')
        })
    },
    [config, mode, question, runDemoClock],
  )

  const cancelRun = useCallback(() => {
    stopClock()
    // Cancelling ends the run without a terminal phase — the stream just stops —
    // so the feed is told to hold its clock at the moment it was asked to stop.
    // That number is what the cancelled screen reports as the run's length.
    feedRef.current?.freeze()
    setRun((current) => feedRef.current?.view() ?? current)
    setFlag('cancelled')
    if (mode === 'live' && activeQueryId && socketRef.current) {
      void socketRef.current.request('queries.cancel', { query_id: activeQueryId }).catch(() => undefined)
    }
  }, [activeQueryId, mode, stopClock])

  const skipToEnd = useCallback(() => {
    if (mode !== 'demo') return
    stopClock()
    setFlag(null)
    setRun(simulateRun(DEMO_RUN_TICKS, question, 'completed'))
  }, [mode, question, stopClock])

  const reloadRun = useCallback(() => {
    setFlag(null)
    setGap(null)
    socketRef.current?.clearDesync()
    if (mode === 'live' && activeQueryId) void loadQueryArtifacts(activeQueryId)
  }, [activeQueryId, loadQueryArtifacts, mode])

  const simulateGap = useCallback(() => {
    const lastApplied = seq || 1840
    setGap({
      topic: `query:${activeQueryId ?? DEMO_QUERY_ID}`,
      lastApplied,
      received: lastApplied + 18,
      missed: 17,
    })
    setScreen('run')
    setFlag('seqgap')
  }, [activeQueryId, seq])

  const openQuery = useCallback(
    (queryId: string) => {
      const record = queries.find((q) => q.id === queryId)
      setActiveQueryId(queryId)
      if (record) setQuestion(record.raw_query)

      if (record?.status === 'failed') {
        setScreen('run')
        setFlag('failed')
        setRun((current) => ({
          ...current,
          question: record.raw_query,
          outcome: 'failed',
          errorMessage: record.error_message,
        }))
        return
      }
      if (record?.status === 'processing') {
        setScreen('run')
        setFlag(null)
        if (mode === 'demo') {
          runDemoClock(48)
          return
        }
        // A feed to reduce into, and the topic to accept — without both, the
        // events arrive and the run screen has nowhere to put them.
        releaseRun()
        feedRef.current = new RunFeed(queryId, record.raw_query, config?.top_k_papers ?? 20)
        setRun(feedRef.current.view())
        activeTopicRef.current = `query:${queryId}`
        void socketRef.current?.subscribe(queryId)
        return
      }
      // Reading a finished run, not watching one: let go of whatever was
      // streaming rather than leaving it attached for the rest of the session.
      if (mode === 'live') releaseRun()
      setScreen('report')
      setFlag(null)
      if (mode === 'live') void loadQueryArtifacts(queryId)
    },
    [config, loadQueryArtifacts, mode, queries, releaseRun, runDemoClock],
  )

  const openCluster = useCallback(
    (clusterId: string) => {
      setActiveClusterId(clusterId)
      setScreen('cluster')
      setFlag(null)
      if (mode === 'live') void ensureClusterClaims(clusterId)
    },
    [ensureClusterClaims, mode],
  )

  const openSource = useCallback(
    (claim: ClusterClaimRead, ref: string) => {
      setSourceClaimId(claim.claim_id)
      setSourceRef(ref)
      if (mode === 'demo' || !socketRef.current) {
        setSource({ ...demoClaimSource(claim), claim_id: claim.claim_id })
        return
      }
      setSource(null)
      void socketRef.current
        .request<ClaimSourceRead>('claims.source', { claim_id: claim.claim_id })
        .then(setSource)
        .catch(() => {
          // The panel still opens: a claim with no locatable source is a state
          // the reader has to see, not an error to swallow.
          setSource({
            claim_id: claim.claim_id,
            paper_id: claim.paper_id,
            paper_title: claim.citation,
            citation: claim.citation,
            claim_text: claim.claim_text,
            available: false,
            match: claim.source_match,
            origin: claim.source_origin,
            reason: `Source text could not be loaded for claim ${ref}.`,
            quote: claim.source_quote,
            section: claim.source_section,
            page: claim.source_page,
            start: claim.source_start,
            end: claim.source_end,
            context: null,
            context_start: null,
            highlight_start: null,
            highlight_end: null,
            pdf_url: null,
          })
        })
    },
    [mode],
  )

  const closeSource = useCallback(() => {
    setSource(null)
    setSourceClaimId(null)
    setSourceRef('')
  }, [])

  const recordEdit = useCallback((entry: EditEntry) => {
    setEdits((current) => [entry, ...current])
  }, [])

  const nowLabel = () => new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

  const renameCluster = useCallback(
    (clusterId: string, title: string) => {
      let previous = ''
      setClusters((current) =>
        current.map((cluster) => {
          if (cluster.id !== clusterId) return cluster
          previous = cluster.central_theme
          return { ...cluster, central_theme: title, user_edited: true }
        }),
      )
      setReport((current) =>
        current?.sections
          ? {
              ...current,
              sections: current.sections.map((section) =>
                section.cluster_id === clusterId ? { ...section, heading: title } : section,
              ),
            }
          : current,
      )
      if (mode === 'live' && socketRef.current) {
        void socketRef.current
          .request('clusters.update', { cluster_id: clusterId, patch: { central_theme: title } })
          .catch(() => undefined)
      }
      recordEdit({
        field: 'cluster.central_theme',
        object: `${clusterId} · cluster`,
        computed: previous,
        yours: title,
        at: nowLabel(),
      })
    },
    [mode, recordEdit],
  )

  const overrideTier = useCallback(
    (clusterId: string, tier: QualityTier) => {
      let computed = ''
      setClusters((current) =>
        current.map((cluster) => {
          if (cluster.id !== clusterId) return cluster
          const score = cluster.quality_rationale?.score ?? cluster.quality_score
          computed = `computed ${cluster.quality_rationale?.tier ?? cluster.quality_tier}` +
            (typeof score === 'number' ? ` (${score.toFixed(2)})` : '')
          return { ...cluster, quality_tier: tier, user_edited: true }
        }),
      )
      if (mode === 'live' && socketRef.current) {
        void socketRef.current
          .request('clusters.update', { cluster_id: clusterId, patch: { quality_tier: tier } })
          .catch(() => undefined)
      }
      recordEdit({
        field: 'quality_tier',
        object: `${clusterId} · cluster`,
        computed,
        yours: `${tier} — set by hand`,
        at: nowLabel(),
      })
    },
    [mode, recordEdit],
  )

  const clearTierOverride = useCallback(
    (clusterId: string) => {
      setClusters((current) =>
        current.map((cluster) => {
          if (cluster.id !== clusterId) return cluster
          const computed = cluster.quality_rationale?.tier
          return computed ? { ...cluster, quality_tier: computed, user_edited: false } : cluster
        }),
      )
      setEdits((current) =>
        current.filter((entry) => !(entry.field === 'quality_tier' && entry.object.startsWith(clusterId))),
      )
      if (mode === 'live' && socketRef.current) {
        const cluster = clusters.find((c) => c.id === clusterId)
        const computed = cluster?.quality_rationale?.tier
        if (computed) {
          void socketRef.current
            .request('clusters.update', { cluster_id: clusterId, patch: { quality_tier: computed } })
            .catch(() => undefined)
        }
      }
    },
    [clusters, mode],
  )

  const flipStance = useCallback(
    (clusterId: string, claimId: string, next: Stance) => {
      let previous: Stance = 'supports'
      let ref = claimId
      setClusters((current) =>
        current.map((cluster) => {
          if (cluster.id !== clusterId) return cluster
          const index = current.findIndex((c) => c.id === clusterId)
          return {
            ...cluster,
            user_edited: true,
            claims: cluster.claims.map((claim, claimIndex) => {
              if (claim.claim_id !== claimId) return claim
              previous = claim.stance
              ref = claimRef(index, claimIndex, claim.claim_id)
              return { ...claim, stance: next }
            }),
          }
        }),
      )
      if (mode === 'live' && socketRef.current) {
        void socketRef.current
          .request('clusters.set_stance', { cluster_id: clusterId, claim_id: claimId, stance: next })
          .catch(() => undefined)
      }
      recordEdit({
        field: 'claim.stance',
        object: `claim ${ref} in ${clusterId}`,
        computed: `computed ${previous}`,
        yours: `${next} — set by hand`,
        at: nowLabel(),
      })
    },
    [mode, recordEdit],
  )

  const saveExecutiveSummary = useCallback(
    (text: string) => {
      let previous = ''
      setReport((current) => {
        if (!current) return current
        previous = current.executive_summary ?? ''
        return { ...current, executive_summary: text, user_edited: true }
      })
      if (mode === 'live' && socketRef.current && activeQueryId) {
        void socketRef.current
          .request('report.update', { query_id: activeQueryId, patch: { executive_summary: text } })
          .catch(() => undefined)
      }
      if (previous !== text) {
        recordEdit({
          field: 'report.executive_summary',
          object: 'report · front matter',
          computed: `${previous.slice(0, 120)}…`,
          yours: `${text.slice(0, 120)}…`,
          at: nowLabel(),
        })
      }
    },
    [activeQueryId, mode, recordEdit],
  )

  const runFollowup = useCallback(() => {
    setFlag(null)
    setScreen('run')
    if (mode === 'demo' || !socketRef.current || !activeQueryId) {
      runDemoClock(0)
      return
    }
    const parentId = activeQueryId
    releaseRun()
    feedRef.current = new RunFeed(null, followupQuestion, config?.top_k_papers ?? 20)
    setRun(feedRef.current.view())
    void socketRef.current
      .request<{ query: QueryRead }>('queries.followup', {
        query_id: parentId,
        query: followupQuestion,
        subscribe: true,
      })
      .then((created) => {
        const id = created.query.id
        activeTopicRef.current = `query:${id}`
        setActiveQueryId(id)
        setQuestion(followupQuestion)
        socketRef.current?.adopt(id)
        feedRef.current?.adopt(id)
        setRun((current) => feedRef.current?.view() ?? current)
      })
      .catch(() => setFlag('busy'))
  }, [activeQueryId, config, followupQuestion, mode, releaseRun, runDemoClock])


  // -- export --------------------------------------------------------------

  const exportReport = useCallback(
    (format: 'markdown' | 'json' | 'html') => {
      if (mode === 'live' && socketRef.current && activeQueryId) {
        void socketRef.current
          .request<{ content: string; media_type?: string; filename?: string }>('report.export', {
            query_id: activeQueryId,
            format,
          })
          .then((result) => {
            download(
              result.content,
              result.media_type ?? MEDIA_TYPE[format],
              result.filename ?? `nodus-report.${EXTENSION[format]}`,
            )
          })
          .catch(() => undefined)
        return
      }
      if (!report) return
      // Offline, the export is generated from the same document on screen —
      // never a second rendering that could disagree with it.
      const content =
        format === 'json' ? JSON.stringify(report, null, 2) : reportToMarkdown(report, question)
      download(content, MEDIA_TYPE[format], `nodus-report.${EXTENSION[format]}`)
    },
    [activeQueryId, mode, question, report],
  )

  const downloadPdf = useCallback(() => {
    if (mode === 'live' && socketRef.current && activeQueryId) {
      void socketRef.current
        .request<{ content_base64: string; filename?: string }>('report.pdf', {
          query_id: activeQueryId,
        })
        .then((result) => {
          const binary = atob(result.content_base64)
          const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0))
          const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }))
          triggerDownload(url, result.filename ?? 'nodus-report.pdf')
        })
        .catch(() => setScreen('print'))
      return
    }
    // Without a backend there is no Chromium to render with, so the print
    // variant is what a reader gets — and it is the same layout the PDF prints.
    setScreen('print')
  }, [activeQueryId, mode])

  const value = useMemo<Store>(
    () => ({
      mode,
      theme,
      screen,
      flag,
      socketStatus,
      seq,
      connectionNote,
      lastError,
      config,
      question,
      structured,
      interpretation,
      interpreting,
      queries,
      activeQueryId,
      run,
      report,
      clusters,
      activeClusterId,
      papers,
      gap,
      source,
      sourceClaimId,
      sourceRef,
      edits,
      followupQuestion,
      setTheme: setThemeState,
      go,
      setFlag,
      // Editing the question invalidates the verdict on it, so the panel goes
      // rather than sitting under text it no longer describes.
      setQuestion: (value: string) => {
        setQuestion(value)
        setInterpretation(null)
        setStructured(null)
      },
      setFollowupQuestion,
      interpret,
      // Applying a suggestion leaves the question runnable. Sending it straight
      // back to be interpreted would spend a second call asking the model about
      // a question it just wrote to be specific enough to run — and would leave
      // the person who took the advice one step further from a report than the
      // person who ignored it.
      useSuggestedQuestion: (next: string) => {
        const asked = interpretation?.question
        setQuestion(next)
        // The old reading describes the old question, so it goes.
        setStructured(null)
        setInterpretation({
          question: next,
          verdict: 'suggested',
          worth_running: true,
          reason: asked
            ? `Nodus offered this instead of “${asked}”, written to name an outcome and a population, so it has not been checked again.`
            : 'This is one of Nodus’s own suggestions, written to be specific enough to run, so it has not been checked again.',
          suggestions: [],
          structured_query: { topic: next, search_keywords: [next] },
        })
      },
      editQuestion: () => {
        setStructured(null)
        setInterpretation(null)
      },
      startRun,
      cancelRun,
      skipToEnd,
      reloadRun,
      simulateGap,
      openQuery,
      openCluster,
      openSource,
      closeSource,
      renameCluster,
      overrideTier,
      clearTierOverride,
      flipStance,
      saveExecutiveSummary,
      runFollowup,
      exportReport,
      downloadPdf,
    }),
    [
      activeClusterId,
      activeQueryId,
      cancelRun,
      clearTierOverride,
      clusters,
      config,
      connectionNote,
      lastError,
      closeSource,
      downloadPdf,
      edits,
      exportReport,
      flag,
      flipStance,
      followupQuestion,
      gap,
      go,
      interpret,
      interpretation,
      interpreting,
      mode,
      openCluster,
      openQuery,
      openSource,
      papers,
      queries,
      question,
      renameCluster,
      overrideTier,
      report,
      reloadRun,
      run,
      runFollowup,
      simulateGap,
      saveExecutiveSummary,
      screen,
      seq,
      skipToEnd,
      socketStatus,
      source,
      sourceClaimId,
      sourceRef,
      startRun,
      structured,
      theme,
    ],
  )

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

// -- live paper rows --------------------------------------------------------

/** Terminal query states: after one of these, nothing more will be processed.
 *
 *  The distinction matters for a paper with no normalisation row. Mid-run that
 *  means its turn has not come; once the run has stopped it means the paper was
 *  dropped and never will be.
 */
const SETTLED_STATUSES: ReadonlySet<QueryStatus> = new Set<QueryStatus>(['completed', 'failed'])

/** Why this paper has no usable normalisation, or null when nothing is wrong.
 *
 *  Three states that a single "did we get a record?" check used to flatten into
 *  one, and reported as a processing failure:
 *
 *  - no record, run still going — not a failure, just not reached yet
 *  - no record, run finished    — the paper was dropped
 *  - record present, `failed`   — normalised, but extraction gave up on it
 *
 *  Nothing here reports a *transport* problem, and that is the point. This
 *  reads a field that arrived with the paper itself, so there is no separate
 *  request whose refusal could be mistaken for a dead paper. When twenty of
 *  these were fetched one-per-paper, the socket's in-flight ceiling refused the
 *  tail of the fan-out and every refusal was rendered as "failed during
 *  processing" — a transport limit presented to the user as data loss.
 */
function normalisationFailure(
  normalized: NormalizedPaperSummary | null,
  status: QueryStatus,
): string | null {
  if (!normalized) {
    return SETTLED_STATUSES.has(status)
      ? 'Not normalised — the paper was dropped during processing'
      : null
  }
  if (normalized.processing_status === 'failed') {
    return 'Normalised, but claim extraction failed'
  }
  return null
}

function livePaperRows(
  detail: QueryWithPapers,
  sections: ReportSection[],
): PaperRow[] {
  const claimsByPaper = new Map<string, PaperRow['claims']>()
  sections.forEach((section, clusterIndex) => {
    ;(section.claims ?? []).forEach((claim, claimIndex) => {
      const rows = claimsByPaper.get(claim.paper_id) ?? []
      rows.push({
        id: claim.claim_id,
        text: claim.claim_text,
        citation: claim.citation,
        clusterId: section.cluster_id,
        ref: claimRef(clusterIndex, claimIndex, claim.claim_id),
        source_match: claim.source_match,
        source_quote: claim.source_quote,
        source_origin: claim.source_origin,
        source_section: claim.source_section,
        source_page: claim.source_page,
        source_start: claim.source_start,
        source_end: claim.source_end,
      })
      claimsByPaper.set(claim.paper_id, rows)
    })
  })

  // `queries.get` carries each paper's normalisation inline, so this is one
  // request for the whole table rather than one per paper.
  return detail.papers.map((qp) => {
    const norm = qp.normalized
    const methodology = norm?.methodology ?? null
    const claims = claimsByPaper.get(qp.paper.id) ?? []
    return {
      id: qp.paper.id,
      rank: qp.rank,
      rankingScore: qp.ranking_score,
      title: qp.paper.title,
      authorLine: qp.paper.authors.map((a) => a.name).filter(Boolean).join(', ') || 'Unknown authors',
      year: qp.paper.publication_year,
      venue: qp.paper.venue,
      citationCount: qp.paper.citation_count,
      studyType: norm?.study_type ?? null,
      methodology: methodologyLine(methodology),
      sampleSize: sampleLine(methodology),
      claimCount: claims.length,
      failureReason: normalisationFailure(norm, detail.status),
      claims,
    }
  })
}

function methodologyLine(methodology: Record<string, unknown> | null): string | null {
  if (!methodology) return null
  const design = methodology.design ?? methodology.summary ?? methodology.description
  if (typeof design === 'string') return design
  return Object.entries(methodology)
    .filter(([, value]) => typeof value === 'string' || typeof value === 'number')
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${String(value)}`)
    .join(' · ') || null
}

function sampleLine(methodology: Record<string, unknown> | null): string | null {
  if (!methodology) return null
  const sample = methodology.sample_size ?? methodology.n ?? methodology.participants
  if (typeof sample === 'number') return `n = ${sample.toLocaleString('en-US')}`
  if (typeof sample !== 'string') return null

  // Normalisation writes whatever the paper said, which is often a sentence.
  // A leading count is the useful part; anything else is cut to a width the
  // column can hold, with the full text kept on the cell's title. It is never
  // dressed up as an "n =" the paper did not claim.
  const leading = /^\s*(?:n\s*=\s*)?([\d,]{1,12})\s*(?:participants|subjects|patients)?\b/.exec(sample)
  if (leading && leading[1]) return `n = ${leading[1]}`
  const trimmed = sample.trim()
  return trimmed.length > 40 ? `${trimmed.slice(0, 39)}…` : trimmed
}

// -- download helpers -------------------------------------------------------

const MEDIA_TYPE = {
  markdown: 'text/markdown',
  json: 'application/json',
  html: 'text/html',
} as const

const EXTENSION = { markdown: 'md', json: 'json', html: 'html' } as const

function download(content: string, mediaType: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mediaType }))
  triggerDownload(url, filename)
}

function triggerDownload(url: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function reportToMarkdown(report: ReportRead, question: string): string {
  const lines: string[] = [`# ${report.title}`, '', `In answer to: ${question}`, '']
  if (report.executive_summary) lines.push('## Executive summary', '', report.executive_summary, '')
  if (report.key_findings?.length) {
    lines.push('## Key findings', '')
    report.key_findings.forEach((finding, index) => lines.push(`${index + 1}. ${finding}`))
    lines.push('')
  }
  for (const section of report.sections ?? []) {
    lines.push(`## ${section.heading}`, '', section.narrative, '')
    if (section.caveats.length) {
      for (const caveat of section.caveats) lines.push(`> caveat — ${caveat}`)
      lines.push('')
    }
    lines.push(
      `Quality ${section.quality_tier}` +
        (section.quality_score === null ? '' : ` (${section.quality_score.toFixed(2)})`) +
        ` · ${section.stance_counts.supports} support / ${section.stance_counts.contradicts} contradict / ${section.stance_counts.neutral} neutral`,
      '',
    )
    for (const claim of section.claims) {
      const where = claim.source_page ? `, p. ${claim.source_page}` : ''
      lines.push(`- ${claim.claim_text} — ${claim.citation}${where} [${claim.source_match}]`)
    }
    lines.push('')
  }
  if (report.open_questions?.length) {
    lines.push('## Open questions', '')
    for (const openQuestion of report.open_questions) lines.push(`- ${openQuestion}`)
  }
  return lines.join('\n')
}

/** A failed action as a screen can show it: which call, and what it said. */
/** The verdict the demo build shows, since there is no server to ask.
 *
 *  It is a heuristic and says so: the real check is an LLM reading the question
 *  against what the pipeline can actually do. This exists so the screen can be
 *  seen and reviewed without a backend, not so it can judge anything.
 */
/** Words that, in a research question, usually introduce the population or the
 *  setting — the part "is exercise good?" is missing. */
const QUALIFIERS = new Set(['in', 'among', 'for', 'on', 'with'])

function demoInterpretation(draft: string): QueryInterpretation {
  const words = draft.trim().split(/\s+/).filter(Boolean)
  const qualified = words.some((word) => QUALIFIERS.has(word.toLowerCase().replace(/[^a-z]/g, '')))
  const specific = words.length >= 6 && qualified

  if (specific) {
    return {
      question: draft,
      verdict: 'ready',
      worth_running: true,
      reason:
        'Names a subject, an outcome and a population, so retrieval has three concepts to AND and clusters will land on comparable endpoints.',
      suggestions: [],
      structured_query: DEMO_QUERIES[0].structured_query as StructuredQuery,
    }
  }

  return {
    question: draft,
    verdict: 'workable',
    worth_running: false,
    reason: `“${draft}” fixes no outcome measure and no population, so ranking will be close to arbitrary and one cluster will mix unrelated endpoints.`,
    suggestions: [
      'Does aerobic exercise reduce depression severity in adults with major depressive disorder?',
      'Does resistance training improve HbA1c in adults with type 2 diabetes?',
      'Does exercise reduce all-cause mortality in adults over 60?',
    ],
    structured_query: DEMO_QUERIES[0].structured_query as StructuredQuery,
  }
}

function describe(action: string, error: unknown): { action: string; message: string } {
  if (error instanceof NodusError) return { action, message: `${error.code} — ${error.message}` }
  return { action, message: error instanceof Error ? error.message : String(error) }
}
