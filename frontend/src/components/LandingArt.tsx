/** The landing page's drawings.
 *
 *  Each one draws a mechanism the page describes, in the grammar the app itself
 *  uses: square nodes, a filled square for a claim that supports, a hollow one
 *  for a claim that contradicts, grey for neutral, and the accent for an origin
 *  or a result. None is decoration — every mark stands for something the
 *  pipeline does, and the numbers are the page's worked example, passed in by
 *  the page rather than retyped here.
 *
 *  Colour comes from the theme tokens through the `lp-svg` classes in
 *  landing.css, so the drawings follow light and dark with the page. Wide ones
 *  sit in a scroller with a minimum width instead of shrinking: scaled down to
 *  a phone, their labels would fall below any readable size.
 */

import { useId, type ReactElement } from 'react'

import { SCREEN_ICONS } from './Sidebar'

export type ClaimStance = 'supports' | 'contradicts' | 'neutral'
export type Relationship = 'origin' | 'supports' | 'contradicts' | 'extends'

export interface ChainPoint {
  rel: Relationship
  year: number
  /** "Krogh 2009" — the citation as the app prints it. */
  short: string
  stance: ClaimStance
}

/** SVG ids must be unique per document, and React's contain colons. */
function useSvgId(): string {
  return useId().replace(/:/g, '')
}

function Arrowhead({ id }: { id: string }): ReactElement {
  return (
    <marker id={id} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L8 4L0 8z" className="f-ink" />
    </marker>
  )
}

/** A node square in the app's stance grammar, centred on (x, y). */
function Square({ x, y, rel, size = 12 }: { x: number; y: number; rel: Relationship | ClaimStance; size?: number }): ReactElement {
  const half = size / 2
  const cls =
    rel === 'origin'
      ? 'f-acc'
      : rel === 'supports'
        ? 'f-ink'
        : rel === 'contradicts'
          ? 'f-panel s-ink'
          : rel === 'extends'
            ? 'f-panel s-faint'
            : 'f-neu'
  return <rect x={x - half} y={y - half} width={size} height={size} className={cls} strokeWidth={2} />
}

// -- 02: the problem ----------------------------------------------------------

/** A summary with a citation list beside claims tied to their passages. The
 *  left half has no line from any sentence to any paper, because a summary has
 *  none to draw; the right half is nothing but those lines. */
export function ProblemArt(): ReactElement {
  const paragraph = [304, 322, 286, 314, 298, 262, 310, 176]
  const sheets = [404, 440, 476, 512]
  const claims = [36, 92, 148]
  // Paper A holds the passages behind the first two claims, paper B the third.
  const passages = [
    { y: 52.5, paper: 0 },
    { y: 82.5, paper: 0 },
    { y: 162.5, paper: 1 },
  ]
  return (
    <svg className="lp-svg" viewBox="0 0 1168 222" role="img" aria-label="On the left, a paragraph with four numbered citations that link to four papers but not to any sentence. On the right, three claims, each linked to a highlighted passage inside a paper.">
      <text x={0} y={14} className="t-faint">a summary and its citation list</text>
      {paragraph.map((w, i) => (
        <rect key={i} x={0} y={36 + i * 16} width={w} height={6} className="f-line" />
      ))}
      {/* Each numbered citation leads to its paper; nothing leads from any
          sentence to a citation. The gap is the drawing's whole point. */}
      <line x1={336} y1={92} x2={390} y2={92} className="s-line" strokeWidth={1.25} strokeDasharray="3 4" />
      <text x={363} y={86} textAnchor="middle" className="t-acc t-strong">?</text>
      {sheets.map((sx, i) => (
        <g key={sx}>
          <rect x={sx} y={40} width={30} height={42} className="f-panel s-line" strokeWidth={1.25} />
          {[0, 1, 2].map((k) => (
            <rect key={k} x={sx + 6} y={48 + k * 9} width={18 - k * 4} height={3} className="f-line" />
          ))}
          <line x1={sx + 15} y1={82} x2={sx + 15} y2={100} className="s-line" strokeWidth={1.25} />
          <rect x={sx + 2} y={100} width={26} height={18} className="f-none s-line" strokeWidth={1.25} />
          <text x={sx + 15} y={113} textAnchor="middle" className="t-dim">
            {i + 1}
          </text>
        </g>
      ))}
      <text x={0} y={210} className="t-dim">Which sentence came from which paper?</text>

      <text x={600} y={14} className="t-faint">claims tied to their passages</text>
      {claims.map((y, i) => (
        <g key={y}>
          <rect x={600} y={y} width={240} height={40} className="f-none s-ink" strokeWidth={1.5} />
          <text x={614} y={y + 25} className="t-acc t-strong">¶</text>
          <rect x={634} y={y + 13} width={168 - i * 18} height={5} className="f-dim" />
          <rect x={634} y={y + 23} width={116 + i * 14} height={5} className="f-dim" />
          <path
            d={`M840 ${y + 20} H910 V${passages[i].y} H984`}
            className="f-none s-acc"
            strokeWidth={1.5}
          />
        </g>
      ))}
      {[
        { y: 28, h: 84, lines: 7, label: 'paper A' },
        { y: 130, h: 64, lines: 5, label: 'paper B' },
      ].map((sheet, p) => (
        <g key={sheet.label}>
          <rect x={980} y={sheet.y} width={84} height={sheet.h} className="f-panel s-line" strokeWidth={1.25} />
          {Array.from({ length: sheet.lines }, (_, k) => (
            <rect key={k} x={988} y={sheet.y + 10 + k * 10} width={k % 3 === 2 ? 48 : 66} height={4} className="f-line" />
          ))}
          {passages
            .filter((passage) => passage.paper === p)
            .map((passage) => (
              <rect key={passage.y} x={984} y={passage.y - 4} width={76} height={8} className="f-acc-soft s-acc" strokeWidth={1.25} />
            ))}
          <text x={1074} y={sheet.y + 12} className="t-faint">{sheet.label}</text>
        </g>
      ))}
      <text x={600} y={210} className="t-dim">Each claim opens the passage it was taken from.</text>
    </svg>
  )
}

