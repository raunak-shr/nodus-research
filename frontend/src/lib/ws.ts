/** The client for `/api/v2/ws`.
 *
 *  One socket carries the whole API: every call is `{id, action, params}` and
 *  every reply is a `result` or `error` frame echoing that id. Progress arrives
 *  unprompted as `event` frames on a `query:<uuid>` topic.
 *
 *  Two things this client refuses to paper over:
 *
 *  - A gap in `seq` means events were dropped. It is reported, never
 *    interpolated: the caller reloads state instead of assuming continuity.
 *  - A dropped connection re-subscribes with the last seq it applied, so the
 *    server replays only what was missed.
 */

import type { ErrorFrame, EventFrame, ServerFrame } from './types'

export type SocketStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'desynced'

export interface SocketGap {
  topic: string
  lastApplied: number
  received: number
  missed: number
}

export class NodusError extends Error {
  code: string
  detail: Record<string, unknown>
  action: string | null

  constructor(frame: ErrorFrame) {
    super(frame.error.message)
    this.name = 'NodusError'
    this.code = frame.error.code
    this.detail = frame.error.detail ?? {}
    this.action = frame.action
  }
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  action: string
}

export interface SocketOptions {
  url: string
  apiKey?: string
  /** Give up reconnecting after this many consecutive failures. */
  maxRetries?: number
  /** How long a socket may stay silent after the upgrade before it is judged
   *  not to be a Nodus endpoint. The server sends `ready` immediately. */
  readyTimeoutMs?: number
}

type StatusListener = (status: SocketStatus, info?: { seq: number }) => void
type EventListener = (frame: EventFrame) => void
type GapListener = (gap: SocketGap) => void

export class NodusSocket {
  private ws: WebSocket | null = null
  private readonly url: string
  private readonly apiKey?: string
  private readonly maxRetries: number
  private readonly readyTimeoutMs: number
  private readyTimer: number | null = null

  private nextId = 1
  private pending = new Map<string, Pending>()
  private queue: string[] = []

  /** Last seq applied per topic — what a re-subscribe resumes from. */
  private seqByTopic = new Map<string, number>()
  private subscriptions = new Set<string>()

  private retries = 0
  private reconnectTimer: number | null = null
  private closedByUs = false

  private statusListeners = new Set<StatusListener>()
  private eventListeners = new Set<EventListener>()
  private gapListeners = new Set<GapListener>()

  status: SocketStatus = 'idle'
  lastSeq = 0
  actions: string[] = []

  constructor(opts: SocketOptions) {
    this.url = opts.url
    this.apiKey = opts.apiKey
    this.maxRetries = opts.maxRetries ?? 8
    this.readyTimeoutMs = opts.readyTimeoutMs ?? 6000
  }

