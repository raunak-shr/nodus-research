/** The live run.
 *
 *  Everything on this screen is something the pipeline actually reported: a
 *  phase it entered, a paper it finished, a section it wrote. Nothing predicts
 *  a finish time, and a failure is a designed screen rather than a thrown error.
 */

import { useState, type ReactElement } from 'react'

import { clock } from '../lib/format'
import { useStore } from '../state/store'

export function RunScreen(): ReactElement {
  const store = useStore()
  const { run, flag } = store
  const [showStream, setShowStream] = useState(true)

  // A finished run with no report is a real outcome, not a stalled panel: show
  // why rather than a ladder of dashes and a button that opens an empty screen.
  const noReport = run.complete && !run.reportAvailable

  // Nothing has been submitted on this connection. The screen used to be
  // reachable only by starting a run, so it assumed one; now that opening it
  // is just navigation, it has to be able to say there isn't one. A flag is
  // still shown — the failed and cancelled states are staged without a run.
  //
  // `run.started` is what the feed sets the moment a run is asked for. The
  // other three are consequences of one, and all three are still false for the
  // second or two `queries.create` takes to answer — long enough that starting
  // a run flashed the no-run screen before the run appeared.
  const started =
    run.started || Boolean(run.queryId) || run.papers.length > 0 || run.events.length > 0
  if (!started && !run.complete && !flag) return <NoRun />

  return (
    <div style={{ padding: '0 0 80px' }}>
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 5,
          background: 'var(--n-bg)',
          borderBottom: '2px solid var(--n-line2)',
          padding: '26px 56px 20px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 30,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div className="kicker" style={{ marginBottom: 8 }}>
              run {shortId(run.queryId)} · {run.phase}
            </div>
            <div style={{ fontSize: 23, letterSpacing: '-.015em', lineHeight: 1.25, maxWidth: 640 }}>
              {run.question || store.question}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flex: '0 0 auto' }}>
            <div style={{ textAlign: 'right', marginRight: 8 }}>
              <div className="num" style={{ fontSize: 24, letterSpacing: '-.02em' }}>
                {clock(run.elapsedSeconds)}
              </div>
              <div className="faint" style={{ fontSize: 11 }}>
                elapsed
              </div>
            </div>
            {store.mode === 'demo' ? (
              <button
                type="button"
                className="btn btn-ghost dim"
                onClick={store.skipToEnd}
                style={{ whiteSpace: 'nowrap', fontSize: 12 }}
              >
                Skip to end
              </button>
            ) : null}
            <button
              type="button"
              className="btn btn-secondary"
              onClick={store.cancelRun}
              disabled={run.complete}
              style={{
                color: 'var(--n-text)',
                whiteSpace: 'nowrap',
                fontSize: 12,
                borderColor: 'var(--n-line2)',
              }}
            >
              Cancel run
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', marginTop: 22, alignItems: 'stretch' }}>
          {run.phases.map((phase) => (
            <div
              key={phase.name}
              style={{
                flex: 1,
                minWidth: 0,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                paddingRight: 10,
              }}
            >
              <div
                style={{
                  height: 3,
                  background:
                    phase.state === 'done'
                      ? 'var(--color-accent-600)'
                      : phase.state === 'active'
                        ? 'var(--color-accent)'
                        : 'var(--n-line2)',
                  animation: phase.state === 'active' ? 'n-pulse 1.4s ease-in-out infinite' : undefined,
                }}
              />
              <div
                style={{
                  fontSize: 11.5,
                  letterSpacing: '.02em',
                  color:
                    phase.state === 'active'
                      ? 'var(--n-text)'
                      : phase.state === 'done'
                        ? 'var(--n-dim)'
                        : 'var(--n-faint)',
                }}
              >
                {phase.name}
              </div>
              <div className="faint num" style={{ fontSize: 10, height: 12 }}>
                {phase.detail}
              </div>
            </div>
          ))}
        </div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 400px', alignItems: 'start' }}>
        <div style={{ padding: '30px 40px 0 56px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              justifyContent: 'space-between',
              marginBottom: 16,
              gap: 16,
            }}
          >
            <div className="kicker">
              processing · {run.processedCount} of {run.paperTotal} papers
            </div>
            <div className="dim num" style={{ fontSize: 12 }}>
              {run.claimsExtracted} claims extracted · {run.failedCount} failed
            </div>
          </div>

          {run.papers.length === 0 ? (
            <div className="dim" style={{ fontSize: 13.5, lineHeight: 1.6, maxWidth: 520 }}>
              Nothing to show yet. The whole shortlist appears here as soon as retrieval and ranking
              land, and each row then moves through normalisation, extraction and embedding — the run
              reports per paper, not in a single jump.
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '1px 26px' }}>
              {run.papers.map((paper) => (
                <div
                  key={paper.id}
                  style={{
                    display: 'flex',
                    gap: 11,
                    minWidth: 0,
                    padding: '9px 0',
                    borderBottom: '2px solid var(--n-line2)',
                    opacity: paper.stage === 'queued' ? 0.42 : 1,
                    transition: 'opacity .3s',
                  }}
                >
                  <div
                    style={{
                      width: 7,
                      height: 7,
                      marginTop: 6,
                      flex: '0 0 7px',
                      background:
                        paper.stage === 'failed'
                          ? 'var(--n-con)'
                          : paper.stage === 'done'
                            ? 'var(--color-accent-500)'
                            : paper.stage === 'active'
                              ? 'var(--color-accent)'
                              : 'var(--n-line2)',
                      animation: paper.stage === 'active' ? 'n-pulse 1s ease-in-out infinite' : undefined,
                    }}
                  />
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        lineHeight: 1.35,
                        marginBottom: 3,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                      title={paper.title}
                    >
                      {paper.title}
                    </div>
                    <div
                      className="faint num"
                      style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 11 }}
                    >
                      <span
                        style={{
                          color:
                            paper.stage === 'failed'
                              ? 'var(--n-con)'
                              : paper.stage === 'active'
                                ? 'var(--color-accent-400)'
                                : 'var(--n-faint)',
                        }}
                      >
                        {paper.label}
                      </span>
                      <span>{paper.meta}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ padding: '30px 56px 0 0', position: 'sticky', top: 210 }}>
          <div className="panel" style={{ padding: '18px 20px', marginBottom: 16 }}>
            <div
              className="kicker"
              style={{
                marginBottom: 14,
                display: 'flex',
                justifyContent: 'space-between',
                gap: 10,
              }}
            >
              <span>{noReport ? 'No report' : 'Report assembling'}</span>
              {/* The list below scrolls, so it no longer shows its own length.
                  This says how many sections there are to scroll through. */}
              {!noReport && run.sectionTotal ? (
                <span className="num faint">
                  {run.sections.filter((slot) => slot.ready).length} of {run.sectionTotal}
                </span>
              ) : null}
            </div>
            {noReport ? (
              <div className="dim" style={{ fontSize: 13, lineHeight: 1.45 }}>
                {run.reportNote ??
                  'The run finished without writing a report. The stream below says how far it got.'}
              </div>
            ) : (
            // The section list grows with the cluster count, and a run with a
            // dozen clusters pushed the event stream below it off the screen.
            // Scrolling the list keeps the panel — and what sits under it — the
            // same height however many sections the run writes.
            <div
              className="n-scroll"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                maxHeight: 260,
                overflowY: 'auto',
                overflowX: 'hidden',
                paddingRight: 4,
                marginRight: -4,
              }}
            >
              {(run.sections.length ? run.sections : placeholderSlots(run.sectionTotal)).map((slot, index) => (
                <div
                  key={index}
                  style={{
                    display: 'flex',
                    gap: 10,
                    alignItems: 'flex-start',
                    opacity: slot.ready ? 1 : 0.38,
                    animation: slot.ready ? 'n-in .35s ease both' : undefined,
                  }}
                >
                  <div
                    className="num"
                    style={{
                      flex: '0 0 18px',
                      fontSize: 11,
                      paddingTop: 2,
                      color: slot.ready ? 'var(--color-accent-400)' : 'var(--n-faint)',
                    }}
                  >
                    {slot.ready ? '✓' : String(index + 1).padStart(2, '0')}
                  </div>
                  <div style={{ minWidth: 0, fontSize: 13, lineHeight: 1.35 }}>
                    {slot.ready ? slot.heading : '—'}
                  </div>
                </div>
              ))}
            </div>
            )}
            {run.complete && run.reportAvailable ? (
              <button
                type="button"
                className="btn btn-primary btn-block"
                onClick={() => store.go('report')}
                style={{ marginTop: 18, fontSize: 13 }}
              >
                Open report
              </button>
            ) : null}
          </div>

          <button
            type="button"
            className="linkish"
            onClick={() => setShowStream((value) => !value)}
            style={{ marginBottom: 8 }}
          >
            {showStream ? 'Hide event stream' : 'Show event stream'}
          </button>

          {showStream ? (
            <div
              className="inset num"
              style={{
                padding: '14px 16px',
                fontSize: 11.5,
                lineHeight: 1.7,
                color: 'var(--n-dim)',
                maxHeight: 250,
                overflow: 'hidden',
              }}
            >
              <div className="kicker" style={{ fontSize: 10, marginBottom: 8 }}>
                Event stream
              </div>
              {run.events.length === 0 ? (
                <div className="faint">no events yet</div>
              ) : (
                run.events.map((event, index) => (
                  <div key={`${event.seq}-${index}`} style={{ display: 'flex', gap: 8 }}>
                    <span className="faint" style={{ flex: '0 0 42px' }}>
                      {event.seq}
                    </span>
                    <span
                      style={{
                        color:
                          event.kind === 'fail'
                            ? 'var(--n-con)'
                            : event.kind === 'high'
                              ? 'var(--n-text)'
                              : 'var(--n-dim)',
                      }}
                    >
                      {event.text}
                    </span>
                  </div>
                ))
              )}
            </div>
          ) : null}
        </div>
      </div>

      {flag === 'busy' ? <BusyDialog /> : null}
      {flag === 'failed' ? <FailedTakeover /> : null}
      {flag === 'cancelled' ? <CancelledTakeover /> : null}
    </div>
  )
}

