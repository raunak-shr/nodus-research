/** Ask the report.
 *
 *  A thread whose world is one finished report and the clusters behind it. It
 *  retrieves nothing, reads no paper, and answers from no other source — so
 *  every turn is checkable against a section a reader can open, and a question
 *  the evidence does not settle comes back uncovered instead of answered.
 *
 *  That refusal is the screen's most important state, so it is the loudest: an
 *  uncovered answer carries the one remedy the chat cannot provide itself, which
 *  is putting the question through the pipeline as a follow-up.
 */

import { useEffect, useRef, type KeyboardEvent, type ReactElement } from 'react'

import type { ChatCitation } from '../lib/types'
import type { ChatMessage } from '../lib/viewmodels'
import { useStore } from '../state/store'

/** Openers that are true of every report, phrased as what this thread can do:
 *  read back what the report established, and only that. */
const OPENERS = [
  'What is the strongest evidence in this report?',
  'Where do the papers disagree, and why?',
  'Which findings rest on a single paper?',
]

export function ChatScreen(): ReactElement {
  const store = useStore()
  const { chat, chatDraft, chatPending, report } = store
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [chat.length, chatPending])

  const sections = report?.sections ?? []
  const send = (): void => store.askReport()

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    // Enter sends, Shift+Enter breaks the line. A question is one or two lines,
    // and reaching for a button after every one of them is the wrong shape.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  return (
    <div className="screen" style={{ maxWidth: 940 }}>
      <div className="kicker" style={{ marginBottom: 14 }}>
        Ask the report
      </div>
      <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>
        Ask inside the answer
      </h2>
      <p className="dim pretty" style={{ maxWidth: 660, margin: '0 0 26px', lineHeight: 1.6 }}>
        Every answer here comes from this run&rsquo;s report and the clusters behind it, and from
        nothing else &mdash; no new papers, no second search, none of the model&rsquo;s own recall.
        Where the report is hedged the answer is hedged, and where it is silent the answer says so
        rather than filling the gap.
      </p>

      {report ? (
        <>
          <Scope />
          <div style={{ display: 'flex', flexDirection: 'column', marginBottom: 26 }}>
            {chat.length === 0 ? <Opening /> : null}
            {chat.map((message) => (
              <Turn key={message.id} message={message} />
            ))}
            <div ref={endRef} />
          </div>

          <div className="ask-box" style={{ maxWidth: 760 }}>
            <textarea
              className="bare"
              value={chatDraft}
              onChange={(event) => store.setChatDraft(event.target.value)}
              onKeyDown={onKeyDown}
              rows={2}
              maxLength={600}
              placeholder={
                sections.length
                  ? `Ask about “${sections[0].heading}”, or anything else the report covers…`
                  : 'Ask what this report found…'
              }
              style={{ fontSize: 17, lineHeight: 1.45, padding: '16px 18px 6px' }}
            />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 12px 12px 18px',
                gap: 12,
                flexWrap: 'wrap',
              }}
            >
              <div className="faint" style={{ fontSize: 11.5 }}>
                {store.mode === 'demo'
                  ? 'no socket — answers are matched out of the report, not written about it'
                  : 'grounded in this report and its clusters only'}
              </div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                {chat.length ? (
                  <button type="button" className="linkish" onClick={store.clearChat}>
                    clear thread
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={send}
                  disabled={chatDraft.trim().length < 3 || chatPending}
                  style={{ whiteSpace: 'nowrap', fontSize: 12.5 }}
                >
                  {chatPending ? 'Reading…' : 'Ask'}
                </button>
              </div>
            </div>
          </div>
        </>
      ) : (
        <NoReport />
      )}
    </div>
  )
}

/** What is in scope, stated before the first question rather than after it. */
function Scope(): ReactElement | null {
  const store = useStore()
  const report = store.report
  if (!report) return null

  const sections = report.sections?.length ?? 0
  const claims = (report.sections ?? []).reduce(
    (total, section) => total + (section.claims?.length ?? 0),
    0,
  )

  return (
    <div
      className="panel"
      style={{
        borderLeft: '2px solid var(--n-line2)',
        padding: '14px 18px',
        marginBottom: 34,
        maxWidth: 760,
      }}
    >
      <div style={{ fontSize: 14, lineHeight: 1.45, marginBottom: 6 }}>{report.title}</div>
      <div className="faint num" style={{ fontSize: 11.5, lineHeight: 1.6 }}>
        {sections} sections · {store.clusters.length} clusters · {claims} claims ·{' '}
        {store.papers.length} papers
        {store.activeQueryId ? ` · run ${store.activeQueryId.replace(/-/g, '').slice(0, 6)}` : ''}
      </div>
    </div>
  )
}

function Opening(): ReactElement {
  const store = useStore()
  return (
    <Row when="—" dot={<Dot kind="idle" />}>
      <div className="dim" style={{ fontSize: 14, lineHeight: 1.6, marginBottom: 14 }}>
        Nothing asked yet. These read back what the report already established:
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {OPENERS.map((opener) => (
          <button
            key={opener}
            type="button"
            className="chip-btn"
            onClick={() => store.askReport(opener)}
          >
            {opener}
          </button>
        ))}
      </div>
    </Row>
  )
}

function NoReport(): ReactElement {
  const store = useStore()
  return (
    <div style={{ borderTop: '2px solid var(--n-line2)', paddingTop: 26, maxWidth: 640 }}>
      <div style={{ fontSize: 17, lineHeight: 1.45, marginBottom: 8 }}>
        There is no report to ask about yet.
      </div>
      <p className="dim" style={{ fontSize: 14, lineHeight: 1.6, margin: '0 0 22px' }}>
        This thread answers from a finished report and its clusters, so it has nothing to read until
        a run has been synthesised. Run a question, then come back and interrogate the answer.
      </p>
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => store.go('query')}
        style={{ fontSize: 13 }}
      >
        New query
      </button>
    </div>
  )
}