// -- 03: lineage --------------------------------------------------------------

/** The example's chain on a real time axis, so the gaps between papers are
 *  the gaps between years. Styles match the chain list below it. */
export function LineageTimeline({ chain }: { chain: ChainPoint[] }): ReactElement {
  const lo = chain[0].year - 1
  const hi = chain[chain.length - 1].year + 1
  const x = (year: number): number => 24 + ((year - lo) / (hi - lo)) * 492
  const nodeY = 58
  const ticks: number[] = []
  for (let year = Math.ceil(lo / 5) * 5; year <= hi; year += 5) ticks.push(year)
  const first = x(chain[0].year)
  const last = x(chain[chain.length - 1].year)
  const span = chain[chain.length - 1].year - chain[0].year

  return (
    <svg className="lp-svg" viewBox="0 0 540 134" role="img" aria-label={`The ${chain.length} papers of the example cluster placed on a time axis from ${chain[0].year} to ${chain[chain.length - 1].year}, a span of ${span} years.`}>
      {chain.slice(1).map((point, i) => (
        <line
          key={point.short}
          x1={x(chain[i].year)}
          y1={nodeY}
          x2={x(point.year)}
          y2={nodeY}
          className="s-ink"
          strokeWidth={1.5}
          strokeDasharray={point.rel === 'contradicts' ? '4 3' : undefined}
        />
      ))}
      {chain.map((point, i) => {
        const cx = x(point.year)
        const labelY = i % 2 === 0 ? 38 : 22
        return (
          <g key={point.short}>
            <line x1={cx} y1={labelY + 4} x2={cx} y2={nodeY - 8} className="s-line" strokeWidth={1} />
            <text x={cx} y={labelY} textAnchor="middle" className={point.rel === 'origin' ? 't-acc' : 't-dim'}>
              {point.short.split(' ')[0]}
            </text>
            <Square x={cx} y={nodeY} rel={point.rel} />
          </g>
        )
      })}
      <line x1={24} y1={84} x2={516} y2={84} className="s-line" strokeWidth={1.25} />
      {ticks.map((year) => (
        <g key={year}>
          <line x1={x(year)} y1={84} x2={x(year)} y2={89} className="s-line" strokeWidth={1.25} />
          <text x={x(year)} y={101} textAnchor="middle" className="t-faint">
            {year}
          </text>
        </g>
      ))}
      {/* The label sits under the bracket, not on it: a halo only covers the
          glyphs, so the rule showed through between the words. */}
      <path d={`M${first} 108 V114 H${last} V108`} className="f-none s-faint" strokeWidth={1.25} />
      <text x={(first + last) / 2} y={128} textAnchor="middle" className="t-dim">
        span {span} years
      </text>
    </svg>
  )
}

// -- 04: controls -------------------------------------------------------------

/** Marks for the controls. Where a control lives on a screen, it is that
 *  screen's sidebar mark; the rest are drawn to the same 24-unit stroke. */
const CONTROL_ICONS: Record<string, string> = {
  interpret: 'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13M15.2 15.2 20 20',
  upload: 'M12 15V4M7.5 8.5 12 4l4.5 4.5M4 14v6h16v-6',
  run: SCREEN_ICONS.run,
  source: 'M11 20V4h7M15 4v16M11 12a4 4 0 0 1 0-8',
  edit: SCREEN_ICONS.edits,
  chat: SCREEN_ICONS.chat,
  followup: 'M6 4v7a5 5 0 0 0 5 5h8M15 12l4 4-4 4',
  graph: SCREEN_ICONS.graph,
  export: 'M12 4v11M7.5 10.5 12 15l4.5-4.5M5 20h14',
}

