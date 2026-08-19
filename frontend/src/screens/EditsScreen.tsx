import type { ReactElement } from 'react'

import { useStore } from '../state/store'

export function EditsScreen(): ReactElement {
  const store = useStore()

  return (
    <div className="screen" style={{ maxWidth: 1060 }}>
      <div className="kicker" style={{ marginBottom: 14 }}>
        Edits
      </div>
      <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>
        What a person changed, kept beside what the machine computed
      </h2>
      <p className="dim" style={{ maxWidth: 660, margin: '0 0 34px' }}>
        Every edit sets <span style={{ color: 'var(--n-text)' }}>user_edited: true</span> and pins the
        object. A re-analysis of the same question recomputes everything else and leaves these alone.
        The computed value is never replaced, only shown alongside.
      </p>

      {store.edits.length === 0 ? (
        <div style={{ border: '1px dashed var(--n-line2)', padding: '22px 24px', maxWidth: 640 }}>
          <div style={{ fontSize: 15, marginBottom: 8 }}>Nothing has been overridden yet.</div>
          <div className="dim" style={{ fontSize: 13.5, lineHeight: 1.6 }}>
            Retitle a cluster, override a quality tier or flip a claim&rsquo;s stance on the cluster
            screen, and the change appears here beside the computed value it replaced in the reading
            view.
          </div>
          {store.clusters.length ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => store.openCluster(store.clusters[0].id)}
              style={{ whiteSpace: 'nowrap', fontSize: 12.5, marginTop: 16 }}
            >
              Open cluster {store.clusters[0].id.slice(0, 8)}
            </button>
          ) : null}
        </div>
      ) : (
        <div>
          <div
            className="kicker-sm"
            style={{
              display: 'grid',
              gridTemplateColumns: '150px minmax(0, 1fr) minmax(0, 1fr) 60px',
              gap: 22,
              paddingBottom: 10,
              borderBottom: '1px solid var(--n-line2)',
            }}
          >
            <div>field</div>
            <div>computed</div>
            <div>yours</div>
            <div>at</div>
          </div>
          {store.edits.map((edit, index) => (
            <div
              key={`${edit.field}-${index}`}
              style={{
                display: 'grid',
                gridTemplateColumns: '150px minmax(0, 1fr) minmax(0, 1fr) 60px',
                gap: 22,
                padding: '16px 0',
                borderBottom: '2px solid var(--n-line2)',
                fontSize: 13.5,
                lineHeight: 1.5,
              }}
            >
              <div>
                <div>{edit.field}</div>
                <div className="faint num" style={{ fontSize: 11 }}>
                  {edit.object}
                </div>
              </div>
              <div
                className="dim pretty"
                style={{ textDecoration: 'line-through', textDecorationColor: 'var(--n-faint)' }}
              >
                {edit.computed}
              </div>
              <div className="pretty" style={{ color: 'var(--color-accent-700)' }}>
                {edit.yours}
              </div>
              <div className="faint num" style={{ fontSize: 11.5 }}>
                {edit.at}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