function Turn({ message }: { message: ChatMessage }): ReactElement {
  const store = useStore()
  const mine = message.role === 'user'

  return (
    <Row
      when={`${message.at} · ${mine ? 'you' : 'nodus'}`}
      dot={<Dot kind={mine ? 'you' : message.covered === false ? 'uncovered' : 'nodus'} />}
    >
      {mine ? (
        <div style={{ fontSize: 16.5, lineHeight: 1.45 }}>{message.text}</div>
      ) : (
        <Answer message={message} onFollowUp={() => store.runFollowup(previousQuestion(store.chat, message))} />
      )}
    </Row>
  )
}

/** The question this answer replied to — what a follow-up run would ask. */
function previousQuestion(chat: ChatMessage[], answer: ChatMessage): string {
  const index = chat.findIndex((message) => message.id === answer.id)
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (chat[cursor].role === 'user') return chat[cursor].text
  }
  return ''
}

function Answer({
  message,
  onFollowUp,
}: {
  message: ChatMessage
  onFollowUp: () => void
}): ReactElement {
  if (message.pending) {
    return (
      <div className="dim num" style={{ fontSize: 13, animation: 'n-pulse 1.4s ease-in-out infinite' }}>
        reading the report…
      </div>
    )
  }

  if (message.failed) {
    return (
      <div
        style={{
          borderLeft: '2px solid var(--n-con)',
          paddingLeft: 14,
          fontSize: 14,
          lineHeight: 1.55,
        }}
      >
        <div style={{ color: 'var(--n-con)', marginBottom: 4 }}>The question did not reach the report.</div>
        <div className="dim num" style={{ fontSize: 12 }}>
          {message.failed}
        </div>
      </div>
    )
  }

  const uncovered = message.covered === false

  return (
    <div>
      {uncovered ? (
        <div className="kicker" style={{ color: 'var(--color-accent-400)', marginBottom: 10 }}>
          not covered by this report
        </div>
      ) : null}
      <div
        className="pretty"
        style={{
          fontSize: 15.5,
          lineHeight: 1.62,
          borderLeft: uncovered ? '2px solid var(--color-accent)' : 'none',
          paddingLeft: uncovered ? 14 : 0,
        }}
      >
        {message.text.split(/\n{2,}/).map((paragraph, index) => (
          <p key={index} style={{ margin: index === 0 ? '0 0 10px' : '0 0 10px' }}>
            {paragraph}
          </p>
        ))}
      </div>

      {message.citations?.length ? <Citations citations={message.citations} /> : null}

      <div className="faint" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.6 }}>
        {/* Only where sentences were actually quoted: on an uncovered answer
            there are none, and the note would be describing nothing. */}
        {message.matched && !uncovered
          ? 'matched out of the report — these are its own sentences, quoted, with no model involved'
          : null}
        {message.grounding?.truncated
          ? `${message.matched && !uncovered ? ' · ' : ''}answered from ${message.grounding.blocks_sent} of the report's blocks — the rest did not fit the model's context`
          : null}
      </div>

      {uncovered ? (
        <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onFollowUp}
            style={{ whiteSpace: 'nowrap', fontSize: 12.5 }}
          >
            Run it as a follow-up
          </button>
          <span className="faint" style={{ fontSize: 11.5 }}>
            a run against the parent&rsquo;s papers — minutes, not seconds
          </span>
        </div>
      ) : null}
    </div>
  )
}

/** Where the answer came from, as things a reader can open.
 *
 *  A citation without a destination is a claim about provenance rather than
 *  provenance, so a section or cluster chip opens that cluster; front matter has
 *  no cluster behind it and opens the report. */
function Citations({ citations }: { citations: ChatCitation[] }): ReactElement {
  const store = useStore()
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
      {citations.map((citation) => (
        <button
          key={citation.label}
          type="button"
          className="chip-btn"
          title={citation.kind === 'front_matter' ? 'Open the report' : 'Open this cluster'}
          onClick={() =>
            citation.cluster_id ? store.openCluster(citation.cluster_id) : store.go('report')
          }
        >
          <span className="num faint" style={{ marginRight: 6 }}>
            {citation.label}
          </span>
          {citation.heading}
        </button>
      ))}
    </div>
  )
}

function Dot({ kind }: { kind: 'you' | 'nodus' | 'uncovered' | 'idle' }): ReactElement {
  const style =
    kind === 'you'
      ? { background: 'var(--n-text)' }
      : kind === 'nodus'
        ? { background: 'var(--color-accent)' }
        : kind === 'uncovered'
          ? { background: 'var(--n-bg)', border: '2px solid var(--color-accent)' }
          : { background: 'var(--n-bg)', border: '2px dashed var(--n-line2)' }
  return <div style={{ width: 11, height: 11, flex: '0 0 11px', ...style }} />
}

/** The same gutter-and-spine the run and lineage views use: a timeline, not a
 *  pair of opposing bubbles. The thread reads as one column of evidence. */
function Row({
  when,
  dot,
  children,
}: {
  when: string
  dot: ReactElement
  children: React.ReactNode
}): ReactElement {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 24px minmax(0, 1fr)', minHeight: 62 }}>
      <div className="faint num" style={{ fontSize: 11.5, paddingTop: 1 }}>
        {when}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {dot}
        <div style={{ width: 1, flex: 1, background: 'var(--n-line2)' }} />
      </div>
      <div style={{ padding: '0 0 26px 16px' }}>{children}</div>
    </div>
  )
}