export type ControlIconName = keyof typeof CONTROL_ICONS

export function ControlIcon({ name }: { name: ControlIconName }): ReactElement {
  return (
    <svg
      className="lp-icon"
      viewBox="0 0 24 24"
      width={22}
      height={22}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={CONTROL_ICONS[name]} />
    </svg>
  )
}

// -- 05: the pipeline ---------------------------------------------------------

function Box({
  x,
  y,
  w,
  h = 36,
  label,
  strong = false,
}: {
  x: number
  y: number
  w: number
  h?: number
  label: string
  strong?: boolean
}): ReactElement {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} className="f-panel s-ink" strokeWidth={strong ? 2 : 1.5} />
      <text x={x + w / 2} y={y + h / 2 + 4.5} textAnchor="middle" className="t-node">
        {label}
      </text>
    </g>
  )
}

/** One run, left to right. The search and the upload branch leave the same
 *  structured question and rejoin before the first paper is read, which is the
 *  graph's own shape: from there on the two kinds of run are the same run. */
export function PipelineArt(): ReactElement {
  const arrow = `${useSvgId()}-arrow`
  const end = `url(#${arrow})`
  return (
    <svg className="lp-svg" viewBox="0 0 1168 238" role="img" aria-label="Stage 1: a question is structured, then either searched on Semantic Scholar and ranked down to twenty papers, or replaced by two to twenty uploaded PDFs. Stage 2: each paper is read from its best available text and up to twelve claims are extracted with quotes. Stage 3: claims are clustered by meaning, each cluster is weighed on lineage, disagreement and quality, and each becomes a report section.">
      <defs>
        <Arrowhead id={arrow} />
      </defs>

      <text x={0} y={16} className="t-faint">stage 1: find the papers</text>
      <text x={452} y={16} className="t-faint">stage 2: read them</text>
      <text x={792} y={16} className="t-faint">stage 3: cluster, weigh, write</text>
      <line x1={430} y1={4} x2={430} y2={230} className="s-line" strokeWidth={1} strokeDasharray="3 4" />
      <line x1={770} y1={4} x2={770} y2={230} className="s-line" strokeWidth={1} strokeDasharray="3 4" />

      <Box x={0} y={102} w={112} label="your question" />
      <line x1={112} y1={120} x2={132} y2={120} className="s-ink" strokeWidth={1.5} markerEnd={end} />
      <Box x={134} y={102} w={112} label="structure it" />

      <path d="M246 120 H258 V64 H270" className="f-none s-ink" strokeWidth={1.5} markerEnd={end} />
      <Box x={272} y={46} w={132} label="search + rank" />
      <text x={338} y={36} textAnchor="middle" className="t-faint">Semantic Scholar, top 20</text>

      <path d="M246 120 H258 V176 H270" className="f-none s-acc" strokeWidth={1.5} strokeDasharray="5 4" markerEnd={end} />
      <Box x={272} y={158} w={132} label="your PDFs" />
      <text x={338} y={212} textAnchor="middle" className="t-faint">2–20 files, your order</text>
      <text x={338} y={227} textAnchor="middle" className="t-faint">no search, no ranking</text>

      <path d="M404 64 H418 V120" className="f-none s-ink" strokeWidth={1.5} />
      <path d="M404 176 H418 V120" className="f-none s-acc" strokeWidth={1.5} strokeDasharray="5 4" />
      <line x1={418} y1={120} x2={450} y2={120} className="s-ink" strokeWidth={1.5} markerEnd={end} />

      {/* Stacked, because this stage runs once per paper, ten at a time. */}
      <rect x={462} y={92} width={148} height={36} className="f-panel s-line" strokeWidth={1.25} />
      <rect x={457} y={97} width={148} height={36} className="f-panel s-line" strokeWidth={1.25} />
      <Box x={452} y={102} w={148} label="read each paper" />
      <text x={526} y={156} textAnchor="middle" className="t-faint">PDF → arXiv → abstract</text>
      <text x={526} y={171} textAnchor="middle" className="t-faint">10 papers at a time</text>

      <line x1={600} y1={120} x2={620} y2={120} className="s-ink" strokeWidth={1.5} markerEnd={end} />
      <Box x={622} y={102} w={132} label="extract claims" />
      <text x={688} y={156} textAnchor="middle" className="t-faint">≤ 12 each, quoted</text>

      <line x1={754} y1={120} x2={790} y2={120} className="s-ink" strokeWidth={1.5} markerEnd={end} />
      <Box x={792} y={102} w={108} label="cluster" />
      <text x={846} y={156} textAnchor="middle" className="t-faint">≤ 25, by meaning</text>

      <line x1={900} y1={120} x2={920} y2={120} className="s-ink" strokeWidth={1.5} markerEnd={end} />
      <rect x={922} y={84} width={120} height={72} className="f-panel s-ink" strokeWidth={1.5} />
      {['lineage', 'disagreement', 'quality'].map((axis, i) => (
        <g key={axis}>
          <rect x={934} y={97 + i * 20} width={7} height={7} className={i === 0 ? 'f-acc' : 'f-ink'} />
          <text x={950} y={104 + i * 20} className="t-ink">{axis}</text>
        </g>
      ))}
      <text x={982} y={174} textAnchor="middle" className="t-faint">per cluster</text>

      <line x1={1042} y1={120} x2={1060} y2={120} className="s-ink" strokeWidth={1.5} markerEnd={end} />
      <Box x={1062} y={102} w={104} label="report" strong />
      <text x={1114} y={156} textAnchor="middle" className="t-faint">a section</text>
      <text x={1114} y={171} textAnchor="middle" className="t-faint">per cluster</text>
    </svg>
  )
}

