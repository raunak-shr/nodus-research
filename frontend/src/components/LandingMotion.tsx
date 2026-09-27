/** The three axis sections' animations: each builds its axis's answer for the
 *  worked example one step at a time, beside the finished figure.
 *
 *  They play once, when they first come half into view, and then wait for
 *  Replay — three sections looping at once would be three things competing for
 *  the eye, and a reader who wants the sequence again can ask for it. Under
 *  reduced motion they open on their last step and offer no replay: the end
 *  state carries everything the sequence does.
 *
 *  Every position and count comes from the chain and score passed in, the same
 *  data the figures draw, so an animation cannot show a different cluster from
 *  the one beside it. Movement is CSS transitions on transforms and colours,
 *  keyed off the current step; nothing is animated by script except the
 *  running total, which has to count.
 */

import { useCallback, useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'

import type { ChainPoint } from './LandingArt'

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}

interface Sequence {
  ref: React.RefObject<HTMLDivElement>
  step: number
  playing: boolean
  reduced: boolean
  replay: () => void
}

/** Steps 0…last, one every `ms`, from the first time the player is half in view. */
function useSequence(last: number, ms: number): Sequence {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useRef(prefersReducedMotion()).current
  const [step, setStep] = useState(reduced ? last : 0)
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    if (reduced) return
    const node = ref.current
    if (!node || typeof IntersectionObserver === 'undefined') {
      setStep(last)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setPlaying(true)
          observer.disconnect()
        }
      },
      { threshold: 0.5 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [last, reduced])

  useEffect(() => {
    if (!playing) return
    if (step >= last) {
      setPlaying(false)
      return
    }
    const timer = window.setTimeout(() => setStep((current) => current + 1), ms)
    return () => window.clearTimeout(timer)
  }, [playing, step, last, ms])

  const replay = useCallback(() => {
    setStep(0)
    setPlaying(true)
  }, [])

  return { ref, step, playing, reduced, replay }
}