/** No run to show, because none was started.
 *
 *  A designed screen rather than an empty ladder of phases: the phases would
 *  all read "pending" and the elapsed clock would read 00:00, which looks like
 *  a run that is stuck rather than a run that does not exist.
 */
function NoRun(): ReactElement {
  const store = useStore()

  return (
    <div className="screen" style={{ maxWidth: 640 }}>
      <div className="kicker" style={{ marginBottom: 18 }}>
        live run
      </div>
      <h1
        className="pretty"
        style={{ fontSize: 30, lineHeight: 1.2, letterSpacing: '-.02em', margin: '0 0 12px' }}
      >
        No run on this connection yet.
      </h1>
      <p className="dim pretty" style={{ fontSize: 14.5, lineHeight: 1.6, margin: '0 0 26px' }}>
        This screen follows one analysis as it happens — retrieval, then each paper as it is
        normalised and mined for claims, then the sections as they are written. Ask a question to
        start one. Opening this screen does not start anything on its own.
      </p>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => store.go('query')}
          style={{ whiteSpace: 'nowrap', fontSize: 13.5, padding: '9px 18px' }}
        >
          Ask a question
        </button>
        {store.queries.length ? (
          <button
            type="button"
            className="btn btn-ghost dim"
            onClick={() => store.go('history')}
            style={{ whiteSpace: 'nowrap', fontSize: 13 }}
          >
            Open a previous run
          </button>
        ) : null}
      </div>
    </div>
  )
}

