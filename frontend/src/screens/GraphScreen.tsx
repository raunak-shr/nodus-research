import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'

import {
  GH,
  GRAPH_TABS,
  GW,
  TAB_HINTS,
  buildScene,
  emptyReason,
  panelFor,
  tabCount,
  type GraphTab,
  type NodeRef,
  type NodeRole,
  type SceneEdge,
  type SceneNode,
} from '../lib/graph'
import { useStore } from '../state/store'

/** How each role is painted. Kept as one table so the four views cannot drift
 *  apart on what a paper or a cluster looks like. */
const ROLE_STYLE: Record<NodeRole, React.CSSProperties> = {
  root: { fill: 'var(--n-text)', stroke: 'none' },
  cluster: { fill: 'var(--color-accent)', stroke: 'none' },
  hub: { fill: 'none', stroke: 'var(--color-accent)', strokeWidth: 2 },
  paper: { fill: 'var(--n-bg)', stroke: 'var(--n-text)', strokeWidth: 1.5 },
  paperDim: {
    fill: 'none',
    stroke: 'var(--n-line2)',
    strokeWidth: 1.25,
    strokeDasharray: '3 3',
  },
  claim: { fill: 'var(--n-text)', stroke: 'none' },
  author: { fill: 'var(--n-panel2)', stroke: 'var(--n-line2)', strokeWidth: 1.5 },
}

function edgeStyle(edge: SceneEdge, motion: boolean): React.CSSProperties {
  const flow = motion ? { animation: 'n-flow 1.6s linear infinite' } : {}
  switch (edge.tone) {
    case 'faint':
      return { stroke: 'var(--n-line)', strokeWidth: 1, fill: 'none' }
    case 'accent':
      return { stroke: 'var(--color-accent)', strokeWidth: 2, fill: 'none' }
    case 'thin':
      return {
        stroke: 'var(--color-accent)',
        strokeWidth: 1.25,
        fill: 'none',
        opacity: 0.75,
        strokeDasharray: '5 4',
        ...flow,
      }
    case 'dashed':
      return {
        stroke: 'var(--n-line2)',
        strokeWidth: 1.25,
        fill: 'none',
        strokeDasharray: '4 4',
        ...flow,
      }
    case 'weighted':
      return {
        stroke: 'var(--n-line2)',
        strokeWidth: 1 + (edge.weight ?? 0) * 0.16,
        fill: 'none',
      }
    default:
      return { stroke: 'var(--n-line2)', strokeWidth: 1.25, fill: 'none' }
  }
}

const MIN_ZOOM = 0.5
const MAX_ZOOM = 3

interface View {
  k: number
  x: number
  y: number
}

const HOME: View = { k: 1, x: 0, y: 0 }

/** Four views over one run.
 *
 *  Everything on screen comes from a single `graph.get` — the four tabs are the
 *  same payload seen from different sides, not four requests. Hover, pin and
 *  the viewport live here rather than in the store: they are ways of looking at
 *  the run, not facts about it, and nothing else in the app needs them.
 */
