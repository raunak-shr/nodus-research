/** Every refusal, failure and degenerate case, reachable in one click.
 *
 *  These are designed screens rather than thrown errors, and they are the ones
 *  hardest to reach by accident — so they get a door. */

import type { ReactElement } from 'react'

import { useStore } from '../state/store'

export function StatesScreen(): ReactElement {
  const store = useStore()

  const unrated = store.clusters.find((c) => c.quality_tier === 'unrated') ?? store.clusters[0]
  const noDrivers = store.clusters.find((c) => (c.disagreement_drivers ?? []).length === 0)
  const contested = store.clusters.find((c) => c.contradiction_count >= 2)

  const cards: { label: string; go: () => void; enabled: boolean }[] = [
    {
      label: 'Backpressure — 429, every pipeline slot busy',
      go: () => store.go('run', 'busy'),
      enabled: true,
    },
    { label: 'Seq gap — reload prompt', go: store.simulateGap, enabled: true },
    { label: 'Failed run — retrieval stopped after four attempts', go: () => store.go('run', 'failed'), enabled: true },
    { label: 'Cancelled run — stopped part way through the papers', go: () => store.go('run', 'cancelled'), enabled: true },
    {
      label: 'Clarification needed — question too broad',
      go: () => {
        store.setQuestion('Is exercise good?')
        store.interpret()
        store.go('query')
      },
      enabled: true,
    },
    { label: 'Partial degradation — a report built on fewer papers than retrieved', go: () => store.go('report'), enabled: Boolean(store.report) },
    {
      label: 'Unrated quality — single-paper cluster',
      go: () => unrated && store.openCluster(unrated.id),
      enabled: Boolean(unrated),
    },
    {
      label: 'Zero disagreement drivers',
      go: () => noDrivers && store.openCluster(noDrivers.id),
      enabled: Boolean(noDrivers),
    },
    {
      label: 'Overridden tier — model said medium, I said high',
      go: () => {
        if (!contested) return
        store.overrideTier(contested.id, 'high')
        store.openCluster(contested.id)
      },
      enabled: Boolean(contested),
    },
    { label: 'Print variant — A4, 18 mm margins', go: () => store.go('print'), enabled: true },
  ]

  return (
    <div className="screen" style={{ maxWidth: 820 }}>
      <div className="kicker" style={{ marginBottom: 14 }}>
        States
      </div>
      <h2 style={{ fontSize: 30, letterSpacing: '-.022em', margin: '0 0 8px' }}>
        Every refusal, failure and degenerate case
      </h2>
      <p className="dim" style={{ maxWidth: 600, margin: '0 0 32px' }}>
        Each of these is a designed screen rather than a thrown error. Pick one to jump straight to
        it in context.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {cards.map((card) => (
          <button
            key={card.label}
            type="button"
            className="row-btn"
            onClick={card.go}
            disabled={!card.enabled}
            style={{ opacity: card.enabled ? 1 : 0.45, cursor: card.enabled ? 'pointer' : 'not-allowed' }}
          >
            <span>{card.label}</span>
            <span className="faint" style={{ fontSize: 12 }}>
              {card.enabled ? 'open →' : 'needs a completed run'}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