  // -- lifecycle ------------------------------------------------------------

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }
    this.closedByUs = false
    this.setStatus('connecting')

    const url = new URL(this.url, window.location.href)
    if (url.protocol === 'http:') url.protocol = 'ws:'
    if (url.protocol === 'https:') url.protocol = 'wss:'
    if (this.apiKey) url.searchParams.set('api_key', this.apiKey)

    const ws = new WebSocket(url.toString())
    this.ws = ws

    // A TCP upgrade is not a Nodus connection. Anything can accept a WebSocket
    // and then say nothing — a stray proxy, a 404 page, the wrong deployment.
    // The session only counts as open once the server's `ready` frame lands.
    ws.onopen = () => {
      this.readyTimer = window.setTimeout(() => {
        this.readyTimer = null
        ws.close()
      }, this.readyTimeoutMs)
    }

    ws.onmessage = (ev) => this.onFrame(ev.data)

    ws.onclose = () => {
      if (this.readyTimer !== null) {
        window.clearTimeout(this.readyTimer)
        this.readyTimer = null
      }
      this.ws = null
      const err = new Error('socket closed')
      for (const [, p] of this.pending) p.reject(err)
      this.pending.clear()
      if (this.closedByUs) {
        this.setStatus('idle')
        return
      }
      this.setStatus('closed')
      this.scheduleReconnect()
    }

    ws.onerror = () => {
      // `onclose` always follows, and carries the retry logic.
    }
  }

  close(): void {
    this.closedByUs = true
    if (this.readyTimer !== null) {
      window.clearTimeout(this.readyTimer)
      this.readyTimer = null
    }
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this.setStatus('idle')
  }

  private scheduleReconnect(): void {
    if (this.retries >= this.maxRetries) return
    const delay = Math.min(15_000, 500 * 2 ** this.retries)
    this.retries += 1
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }

  // -- frames ---------------------------------------------------------------

  private onFrame(raw: unknown): void {
    if (typeof raw !== 'string') return
    let frame: ServerFrame
    try {
      frame = JSON.parse(raw) as ServerFrame
    } catch {
      return
    }

    switch (frame.type) {
      case 'ready': {
        if (this.readyTimer !== null) {
          window.clearTimeout(this.readyTimer)
          this.readyTimer = null
        }
        this.actions = frame.actions
        this.retries = 0
        this.setStatus('open')
        // Resume every subscription from the last seq applied, so the server
        // replays the gap instead of the client guessing at it.
        for (const topic of this.subscriptions) {
          const queryId = topic.replace(/^query:/, '')
          void this.request('queries.subscribe', {
            query_id: queryId,
            since: this.seqByTopic.get(topic) ?? 0,
          }).catch(() => undefined)
        }
        const queued = this.queue
        this.queue = []
        for (const raw of queued) this.ws?.send(raw)
        break
      }
      case 'heartbeat':
        break
      case 'result': {
        const p = frame.id ? this.pending.get(frame.id) : undefined
        if (p && frame.id) {
          this.pending.delete(frame.id)
          p.resolve(frame.data)
        }
        break
      }
      case 'error': {
        const p = frame.id ? this.pending.get(frame.id) : undefined
        if (p && frame.id) {
          this.pending.delete(frame.id)
          p.reject(new NodusError(frame))
        }
        break
      }
      case 'event':
        this.onEvent(frame)
        break
    }
  }

  private onEvent(frame: EventFrame): void {
    const previous = this.seqByTopic.get(frame.topic)
    if (previous !== undefined && frame.seq > previous + 1) {
      const gap: SocketGap = {
        topic: frame.topic,
        lastApplied: previous,
        received: frame.seq,
        missed: frame.seq - previous - 1,
      }
      this.setStatus('desynced')
      for (const fn of this.gapListeners) fn(gap)
    }
    // A replayed event can arrive out of order after a resubscribe; the highest
    // seq seen is what a resume must ask from.
    this.seqByTopic.set(frame.topic, Math.max(previous ?? 0, frame.seq))
    this.lastSeq = frame.seq
    for (const fn of this.eventListeners) fn(frame)
  }

  // -- calls ----------------------------------------------------------------

  request<T = unknown>(action: string, params: Record<string, unknown> = {}): Promise<T> {
    const id = String(this.nextId++)
    const raw = JSON.stringify({ id, action, params })
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, action })
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(raw)
      } else {
        this.queue.push(raw)
        this.connect()
      }
    })
  }

  async subscribe(queryId: string, since = 0): Promise<void> {
    const topic = `query:${queryId}`
    this.subscriptions.add(topic)
    if (since > 0) this.seqByTopic.set(topic, since)
    await this.request('queries.subscribe', { query_id: queryId, since })
  }

  async unsubscribe(queryId: string): Promise<void> {
    const topic = `query:${queryId}`
    this.subscriptions.delete(topic)
    this.seqByTopic.delete(topic)
    await this.request('queries.unsubscribe', { query_id: queryId }).catch(() => undefined)
  }

  /** After a gap: refetch state, then keep streaming from where we are. */
  clearDesync(): void {
    if (this.status === 'desynced') this.setStatus(this.ws ? 'open' : 'closed')
  }

  // -- listeners ------------------------------------------------------------

  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn)
    return () => this.statusListeners.delete(fn)
  }

  onEventFrame(fn: EventListener): () => void {
    this.eventListeners.add(fn)
    return () => this.eventListeners.delete(fn)
  }

  onGap(fn: GapListener): () => void {
    this.gapListeners.add(fn)
    return () => this.gapListeners.delete(fn)
  }

  private setStatus(status: SocketStatus): void {
    this.status = status
    for (const fn of this.statusListeners) fn(status, { seq: this.lastSeq })
  }
}

/** Where the socket lives. In dev, vite proxies /api so the default is same-origin. */
export function resolveSocketUrl(): string {
  const configured = import.meta.env.VITE_NODUS_WS_URL
  if (configured) return configured
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v2/ws`
}
