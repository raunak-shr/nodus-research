/** The passage a claim was extracted from.
 *
 *  The highlight is placed by the offsets `claims.source` returned, never by
 *  searching the paragraph for the quote: extraction normalises whitespace and
 *  case, so a search would either miss or highlight the wrong span, and either
 *  would misrepresent what was verified.
 */

import type { ReactElement } from 'react'

import { KIND_TITLE, sourceKind } from '../lib/evidence'
import type { ClaimSourceRead } from '../lib/types'

const KIND_CLASS = {
  verified: 'prov prov-verified',
  approximate: 'prov prov-approximate',
  abstract: 'prov prov-abstract',
  unavailable: 'prov prov-unavailable',
} as const

export function SourcePanel({
  source,
  claimRef,
  onClose,
}: {
  source: ClaimSourceRead | null
  claimRef: string
  onClose: () => void
}): ReactElement {
  const kind = source ? sourceKind(source) : 'unavailable'
  const hasContext =
    source?.available &&
    typeof source.context === 'string' &&
    typeof source.highlight_start === 'number' &&
    typeof source.highlight_end === 'number'

  const context = source?.context ?? ''
  const start = source?.highlight_start ?? 0
  const end = source?.highlight_end ?? 0

  return (
    <aside className="src-panel">
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
          padding: '20px 22px 14px',
          borderBottom: '2px solid var(--n-line2)',
        }}
      >
        <div style={{ flex: '1 1 auto', minWidth: 0 }}>
          <div className="kicker-sm" style={{ marginBottom: 8 }}>
            Source text
          </div>
          <span className={KIND_CLASS[kind]} style={{ cursor: 'default' }}>
            {KIND_TITLE[kind]}
          </span>
        </div>
        <button
          type="button"
          className="chip-btn"
          onClick={onClose}
          style={{ marginLeft: 'auto', flex: '0 0 auto' }}
        >
          Close
        </button>
      </div>

      <div
        style={{
          padding: '18px 22px 26px',
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        {source === null ? (
          <div className="dim" style={{ fontSize: 13 }}>
            Loading the passage…
          </div>
        ) : (
          <>
            <div className="num faint" style={{ fontSize: 11.5, lineHeight: 1.5 }}>
              claim {claimRef} · {source.citation}
              <br />
              {[
                source.section ? `section ${source.section}` : 'no section recorded',
                source.page ? `page ${source.page}` : 'no page',
                `origin ${source.origin ?? 'full_text'}`,
                `source_match ${source.match}`,
              ].join(' · ')}
            </div>

            {hasContext ? (
              <>
                <div
                  className="dim pretty"
                  style={{
                    fontSize: 14,
                    lineHeight: 1.65,
                    borderLeft: '2px solid var(--n-line2)',
                    paddingLeft: 14,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {context.slice(0, start)}
                  <mark
                    style={{
                      background: 'color-mix(in srgb, var(--color-accent) 24%, transparent)',
                      color: 'var(--n-text)',
                      boxShadow: 'inset 0 -2px 0 var(--color-accent)',
                      padding: '0 1px',
                    }}
                  >
                    {context.slice(start, end)}
                  </mark>
                  {context.slice(end)}
                </div>
                <div className="num faint" style={{ fontSize: 11 }}>
                  highlight_start {start} · highlight_end {end}
                </div>
              </>
            ) : (
              <div
                className="pretty"
                style={{
                  fontSize: 14,
                  lineHeight: 1.65,
                  borderLeft: '2px dotted var(--n-line2)',
                  paddingLeft: 14,
                }}
              >
                “{source.quote ?? source.claim_text}”
              </div>
            )}

            {source.reason ? (
              <div className="dim pretty" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                {source.reason}
              </div>
            ) : null}

            {source.pdf_url ? (
              <a
                className="btn btn-secondary"
                href={source.pdf_url}
                target="_blank"
                rel="noreferrer"
                style={{
                  color: 'var(--n-text)',
                  fontSize: 12,
                  borderColor: 'var(--n-line2)',
                  alignSelf: 'flex-start',
                  whiteSpace: 'nowrap',
                }}
              >
                {source.page ? `Open PDF at page ${source.page}` : 'Open PDF'}
              </a>
            ) : null}
          </>
        )}
      </div>
    </aside>
  )
}
