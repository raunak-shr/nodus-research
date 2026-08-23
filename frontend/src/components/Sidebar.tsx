import type { ReactElement } from 'react'

import { Mark } from './Mark'
import { useStore, type Screen } from '../state/store'

const ICONS: Record<Screen, string> = {
  landing: 'M4 11l8-7 8 7M6 10v10h12V10M10 20v-6h4v6',
  query: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 8v8M8 12h8',
  run: 'M3 12h4l3-8 4 16 3-8h4',
  report: 'M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6',
  papers: 'M4 8l8-4 8 4-8 4zM4 12l8 4 8-4M4 16l8 4 8-4',
  cluster:
    'M6 12a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0M16 6a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0M16 18a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0M11.2 10.8l5-3M11.2 13.2l5 3',
  edits: 'M4 20h4L20 8l-4-4L4 16z',
  chat: 'M4 5h16v11H9l-5 4z',
  history: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M12 7v5l4 2',
  print: 'M7 8V3h10v5M7 16H5V9h14v7h-2M7 13h10v8H7z',
}

const ITEMS: { id: Screen; label: string }[] = [
  { id: 'landing', label: 'Home' },
  { id: 'query', label: 'New query' },
  { id: 'run', label: 'Live run' },
  { id: 'report', label: 'Report' },
  { id: 'papers', label: 'Papers' },
  { id: 'cluster', label: 'Cluster detail' },
  { id: 'edits', label: 'Edits' },
  { id: 'chat', label: 'Ask the report' },
  { id: 'history', label: 'History' },
  { id: 'print', label: 'Print sheet' },
]

export function Sidebar(): ReactElement {
  const store = useStore()

  const badges: Partial<Record<Screen, string>> = {
    report: store.report?.sections?.length ? String(store.report.sections.length) : '',
    papers: store.papers.length ? String(store.papers.length) : '',
    history: store.queries.length ? String(store.queries.length) : '',
    edits: store.edits.length ? String(store.edits.length) : '',
  }

  const socketLabel =
    store.mode === 'demo'
      ? 'demo'
      : store.socketStatus === 'desynced'
        ? 'desynced'
        : store.socketStatus === 'open'
          ? 'open'
          : store.socketStatus

  return (
    <nav className="sidebar">
      <div style={{ padding: '0 18px', display: 'flex', alignItems: 'center', gap: 9 }}>
        <Mark size={22} />
        <div
          style={{
            fontFamily: 'var(--font-heading)',
            fontWeight: 500,
            fontSize: 16,
            letterSpacing: '-.01em',
          }}
        >
          Nodus
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`nav-item${store.screen === item.id ? ' on' : ''}`}
            // Navigation only. Opening the live run used to *start* one when
            // there was nothing to show, which submitted whatever was in the
            // question box — a click on a nav item is not consent to spend a
            // pipeline slot. The run screen says there is no run instead.
            onClick={() => store.go(item.id)}
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ flex: '0 0 16px', opacity: 0.9 }}
              aria-hidden="true"
            >
              <path d={ICONS[item.id]} />
            </svg>
            <span style={{ whiteSpace: 'nowrap', flex: '1 1 auto' }}>{item.label}</span>
            <span className="badge">{badges[item.id] ?? ''}</span>
          </button>
        ))}
      </div>

      <div
        style={{
          marginTop: 'auto',
          padding: '0 18px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        <div className="kicker" style={{ fontSize: 11 }}>
          Appearance
        </div>
        {/* One switch rather than two buttons. With a pair, the current theme
            is something you deduce from which one is filled; with a switch it
            is the label, and the knob says which way it will go. */}
        <button
          type="button"
          className={`theme-toggle ${store.theme}`}
          onClick={() => store.setTheme(store.theme === 'dark' ? 'light' : 'dark')}
          aria-pressed={store.theme === 'light'}
          aria-label={`Appearance: ${store.theme}. Switch to ${
            store.theme === 'dark' ? 'light' : 'dark'
          }.`}
        >
          <span>{store.theme === 'dark' ? 'Dark' : 'Light'}</span>
          <span className="track" aria-hidden="true">
            <span className="knob" />
          </span>
        </button>
        <div className="num" style={{ fontSize: 11, color: 'var(--n-faint)', lineHeight: 1.5 }}>
          ws /api/v2/ws ·{' '}
          <span
            style={{
              color:
                store.socketStatus === 'desynced'
                  ? 'var(--n-con)'
                  : store.mode === 'demo'
                    ? 'var(--n-faint)'
                    : 'var(--color-accent-400)',
            }}
          >
            {socketLabel}
          </span>
          <br />
          seq {store.seq}
        </div>
        {store.connectionNote ? (
          <div style={{ fontSize: 10.5, color: 'var(--n-faint)', lineHeight: 1.5 }}>
            {store.connectionNote}
          </div>
        ) : null}
        {store.lastError ? (
          <div className="num" style={{ fontSize: 10.5, color: 'var(--n-con)', lineHeight: 1.5 }}>
            {store.lastError.action} failed
          </div>
        ) : null}
      </div>
    </nav>
  )
}