/** Empty rungs to fill the panel before any section lands.
 *
 *  `count` is the number of clusters the server has reported; until it has, six
 *  is a stand-in for "some", not a claim about how many there will be. */
function placeholderSlots(count: number): { ready: boolean; heading: string }[] {
  return Array.from({ length: count || 6 }, () => ({ ready: false, heading: '—' }))
}

function shortId(id: string | null): string {
  if (!id) return '—'
  return id.replace(/-/g, '').slice(0, 6)
}

function BusyDialog(): ReactElement {
  const store = useStore()
  const [retrying, setRetrying] = useState(false)
  const runs = store.config?.runs

  return (
    <div className="scrim">
      <div className="dialog-box" style={{ width: 540 }}>
        <div className="kicker" style={{ marginBottom: 12 }}>
          429 · every pipeline slot busy
        </div>
        <div style={{ fontSize: 21, letterSpacing: '-.015em', marginBottom: 8 }}>
          Both slots are busy.
        </div>
        <p className="dim" style={{ fontSize: 14, margin: '0 0 18px' }}>
          This deployment runs a fixed number of analyses at a time on purpose — one more would slow
          every other and spend the day&rsquo;s LLM budget faster than it earns. Your question was
          not queued and not lost; it is sitting in the box, ready to send.
        </p>
        <div className="mono-block" style={{ marginBottom: 18 }}>
          {`active_runs   ${runs?.active ?? '—'} of ${runs?.limit ?? '—'}\nruns_today    ${runs?.runs_today ?? '—'} of ${runs?.daily_limit ?? '—'}`}
        </div>
        <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.5, marginBottom: 18 }}>
          Phase and per-paper progress only — the questions in the other slots are not shown, and
          nothing here predicts a finish time.
        </div>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setRetrying((value) => !value)}
            style={{ whiteSpace: 'nowrap', fontSize: 13 }}
          >
            {retrying ? 'Stop retrying' : 'Keep my question and retry automatically'}
          </button>
          <span className="dim num" style={{ fontSize: 11.5 }}>
            {retrying
              ? 'Retrying when a slot frees · nothing is sent until then'
              : 'Your question stays in the box. Nothing is queued server-side.'}
          </span>
        </div>
      </div>
    </div>
  )
}

