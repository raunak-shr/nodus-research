import type { ReactElement } from 'react'

import { relativeDay } from '../lib/format'
import { DEMO_STATS } from '../data/demoRun'
import { useStore } from '../state/store'

export function HistoryScreen(): ReactElement {
  const store = useStore()
  // A history is one reader's, so the screen says whose rather than leaving a
  // short list looking like the deployment has only ever run four questions.
  const scope = store.ownerNote

  return (
    <div className="screen" style={{ maxWidth: 1060 }}>
      <div className="kicker" style={{ marginBottom: 14 }}>
        History
      </div>
      <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>Past runs</h2>
      <p className="dim" style={{ fontSize: 13.5, lineHeight: 1.6, margin: '0 0 30px', maxWidth: 620 }}>
        {store.mode === 'demo'
          ? 'Fixture runs from the demo corpus. Nothing here was stored, and nothing is scoped — on a live connection this list is only the runs this browser started.'
          : 'Only the runs started from here. Nodus has no accounts, so a history belongs to the browser that made it: clearing site data mints a new identity, and these runs stop being reachable from this one.'}
        {scope && store.mode !== 'demo' ? <span className="faint"> {scope}.</span> : null}
      </p>

      <div
        className="kicker-sm"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) 150px 100px 84px 110px',
          gap: 22,
          paddingBottom: 10,
          borderBottom: '1px solid var(--n-line2)',
        }}
      >
        <div>question</div>
        <div>status</div>
        <div>papers</div>
        <div>clusters</div>
        <div>started</div>
      </div>

      {store.queries.length === 0 && store.lastError ? (
        <div style={{ padding: '24px 0', maxWidth: 640 }}>
          <div style={{ color: 'var(--n-con)', marginBottom: 8 }}>
            The server could not list past runs.
          </div>
          <div className="mono-block">
            {`action   ${store.lastError.action}
message  ${store.lastError.message}`}
          </div>
          <div className="dim" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 10 }}>
            This is the backend reporting a failure, not an empty history — the two look identical
            in a blank table, so Nodus says which one it is.
          </div>
        </div>
      ) : store.queries.length === 0 ? (
        <div className="dim" style={{ padding: '24px 0' }}>
          No runs yet.
        </div>
      ) : (
        store.queries.map((query) => {
          const stats = DEMO_STATS[query.id]
          return (
            <div
              key={query.id}
              className="hover-row"
              onClick={() => store.openQuery(query.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter') store.openQuery(query.id)
              }}
              style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) 150px 100px 84px 110px',
                gap: 22,
                padding: '16px 0',
                borderBottom: '2px solid var(--n-line2)',
                cursor: 'pointer',
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div className="pretty" style={{ fontSize: 14.5, lineHeight: 1.4, marginBottom: 4 }}>
                  {query.raw_query}
                </div>
                <div className="faint num" style={{ fontSize: 11 }}>
                  run {query.id.replace(/-/g, '').slice(0, 6)}
                  {stats ? ` · ${stats.duration}` : ''}
                  {query.parent_query_id
                    ? ` · follow-up of ${query.parent_query_id.replace(/-/g, '').slice(0, 6)}`
                    : ''}
                </div>
              </div>
              <div
                style={{
                  fontSize: 11.5,
                  letterSpacing: '.04em',
                  textTransform: 'uppercase',
                  color:
                    query.status === 'failed'
                      ? 'var(--n-con)'
                      : query.status === 'completed'
                        ? 'var(--n-dim)'
                        : 'var(--color-accent)',
                }}
              >
                {query.status}
              </div>
              <div className="dim num" style={{ fontSize: 12.5 }}>
                {query.paper_count || '—'}
              </div>
              <div className="dim num" style={{ fontSize: 12.5 }}>
                {stats ? stats.clusters || '—' : '—'}
              </div>
              <div className="faint num" style={{ fontSize: 12.5 }}>
                {relativeDay(query.created_at)}
              </div>
            </div>
          )
        })
      )}

      {store.config ? (
        <div className="faint num" style={{ marginTop: 26, fontSize: 12 }}>
          {store.config.runs.limit} pipeline slots · {store.config.runs.active} in use ·{' '}
          {store.config.runs.runs_today} of {store.config.runs.daily_limit} runs today
        </div>
      ) : (
        <div className="faint num" style={{ marginTop: 26, fontSize: 12 }}>
          Slot and daily-budget figures come from meta.config on a live connection.
        </div>
      )}
    </div>
  )
}