// -- 06: running your own -----------------------------------------------------

/** What a self-hosted run talks to. Everything inside the dashed line is yours;
 *  the brackets on the right say which configuration takes each outside call
 *  away, so the "nothing leaves your machine" claim can be read off the page. */
export function DeploymentArt(): ReactElement {
  const arrow = `${useSvgId()}-arrow`
  const end = `url(#${arrow})`
  const outside = [
    { label: 'Gemini or Anthropic', role: 'language model' },
    { label: 'Workers AI or Gemini', role: 'embeddings' },
    { label: 'Semantic Scholar', role: 'search' },
    { label: 'publisher PDFs, arXiv', role: 'full text' },
  ]
  const ys = [44, 92, 140, 188]
  return (
    <svg className="lp-svg" viewBox="0 0 1168 234" role="img" aria-label="Inside your machine: the browser, the Nodus API as one process, your Postgres with pgvector, and optionally Ollama. Outside: a language model and an embeddings service, which Ollama replaces, and Semantic Scholar and publisher PDFs or arXiv, which upload runs never call.">
      <defs>
        <Arrowhead id={arrow} />
      </defs>

      <rect x={1} y={24} width={580} height={206} className="f-none s-ink" strokeWidth={1.5} strokeDasharray="6 5" />
      <text x={0} y={14} className="t-faint">your machine and your database</text>

      <Box x={24} y={104} w={140} label="browser" />
      <text x={94} y={158} textAnchor="middle" className="t-faint">the reading surface</text>
      <line x1={164} y1={122} x2={230} y2={122} className="s-ink" strokeWidth={1.5} markerEnd={end} />
      <text x={197} y={114} textAnchor="middle" className="t-faint">socket</text>

      <rect x={232} y={96} width={160} height={52} className="f-panel s-ink" strokeWidth={2} />
      <text x={312} y={119} textAnchor="middle" className="t-node">Nodus API</text>
      <text x={312} y={136} textAnchor="middle" className="t-faint">one process</text>

      <path d="M392 110 H422 V62 H450" className="f-none s-ink" strokeWidth={1.5} markerEnd={end} />
      <Box x={452} y={44} w={112} label="Postgres" />
      <text x={508} y={96} textAnchor="middle" className="t-faint">+ pgvector</text>

      <path d="M392 134 H422 V182 H450" className="f-none s-ink" strokeWidth={1.5} strokeDasharray="5 4" markerEnd={end} />
      <Box x={452} y={164} w={112} label="Ollama" />
      <text x={508} y={218} textAnchor="middle" className="t-faint">optional</text>

      {/* One bus out of the API, crossing the boundary once. */}
      <path d={`M392 122 H620`} className="f-none s-faint" strokeWidth={1.25} />
      <line x1={620} y1={ys[0]} x2={620} y2={ys[3]} className="s-faint" strokeWidth={1.25} />
      {outside.map((service, i) => (
        <g key={service.label}>
          <line x1={620} y1={ys[i]} x2={688} y2={ys[i]} className="s-faint" strokeWidth={1.25} markerEnd={end} />
          <Box x={690} y={ys[i] - 16} w={200} h={32} label={service.label} />
          <text x={904} y={ys[i] + 4} className="t-faint">{service.role}</text>
        </g>
      ))}
      <path d="M1010 30 H1016 V106 H1010" className="f-none s-acc" strokeWidth={1.5} />
      <text x={1026} y={72} className="t-acc">not used with Ollama</text>
      <path d="M1010 126 H1016 V202 H1010" className="f-none s-acc" strokeWidth={1.5} />
      <text x={1026} y={168} className="t-acc">not used by uploads</text>
    </svg>
  )
}
