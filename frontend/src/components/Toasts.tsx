/** Notices that do not stop the screen.
 *
 *  A dropped-event gap was a modal over the run: a scrim, a dialog, and no way
 *  past it without answering. It is worth saying and worth acting on, but the
 *  run behind it is still running and most of what is on screen is still right,
 *  so blocking all of it to report a break in the sequence costs more than the
 *  break does. A toast says the same thing from the corner and leaves the run
 *  visible underneath.
 *
 *  It has no timer. A toast normally describes something already over by the
 *  time it fades; this one describes a state the screen is still in, and a
 *  notice that removes itself would leave stale data on screen with nothing
 *  left to say so.
 */

import type { ReactElement } from 'react'

import { useStore } from '../state/store'

export function Toasts(): ReactElement | null {
  const store = useStore()

  if (store.flag !== 'seqgap') return null

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      <SeqGapToast />
    </div>
  )
}

function SeqGapToast(): ReactElement {
  const store = useStore()
  const gap = store.gap
  const missed = gap?.missed ?? 0
  const plural = missed === 1 ? 'event' : 'events'

  return (
    <div className="toast">
      <div className="toast-head">
        <span className="kicker" style={{ color: 'var(--color-accent-400)' }}>
          Event gap detected
        </span>
        <button
          type="button"
          className="toast-close"
          aria-label="Dismiss"
          onClick={() => store.setFlag(null)}
        >
          ×
        </button>
      </div>
      <div style={{ fontSize: 14.5, letterSpacing: '-.005em', marginBottom: 6 }}>
        {gap
          ? missed === 1
            ? `Missed event ${gap.lastApplied + 1}.`
            : `Missed events ${gap.lastApplied + 1} – ${gap.received - 1}.`
          : 'Events were dropped.'}
      </div>
      <p className="dim" style={{ fontSize: 12.5, lineHeight: 1.5, margin: '0 0 10px' }}>
        {gap
          ? `The socket delivered seq ${gap.received} after ${gap.lastApplied}, so ${missed} ${plural} never arrived.`
          : 'The socket reported a break in the sequence.'}{' '}
        What is on screen may be behind or out of order, and Nodus will not guess the difference.
      </p>
      {gap ? (
        <div className="num faint" style={{ fontSize: 11, marginBottom: 12 }}>
          {`last_applied ${gap.lastApplied} · received ${gap.received} · gap ${missed}`}
        </div>
      ) : null}
      <button
        type="button"
        className="btn btn-primary"
        onClick={store.reloadRun}
        style={{ whiteSpace: 'nowrap', fontSize: 12.5 }}
      >
        Reload run state
      </button>
    </div>
  )
}
