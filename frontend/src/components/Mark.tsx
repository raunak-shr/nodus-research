/** The Nodus mark: two nodes and the edge between them, knocked out of a solid
 *  accent square.
 *
 *  One definition, used by the landing header and footer, the app sidebar, and
 *  — as the same geometry drawn in SVG — the favicon in `public/favicon.svg`.
 *  The sidebar used to draw its own outlined version, accent lines on the page
 *  background, which is this mark inverted: the same shape reading as a
 *  different logo depending on which screen you were on.
 *
 *  The knockouts are `--n-bg`, so the mark sits on the page background in
 *  either theme. Scales with `size` — 34px in the landing header, 22px in the
 *  sidebar and footer.
 */

import type { ReactElement } from 'react'

export function Mark({ size }: { size: number }): ReactElement {
  const dot = Math.round(size * 0.21)
  const inset = Math.round(size * 0.18)
  const edge = Math.round(size * 0.56)
  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        flex: `0 0 ${size}px`,
        background: 'var(--color-accent)',
        position: 'relative',
        display: 'block',
      }}
    >
      <span style={{ position: 'absolute', left: inset, top: inset, width: dot, height: dot, background: 'var(--n-bg)', display: 'block' }} />
      <span style={{ position: 'absolute', right: inset, bottom: inset, width: dot, height: dot, background: 'var(--n-bg)', display: 'block' }} />
      <span
        style={{
          position: 'absolute',
          left: inset + dot / 2,
          top: inset + dot / 2,
          width: edge,
          height: 2,
          background: 'var(--n-bg)',
          transform: 'rotate(45deg)',
          transformOrigin: 'left center',
          display: 'block',
        }}
      />
    </span>
  )
}