/** A number that eases to its target instead of jumping — the running total. */
function useTween(target: number, ms: number, instant: boolean): number {
  const [value, setValue] = useState(target)
  const current = useRef(target)
  useEffect(() => {
    if (instant) {
      current.current = target
      setValue(target)
      return
    }
    const from = current.current
    const start = performance.now()
    let frame = 0
    const tick = (now: number): void => {
      const t = Math.min(1, (now - start) / ms)
      const next = from + (target - from) * (1 - (1 - t) ** 3)
      current.current = next
      setValue(next)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, ms, instant])
  return value
}

function Player({
  seq,
  captions,
  wide = false,
  children,
}: {
  seq: Sequence
  captions: string[]
  /** Set inside a figure: it takes the figure's width, and the figure head
   *  already draws the rule the text-column player opens with. */
  wide?: boolean
  children: ReactNode
}): ReactElement {
  const at = Math.min(seq.step, captions.length - 1)
  return (
    <div ref={seq.ref} className={wide ? 'lp-anim lp-anim-wide' : 'lp-anim'}>
      <div className="lp-anim-head">
        <span className="lp-anim-step">
          {at + 1}/{captions.length}
        </span>
        <span className="lp-anim-cap">{captions[at]}</span>
        {seq.reduced ? null : (
          <button type="button" className="lp-anim-replay" onClick={seq.replay} disabled={seq.playing}>
            Replay
          </button>
        )}
      </div>
      {children}
    </div>
  )
}

/** The class a node takes once its role is known; `pending` before. */
function nodeClass(role: 'pending' | ChainPoint['rel'] | ChainPoint['stance']): string {
  switch (role) {
    case 'origin':
      return 'f-acc s-acc'
    case 'supports':
      return 'f-ink s-ink'
    case 'contradicts':
      return 'f-panel s-ink'
    case 'extends':
      return 'f-panel s-faint'
    case 'neutral':
      return 'f-neu s-neu'
    default:
      return 'f-panel s-line'
  }
}

const move = (x: number, y: number, delay = 0): React.CSSProperties => ({
  transform: `translate(${x}px, ${y}px)`,
  transitionDelay: `${delay}ms`,
})

// -- lineage --------------------------------------------------------------------

/** Where each paper sits before it is ordered, by chain index: two loose rows in
 *  retrieval order, which ranks by citations and relevance, not by year. Slots
 *  are 110 apart so each full citation fits over its square. */
const JUMBLE: [number, number][] = [
  [264, 62],
  [284, 96],
  [154, 62],
  [64, 96],
  [174, 96],
  [44, 62],
]

/** How the chain gets its labels. The figure beside it already draws the
 *  finished chain; this draws the one thing the chain invites a reader to get
 *  wrong — each later paper is labelled by a line up to the cluster's
 *  assertion, and no line runs from one paper to the paper before it. */
export function LineageBuild({ chain, assertion }: { chain: ChainPoint[]; assertion: string }): ReactElement {
  const captions = [
    'Six papers, in the order they were retrieved.',
    'Put in order of publication.',
    'The earliest is the origin.',
    "Each later paper's claim is read against the cluster's assertion —",
    '— so no label compares a paper with the one before it.',
  ]
  const seq = useSequence(captions.length - 1, 1200)
  const { step } = seq
  const lo = chain[0].year - 1
  const hi = chain[chain.length - 1].year + 1
  const x = (year: number): number => 20 + ((year - lo) / (hi - lo)) * 320
  const lineY = 112
  const barBottom = 36
  const ticks: number[] = []
  for (let year = Math.ceil(lo / 5) * 5; year <= hi; year += 5) ticks.push(year)
  const linkClass: Record<ChainPoint['rel'], string> = {
    origin: 's-acc',
    supports: 's-ink',
    contradicts: 's-con',
    extends: 's-faint',
  }

  return (
    <Player seq={seq} captions={captions}>
      <svg className="lp-svg" viewBox="0 0 360 200" role="img" aria-label={`The ${chain.length} papers are put in publication order and the earliest, ${chain[0].short}, becomes the origin; each later paper is then labelled by a line to the cluster's assertion, not to the paper before it.`}>
        <g className="lp-fade" style={{ opacity: step >= 3 ? 1 : 0 }}>
          <rect x={16} y={8} width={328} height={barBottom - 8} className="f-panel s-ink" strokeWidth={2} />
          <text x={180} y={26} textAnchor="middle" className="t-node-sm">
            {assertion}
          </text>
        </g>

        {chain.slice(1).map((point, i) => (
          <line
            key={point.short}
            x1={x(point.year)}
            y1={lineY - 8}
            x2={x(point.year)}
            y2={barBottom}
            className={`lp-fade ${linkClass[point.rel]}`}
            strokeWidth={1.5}
            strokeDasharray={point.rel === 'contradicts' ? '4 3' : undefined}
            style={{ opacity: step >= 3 ? 1 : 0, transitionDelay: step >= 3 ? `${i * 180}ms` : '0ms' }}
          />
        ))}

        <g className="lp-fade" style={{ opacity: step >= 1 ? 1 : 0 }}>
          <line x1={16} y1={166} x2={344} y2={166} className="s-line" strokeWidth={1.25} />
          {ticks.map((year) => (
            <g key={year}>
              <line x1={x(year)} y1={166} x2={x(year)} y2={170} className="s-line" strokeWidth={1.25} />
              <text x={x(year)} y={184} textAnchor="middle" className="t-faint">
                {year}
              </text>
            </g>
          ))}
        </g>

        {chain.map((point, i) => {
          const ordered = step >= 1
          const role =
            step >= 3 ? point.rel : step >= 2 && point.rel === 'origin' ? 'origin' : 'pending'
          const [jx, jy] = JUMBLE[i % JUMBLE.length]
          // Names go under the line once it is in order: the links need the
          // space above, running up to the assertion.
          const labelDown = i % 2 === 0 ? 24 : 38
          return (
            <g key={point.short} className="lp-move" style={ordered ? move(x(point.year), lineY, i * 70) : move(jx, jy)}>
              {/* Centred in both states, so the label only ever moves — an anchor
                  switch would make it jump as the paper sets off. */}
              <g className="lp-move" style={ordered ? move(0, labelDown) : move(0, -14)}>
                <text x={0} y={0} textAnchor="middle" className={`lp-tint ${role === 'origin' ? 't-acc' : 't-dim'}`}>
                  {ordered ? point.short.split(' ')[0] : point.short}
                </text>
              </g>
              <rect
                x={-6}
                y={-6}
                width={12}
                height={12}
                strokeWidth={2}
                className={`lp-tint ${nodeClass(role)}`}
                style={{ transitionDelay: step >= 3 ? `${Math.max(0, i - 1) * 180 + 120}ms` : '0ms' }}
              />
            </g>
          )
        })}
      </svg>
    </Player>
  )
}

// -- disagreement ---------------------------------------------------------------

type Bin = 'supports' | 'neutral' | 'contradicts'

/** Left edge of each bin's column — it sits in the figure, so it is laid out at
 *  the figure's width rather than the text column's. */
const BIN_X: Record<Bin, number> = { supports: 24, neutral: 212, contradicts: 392 }
const BIN_WORD: Record<Bin, string> = {
  supports: 'supports it',
  neutral: 'takes no side',
  contradicts: 'contradicts it',
}

/** The claims read one at a time against the assertion and sorted by the stance
 *  each takes, with the counts kept as they go — then the drivers named. It
 *  stands in the figure where a static stance diagram was: its last step is
 *  that diagram, so showing both would say the same thing twice. */
export function StanceSort({
  chain,
  assertion,
  drivers,
}: {
  chain: ChainPoint[]
  assertion: [string, string]
  drivers: string[]
}): ReactElement {
  const captions = [
    'Six claims, and the one assertion they are read against.',
    ...chain.map((claim) => `${claim.short} ${BIN_WORD[claim.stance]}.`),
    `Then what drives the split is named: ${drivers.join(', ')}.`,
  ]
  const seq = useSequence(captions.length - 1, 950)
  const { step } = seq
  const placed = Math.min(step, chain.length)
  // Each claim's row inside its bin: its position among the claims that share it.
  const row = chain.map((claim, i) => chain.slice(0, i).filter((c) => c.stance === claim.stance).length)
  const counts = (bin: Bin): number => chain.slice(0, placed).filter((c) => c.stance === bin).length
  const tagWidth = (driver: string): number => driver.length * 6.6 + 18

  return (
    <Player seq={seq} captions={captions} wide>
      <svg className="lp-svg" viewBox="0 0 540 214" role="img" aria-label={`Each of the ${chain.length} claims is read against the assertion and sorted into supports, neutral or contradicts; then the drivers are named: ${drivers.join(', ')}.`}>
        <rect x={160} y={6} width={220} height={42} className="f-panel s-ink" strokeWidth={2} />
        <text x={270} y={24} textAnchor="middle" className="t-node-sm">{assertion[0]}</text>
        <text x={270} y={40} textAnchor="middle" className="t-node-sm">{assertion[1]}</text>

        {(Object.keys(BIN_X) as Bin[]).map((bin) => (
          <g key={bin}>
            <path
              d={`M270 48 V58 H${BIN_X[bin] + 6} V70`}
              className={`f-none ${bin === 'contradicts' ? 's-con' : bin === 'neutral' ? 's-faint' : 's-ink'}`}
              strokeWidth={1.25}
              strokeDasharray={bin === 'contradicts' ? '4 3' : undefined}
            />
            <text x={BIN_X[bin]} y={84} className="t-faint">
              {bin} <tspan className="t-ink t-strong">{counts(bin)}</tspan>
            </text>
          </g>
        ))}

        {chain.map((claim, i) => {
          const done = i < placed
          const reading = i === placed - 1 && seq.playing
          const queue = move(170 + i * 40, 186)
          const home = move(BIN_X[claim.stance] + 6, 104 + row[i] * 22)
          return (
            <g key={claim.short} className="lp-move" style={done ? home : queue}>
              <rect
                x={-6}
                y={-6}
                width={12}
                height={12}
                strokeWidth={2}
                className={`lp-tint ${done ? nodeClass(claim.stance) : 'f-panel s-line'} ${reading ? 'lp-pulse' : ''}`}
              />
              <text x={12} y={4} className="t-dim lp-fade" style={{ opacity: done ? 1 : 0 }}>
                {claim.short}
              </text>
            </g>
          )
        })}

        {/* The drivers take the queue's place once the queue has emptied. */}
        <g className="lp-fade" style={{ opacity: step > chain.length ? 1 : 0 }}>
          <text x={24} y={190} className="t-faint">drivers</text>
          {drivers.map((driver, i) => {
            const left = 88 + drivers.slice(0, i).reduce((sum, d) => sum + tagWidth(d) + 8, 0)
            return (
              <g key={driver}>
                <rect x={left} y={176} width={tagWidth(driver)} height={20} className="f-none s-con" strokeWidth={1.25} />
                <text x={left + 9} y={190} className="t-con">{driver}</text>
              </g>
            )
          })}
        </g>
      </svg>
    </Player>
  )
}

// -- quality --------------------------------------------------------------------

const TIER_BARS: { tier: 'medium' | 'high'; at: number }[] = [
  { tier: 'medium', at: 0.45 },
  { tier: 'high', at: 0.7 },
]

export function ScoreFill({
  parts,
  penalty,
  score,
}: {
  parts: { name: string; value: string; weight: string; contrib: number }[]
  penalty: number
  score: number
}): ReactElement {
  const fmt = (v: number): string => v.toFixed(3)
  const captions = [
    'Every component starts at zero.',
    ...parts.map((p) => `${p.name}: ${p.value} × ${p.weight} = ${fmt(p.contrib)}`),
    `Contradiction takes ${fmt(penalty)} back off the total.`,
    `${fmt(score)} clears ${TIER_BARS[1].at.toFixed(2)}: the tier is high.`,
  ]
  const seq = useSequence(captions.length - 1, 1000)
  const { step } = seq
  const sums = parts.map((_, i) => parts.slice(0, i + 1).reduce((sum, p) => sum + p.contrib, 0))
  const total = step === 0 ? 0 : step <= parts.length ? sums[step - 1] : score
  const shown = useTween(total, 650, seq.reduced)
  const tier = shown >= TIER_BARS[1].at ? 'high' : shown >= TIER_BARS[0].at ? 'medium' : 'low'

  const bottom = 238
  const scale = 208
  const y = (v: number): number => bottom - v * scale
  const starts = [0, ...sums.slice(0, -1)]

  return (
    <Player seq={seq} captions={captions}>
      <svg className="lp-svg" viewBox="0 0 360 258" role="img" aria-label={`The four weighted components fill the score to ${fmt(sums[sums.length - 1])}, the conflict penalty takes it to ${fmt(score)}, and the tier is high.`}>
        <rect x={30} y={y(1)} width={40} height={scale} className="f-none s-line" strokeWidth={1.25} />
        {parts.map((part, i) => (
          <rect
            key={part.name}
            x={31}
            y={y(starts[i] + part.contrib) + 1}
            width={38}
            height={part.contrib * scale - 1}
            className={`lp-grow ${i % 2 === 0 ? 'f-ink' : 'f-dim'}`}
            style={{ transform: step > i ? 'scaleY(1)' : 'scaleY(0)' }}
          />
        ))}
        {/* The penalty, drawn over the top of the fill it removes. */}
        <rect
          x={31}
          y={y(sums[sums.length - 1]) + 1}
          width={38}
          height={penalty * scale}
          className="f-con lp-fade"
          style={{ opacity: step > parts.length ? 0.85 : 0 }}
        />

        {TIER_BARS.map((bar) => (
          <g key={bar.tier}>
            <line x1={24} y1={y(bar.at)} x2={112} y2={y(bar.at)} className="s-faint" strokeWidth={1.25} strokeDasharray="3 3" />
            <text x={116} y={y(bar.at) + 4} className={`lp-tint ${tier === bar.tier ? 't-acc t-strong' : 't-faint'}`}>
              {bar.tier} {bar.at.toFixed(2).replace(/^0/, '')}
            </text>
          </g>
        ))}
        <line
          x1={20}
          y1={0}
          x2={80}
          y2={0}
          className="s-acc lp-move"
          strokeWidth={2.5}
          style={{ transform: `translate(0px, ${y(total)}px)` }}
        />

        <text x={196} y={128} className="t-score">{fmt(shown)}</text>
        <text x={198} y={150} className="t-faint">
          {step > parts.length ? `after the ${fmt(penalty)} penalty` : 'running total'}
        </text>
        <g className="lp-tint">
          <rect x={198} y={164} width={tier === 'medium' ? 76 : 52} height={24} className={`lp-tint ${tier === 'high' ? 'f-acc s-acc' : 'f-none s-ink'}`} strokeWidth={1.5} />
          <text x={210} y={180} className={`lp-tint t-strong ${tier === 'high' ? 't-on-acc' : 't-ink'}`}>
            {tier}
          </text>
        </g>
        <text x={34} y={254} className="t-faint">0</text>
        <text x={34} y={y(1) - 6} className="t-faint">1</text>
      </svg>
    </Player>
  )
}
