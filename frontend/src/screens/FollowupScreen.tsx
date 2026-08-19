/** A follow-up runs against the papers already retrieved for its parent, so it
 *  costs less and stays comparable. The chain of questions is kept as evidence
 *  of how the reading narrowed. */

import type { ReactElement } from 'react'

import { timeOfDay } from '../lib/format'
import { useStore } from '../state/store'

export function FollowupScreen(): ReactElement {
  const store = useStore()
  const parent = store.queries.find((q) => q.id === store.activeQueryId) ?? store.queries[0] ?? null
  const children = store.queries.filter((q) => q.parent_query_id === parent?.id)

  return (
    <div className="screen" style={{ maxWidth: 980 }}>
      <div className="kicker" style={{ marginBottom: 14 }}>
        Follow-up
      </div>
      <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>Ask inside an answer</h2>
      <p className="dim" style={{ maxWidth: 620, margin: '0 0 38px' }}>
        A follow-up runs against the papers already retrieved for its parent, so it costs less and
        stays comparable. The chain of questions is kept as evidence of how the reading narrowed.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', marginBottom: 40 }}>
        {parent ? (
          <ChainRow
            when={`${timeOfDay(parent.created_at)} · root`}
            dot={<div style={{ width: 11, height: 11, background: 'var(--color-accent)', flex: '0 0 11px' }} />}
            spine
          >
            <div style={{ fontSize: 16.5, lineHeight: 1.4, marginBottom: 5 }}>{parent.raw_query}</div>
            <div className="dim num" style={{ fontSize: 12 }}>
              run {parent.id.replace(/-/g, '').slice(0, 6)} · {parent.paper_count} papers ·{' '}
              {store.clusters.length} clusters
            </div>
          </ChainRow>
        ) : null}

        {children.map((child) => (
          <ChainRow
            key={child.id}
            when={`${timeOfDay(child.created_at)} · child`}
            dot={
              <div
                style={{
                  width: 11,
                  height: 11,
                  background: 'var(--n-bg)',
                  border: '2px solid var(--color-accent-400)',
                  flex: '0 0 11px',
                }}
              />
            }
            spine
          >
            <div style={{ fontSize: 16.5, lineHeight: 1.4, marginBottom: 5 }}>{child.raw_query}</div>
            <div className="dim num" style={{ fontSize: 12 }}>
              run {child.id.replace(/-/g, '').slice(0, 6)} · scoped to {child.paper_count} papers from parent
            </div>
          </ChainRow>
        ))}

        <ChainRow
          when="now · drafting"
          dot={
            <div
              style={{
                width: 11,
                height: 11,
                background: 'var(--n-bg)',
                border: '2px dashed var(--n-line2)',
                flex: '0 0 11px',
              }}
            />
          }
        >
          <div style={{ border: '1px solid var(--n-line2)', background: 'var(--n-panel)', padding: 2 }}>
            <textarea
              className="bare"
              value={store.followupQuestion}
              onChange={(event) => store.setFollowupQuestion(event.target.value)}
              rows={2}
              style={{ fontSize: 17, lineHeight: 1.45, padding: '14px 16px 6px' }}
            />
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 12px 10px 16px',
                gap: 12,
                flexWrap: 'wrap',
              }}
            >
              <div className="faint" style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 11.5 }}>
                <span>scope: {parent?.paper_count ?? 0} papers from run {parent?.id.replace(/-/g, '').slice(0, 6) ?? '—'}</span>
                <span>no new retrieval · re-extraction only</span>
              </div>
              <button
                type="button"
                className="btn btn-primary"
                onClick={store.runFollowup}
                disabled={store.followupQuestion.trim().length < 3 || !parent}
                style={{ whiteSpace: 'nowrap', fontSize: 12.5 }}
              >
                Run follow-up
              </button>
            </div>
          </div>
        </ChainRow>
      </div>

      <div style={{ borderTop: '2px solid var(--n-line2)', paddingTop: 22, maxWidth: 640 }}>
        <div className="kicker" style={{ marginBottom: 10 }}>
          What the child run inherits
        </div>
        <div className="dim" style={{ fontSize: 13.5, lineHeight: 1.65 }}>
          The parent&rsquo;s normalised papers and claim embeddings, its pinned edits, and its
          structured query as context. What it does not inherit: cluster membership and quality
          scores, both recomputed against the narrower question.
        </div>
      </div>
    </div>
  )
}

function ChainRow({
  when,
  dot,
  spine = false,
  children,
}: {
  when: string
  dot: ReactElement
  spine?: boolean
  children: React.ReactNode
}): ReactElement {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 24px minmax(0, 1fr)', minHeight: spine ? 88 : undefined }}>
      <div className="faint num" style={{ fontSize: 11.5, paddingTop: 2 }}>
        {when}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {dot}
        {spine ? <div style={{ width: 1, flex: 1, background: 'var(--n-line2)' }} /> : null}
      </div>
      <div style={{ padding: spine ? '0 0 24px 16px' : '0 0 0 16px' }}>{children}</div>
    </div>
  )
}