function FailedTakeover(): ReactElement {
  const store = useStore()
  return (
    <div className="takeover">
      <div style={{ maxWidth: 640 }}>
        <div className="kicker" style={{ color: 'var(--n-con)', marginBottom: 14 }}>
          Run failed · phase {store.run.phase}
        </div>
        <h2 style={{ fontSize: 30, letterSpacing: '-.02em', margin: '0 0 12px' }}>
          The run stopped before it could produce a report.
        </h2>
        <p className="dim" style={{ margin: '0 0 22px' }}>
          Nodus stops rather than spending the LLM budget on a partial retrieval. The structured
          query is kept, so re-running costs one call.
        </p>
        <div className="mono-block" style={{ marginBottom: 26 }}>
          {`error       RunFailed\nmessage     ${store.run.errorMessage ?? 'no message recorded'}\nfailed_at   phase=${store.run.phase}\npapers_stored ${store.run.processedCount}`}
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => store.startRun()}
            style={{ whiteSpace: 'nowrap', fontSize: 13 }}
          >
            Retry run
          </button>
          <button
            type="button"
            className="btn btn-ghost dim"
            onClick={() => store.go('history')}
            style={{ whiteSpace: 'nowrap', fontSize: 13 }}
          >
            Back to history
          </button>
        </div>
      </div>
    </div>
  )
}

function CancelledTakeover(): ReactElement {
  const store = useStore()
  const { run } = store
  return (
    <div className="takeover">
      <div style={{ maxWidth: 640 }}>
        <div className="kicker" style={{ marginBottom: 14 }}>
          Cancelled at {clock(run.elapsedSeconds)} · phase {run.phase}
        </div>
        <h2 style={{ fontSize: 30, letterSpacing: '-.02em', margin: '0 0 12px' }}>
          You stopped this run after {run.processedCount} of {run.paperTotal} papers.
        </h2>
        <p className="dim" style={{ margin: '0 0 22px' }}>
          Papers already normalised and their {run.claimsExtracted} claims are kept in storage, so a
          re-run reuses them instead of paying for extraction twice. No clusters were formed and no
          report was written.
        </p>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => store.startRun()}
            style={{ whiteSpace: 'nowrap', fontSize: 13 }}
          >
            Resume from {run.processedCount} papers
          </button>
          <button
            type="button"
            className="btn btn-ghost dim"
            onClick={() => store.go('history')}
            style={{ whiteSpace: 'nowrap', fontSize: 13 }}
          >
            Back to history
          </button>
        </div>
      </div>
    </div>
  )
}