export function GraphScreen(): ReactElement {
  const store = useStore()
  const { graph, graphLoading, graphError } = store

  const [tab, setTab] = useState<GraphTab>('clusters')
  const [hover, setHover] = useState<NodeRef | null>(null)
  const [pin, setPin] = useState<NodeRef | null>(null)
  const [view, setView] = useState<View>(HOME)
  const dragRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  const [motion] = useState(
    () => !(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false),
  )

  const activeQueryId = store.activeQueryId
  // A run that finishes while this screen is open has clusters it did not have
  // a moment ago, so the field is refetched once — but only on that edge, not
  // on every render, or the whole graph would reload behind each hover.
  const justFinished = store.run.complete && store.run.queryId === activeQueryId
  useEffect(() => {
    store.loadGraph(justFinished)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeQueryId, justFinished])

  // A pin on a node the previous tab had is meaningless on this one, and a
  // stale one leaves the panel describing something not on screen.
  useEffect(() => {
    setHover(null)
    setPin(null)
    setView(HOME)
  }, [tab, activeQueryId])

  const scene = useMemo(
    () => (graph ? buildScene(graph, { tab, hover, pin, showLabels: true, motion }) : null),
    [graph, tab, hover, pin, motion],
  )
  const panel = useMemo(() => (graph ? panelFor(graph, pin) : null), [graph, pin])

  const onWheel = useCallback((event: React.WheelEvent) => {
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
    setView((current) => ({
      ...current,
      k: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, current.k * factor)),
    }))
  }, [])

  const onMouseDown = useCallback((event: React.MouseEvent) => {
    setView((current) => {
      dragRef.current = { sx: event.clientX, sy: event.clientY, ox: current.x, oy: current.y }
      return current
    })
    setDragging(true)
  }, [])

  const onMouseMove = useCallback((event: React.MouseEvent) => {
    const drag = dragRef.current
    if (!drag) return
    setView((current) => {
      // Clamped so the field cannot be dragged out of its own frame.
      const limit = 300 / current.k
      const clamp = (value: number): number => Math.max(-limit, Math.min(limit, value))
      return {
        ...current,
        x: clamp(drag.ox + (event.clientX - drag.sx) / current.k),
        y: clamp(drag.oy + (event.clientY - drag.sy) / current.k),
      }
    })
  }, [])

  const endDrag = useCallback(() => {
    dragRef.current = null
    setDragging(false)
  }, [])

  if (!activeQueryId) {
    return (
      <Empty
        kicker="Graph"
        headline="No run is open."
        body="The graph draws one run. Open a run from History, or start a new query — the field appears once its clusters exist."
      />
    )
  }

  if (graphError && !graph) {
    return (
      <Empty kicker="Graph" headline="The graph could not be loaded." body={graphError}>
        {/* The effect that loads it runs on the run changing, so a failure here
            would otherwise leave nothing that could ask again. */}
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => store.loadGraph(true)}
          style={{ marginTop: 22, fontSize: 13, padding: '8px 16px' }}
        >
          Try again
        </button>
      </Empty>
    )
  }

  if (!graph) {
    return (
      <Empty
        kicker="Graph"
        headline={graphLoading ? 'Assembling the field…' : 'Nothing to draw yet.'}
        body={
          graphLoading
            ? 'One request carries all four views, so this is the only wait.'
            : 'This run has produced no clusters or papers to lay out.'
        }
      />
    )
  }

  const blank = emptyReason(graph, tab)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <div style={{ padding: '44px 56px 0' }}>
        <div className="kicker" style={{ marginBottom: 14 }}>
          Graph · run {graph.query_id.slice(0, 6)}
          {graph.uploaded_corpus ? ' · uploaded corpus' : ''}
        </div>
        <div
          style={{
            borderLeft: '2px solid var(--color-accent)',
            padding: '2px 0 2px 16px',
            margin: '0 0 20px',
            maxWidth: 760,
          }}
        >
          <div className="kicker" style={{ marginBottom: 6 }}>
            Question that built this graph
          </div>
          <div
            className="pretty"
            style={{
              fontFamily: 'var(--font-heading)',
              fontSize: 24,
              lineHeight: 1.24,
              letterSpacing: '-.018em',
            }}
          >
            {graph.question}
          </div>
        </div>
        <p className="dim pretty" style={{ maxWidth: 640, margin: '0 0 22px' }}>
          Four views over one run: clusters and the claims inside them, the papers those claims came
          from, who wrote them, and the lineage between them.
        </p>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          borderBottom: '2px solid var(--n-line2)',
          padding: '0 56px',
        }}
      >
        {GRAPH_TABS.map((id) => (
          <button
            key={id}
            type="button"
            className={`graph-tab${tab === id ? ' on' : ''}`}
            onClick={() => setTab(id)}
          >
            <span style={{ whiteSpace: 'nowrap', textTransform: 'capitalize' }}>{id}</span>
            <span className="faint num" style={{ fontSize: 11 }}>
              {tabCount(graph, id)}
            </span>
          </button>
        ))}
      </div>

      <div className="graph-body">
        <div className="graph-canvas">
          <div className="graph-hint">{blank ?? TAB_HINTS[tab]}</div>

          <div className="graph-zoom">
            <button
              type="button"
              onClick={() => setView((c) => ({ ...c, k: Math.max(MIN_ZOOM, c.k / 1.25) }))}
              title="Zoom out"
            >
              −
            </button>
            <button
              type="button"
              onClick={() => setView((c) => ({ ...c, k: Math.min(MAX_ZOOM, c.k * 1.25) }))}
              title="Zoom in"
            >
              +
            </button>
            <button type="button" onClick={() => setView(HOME)} title="Reset view">
              <svg
                viewBox="0 0 24 24"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
              </svg>
            </button>
          </div>

          <div className="graph-scale num">{Math.round(view.k * 100)}% · drag to pan</div>

          {scene && !blank ? (
            <div
              style={{
                position: 'relative',
                width: GW,
                height: GH,
                margin: '38px 0 0 2px',
              }}
            >
              <svg
                viewBox={`0 0 ${GW} ${GH}`}
                width={GW}
                height={GH}
                onWheel={onWheel}
                onMouseDown={onMouseDown}
                onMouseMove={onMouseMove}
                onMouseUp={endDrag}
                onMouseLeave={() => {
                  endDrag()
                  setHover(null)
                }}
                style={{ display: 'block', cursor: dragging ? 'grabbing' : 'grab', userSelect: 'none' }}
              >
                <g
                  transform={`translate(${GW / 2} ${GH / 2}) scale(${view.k}) translate(${-GW / 2} ${-GH / 2}) translate(${view.x} ${view.y})`}
                >
                  {scene.frames.map((frame, index) => (
                    <rect
                      key={`frame-${index}`}
                      x={frame.x}
                      y={frame.y}
                      width={frame.w}
                      height={frame.h}
                      style={{
                        fill: 'none',
                        stroke: 'var(--n-line2)',
                        strokeWidth: 1,
                        strokeDasharray: '3 4',
                      }}
                    />
                  ))}
                  {scene.axis.map((line, index) => (
                    <line
                      key={`axis-${index}`}
                      x1={line.x1}
                      y1={line.y1}
                      x2={line.x2}
                      y2={line.y2}
                      style={{ stroke: 'var(--n-line)', strokeWidth: 1, strokeDasharray: '2 5' }}
                    />
                  ))}
                  {scene.edges.map((edge, index) => (
                    <line
                      key={`edge-${index}`}
                      x1={edge.x1}
                      y1={edge.y1}
                      x2={edge.x2}
                      y2={edge.y2}
                      style={edgeStyle(edge, motion)}
                    />
                  ))}
                  {scene.nodes.map((node) => (
                    <Node
                      key={node.key}
                      node={node}
                      motion={motion}
                      onEnter={() => setHover({ kind: node.kind, id: node.id })}
                      onClick={() => setPin({ kind: node.kind, id: node.id })}
                    />
                  ))}
                </g>
              </svg>

              {/* Labels are HTML over the SVG, transformed identically. A hole
                  inside an SVG <text> cannot be laid out or ellipsised, and
                  text-shadow is what keeps a label legible over an edge. */}
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  width: GW,
                  height: GH,
                  transformOrigin: `${GW / 2}px ${GH / 2}px`,
                  transform: `scale(${view.k}) translate(${view.x}px, ${view.y}px)`,
                  pointerEvents: 'none',
                }}
              >
                {scene.captions.map((caption, index) => (
                  <div
                    key={`caption-${index}`}
                    className="graph-label faint"
                    style={{
                      left: caption.x,
                      top: caption.y,
                      width: caption.w,
                      height: caption.h,
                      fontSize: caption.size,
                      justifyContent: caption.align,
                      letterSpacing: caption.uppercase ? '.06em' : undefined,
                      textTransform: caption.uppercase ? 'uppercase' : undefined,
                      textShadow: 'none',
                    }}
                  >
                    {caption.text}
                  </div>
                ))}
                {scene.nodes
                  .filter((node) => node.label)
                  .map((node) => (
                    <div
                      key={`label-${node.key}`}
                      className="graph-label"
                      style={{
                        left: node.labelX,
                        top: node.labelY,
                        width: node.labelW,
                        height: node.labelH,
                        fontSize: node.labelSize,
                        justifyContent: node.labelAlign,
                        color: node.active ? 'var(--n-text)' : 'var(--n-dim)',
                      }}
                    >
                      {node.label}
                    </div>
                  ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="graph-panel n-scroll">
          {panel ? (
            <div style={{ animation: 'n-in .22s ease both' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  gap: 10,
                  marginBottom: 11,
                }}
              >
                <span
                  className="kicker"
                  style={{ color: 'var(--color-accent-700)', whiteSpace: 'nowrap' }}
                >
                  {panel.kicker}
                </span>
                <button type="button" className="linkish" onClick={() => setPin(null)}>
                  unpin
                </button>
              </div>
              <div
                className="pretty"
                style={{ fontSize: 16, lineHeight: 1.32, letterSpacing: '-.01em', marginBottom: 16 }}
              >
                {panel.title}
              </div>
              {panel.meta.map((row) => (
                <div
                  key={row.key}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 14,
                    fontSize: 12,
                    padding: '8px 0',
                    borderTop: '1px solid var(--n-line)',
                  }}
                >
                  <span className="faint" style={{ flex: '0 0 auto', whiteSpace: 'nowrap' }}>
                    {row.key}
                  </span>
                  <span
                    style={{
                      textAlign: 'right',
                      minWidth: 0,
                      ...(row.value.length <= 26 ? { whiteSpace: 'nowrap' } : { lineHeight: 1.4 }),
                    }}
                  >
                    {row.value}
                  </span>
                </div>
              ))}
              <div className="kicker" style={{ margin: '22px 0 2px' }}>
                {panel.listLabel}
              </div>
              {panel.items.map((item, index) => (
                <div
                  key={`${item.text}-${index}`}
                  style={{ padding: '11px 0', borderTop: '2px solid var(--n-line2)' }}
                >
                  <div className="pretty" style={{ fontSize: 13, lineHeight: 1.45 }}>
                    {item.text}
                  </div>
                  {item.sub ? (
                    <div
                      className="faint"
                      style={{ fontSize: 11, marginTop: 5, lineHeight: 1.4 }}
                    >
                      {item.sub}
                    </div>
                  ) : null}
                </div>
              ))}
              {panel.go ? (
                <button
                  type="button"
                  className="graph-go"
                  onClick={() => store.openCluster(panel.go!.clusterId)}
                >
                  {panel.go.label}
                </button>
              ) : null}
            </div>
          ) : (
            <>
              <div className="kicker" style={{ marginBottom: 12 }}>
                Nothing pinned
              </div>
              <p className="dim" style={{ fontSize: 13.5, lineHeight: 1.55, margin: 0 }}>
                Click a node to pin it here. The panel stays put while you keep moving around the
                graph, so you can compare one node against the rest of the field.
              </p>
            </>
          )}

          {tab === 'lineage' ? (
            <p className="faint" style={{ fontSize: 11.5, lineHeight: 1.5, marginTop: 26 }}>
              Lineage is not a citation graph. Nodus has no citation edges — these links are the
              lineage each cluster records, built from publication order and the stance assigned to
              each claim ({graph.lineage_basis}).
            </p>
          ) : null}

          {graph.claims_unclustered > 0 ? (
            <p className="faint" style={{ fontSize: 11.5, lineHeight: 1.5, marginTop: 18 }}>
              {graph.claims_unclustered} extracted{' '}
              {graph.claims_unclustered === 1 ? 'claim reached' : 'claims reached'} no cluster, so{' '}
              {graph.claims_unclustered === 1 ? 'it is' : 'they are'} not on this field.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function Node({
  node,
  motion,
  onEnter,
  onClick,
}: {
  node: SceneNode
  motion: boolean
  onEnter: () => void
  onClick: () => void
}): ReactElement {
  const half = node.size / 2
  const drift =
    motion && node.driftIndex >= 0
      ? {
          transformBox: 'fill-box' as const,
          transformOrigin: 'center',
          animation: `n-drift${node.driftIndex} ${node.driftSeconds.toFixed(1)}s ease-in-out ${node.driftDelay.toFixed(1)}s infinite`,
        }
      : {}

  return (
    <g onMouseEnter={onEnter} onClick={onClick} style={{ cursor: 'pointer' }}>
      {node.active ? (
        <rect
          x={node.x - half - 7}
          y={node.y - half - 7}
          width={node.size + 14}
          height={node.size + 14}
          style={{
            fill: 'none',
            stroke: 'var(--color-accent)',
            strokeWidth: 1.5,
            transformBox: 'fill-box',
            transformOrigin: 'center',
            ...(motion ? { animation: 'n-halo 1.6s ease-in-out infinite' } : {}),
          }}
        />
      ) : null}
      <rect
        x={node.x - half}
        y={node.y - half}
        width={node.size}
        height={node.size}
        style={{
          ...ROLE_STYLE[node.role],
          ...(node.active ? { stroke: 'var(--color-accent)', strokeWidth: 2.5 } : {}),
          ...drift,
        }}
      />
    </g>
  )
}

function Empty({
  kicker,
  headline,
  body,
  children,
}: {
  kicker: string
  headline: string
  body: string
  children?: React.ReactNode
}): ReactElement {
  return (
    <div className="screen">
      <div className="kicker" style={{ marginBottom: 16 }}>
        {kicker}
      </div>
      <h1 style={{ fontSize: 30, letterSpacing: '-.02em', margin: '0 0 12px', maxWidth: 640 }}>
        {headline}
      </h1>
      <p className="dim pretty" style={{ maxWidth: 560, margin: 0 }}>
        {body}
      </p>
      {children}
    </div>
  )
}
