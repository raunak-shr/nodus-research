/** Laying one run out as a field of nodes.
 *
 *  Four views over the same `graph.get` payload — clusters and the claims
 *  inside them, the papers those claims came from, who wrote them, and the
 *  lineage between them. Geometry only: nothing here fetches, and nothing here
 *  decides what a node *means*. That keeps the screen a renderer and keeps this
 *  testable without a socket.
 *
 *  Two things are worth knowing before reading the layouts.
 *
 *  **Positions are deterministic.** Every scatter is seeded from a hash of the
 *  node's identity, never from `Math.random`, so a graph does not rearrange
 *  itself when the panel re-renders — which it does on every hover.
 *
 *  **Labels are placed after the geometry, in one monotone sweep.** Node
 *  squares and axis captions are laid down as obstacles first, then each label
 *  in reading order is pushed one direction until it clears everything already
 *  placed. Monotone because it always converges: nudging labels and geometry
 *  against each other oscillates.
 */

import type { GraphPaperNode, GraphRead } from './types'

export type GraphTab = 'clusters' | 'papers' | 'authors' | 'lineage'

export const GRAPH_TABS: GraphTab[] = ['clusters', 'papers', 'authors', 'lineage']

/** The drawing surface, in its own coordinates. Zoom and pan are a transform
 *  applied over it, so nothing below has to know about either. */
export const GW = 900
export const GH = 620

export type NodeKind = 'root' | 'cluster' | 'hub' | 'claim' | 'paper' | 'author'

/** How a node is drawn. Separate from its kind because the same kind is drawn
 *  differently depending on what it contributed — a paper that yielded no
 *  claims is the same kind of thing, dashed. */
export type NodeRole = 'root' | 'cluster' | 'hub' | 'paper' | 'paperDim' | 'claim' | 'author'

export interface NodeRef {
  kind: NodeKind
  id: string
}

export interface SceneNode extends NodeRef {
  key: string
  x: number
  y: number
  size: number
  role: NodeRole
  active: boolean
  /** Deterministic 0–3, picking one of four drift keyframes so a field of nodes
   *  does not breathe in unison. */
  driftIndex: number
  driftSeconds: number
  driftDelay: number
  label: string
  labelX: number
  labelY: number
  labelW: number
  labelH: number
  labelSize: number
  labelAlign: 'flex-start' | 'flex-end' | 'center'
}

export type EdgeTone = 'base' | 'faint' | 'accent' | 'thin' | 'dashed' | 'weighted'

export interface SceneEdge {
  x1: number
  y1: number
  x2: number
  y2: number
  tone: EdgeTone
  /** Only for `weighted`: how many papers the link stands for. */
  weight?: number
}

export interface SceneAxisLine {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface SceneCaption {
  text: string
  x: number
  y: number
  w: number
  h: number
  size: number
  align: 'flex-start' | 'flex-end' | 'center'
  uppercase: boolean
}

export interface SceneFrame {
  x: number
  y: number
  w: number
  h: number
}

export interface Scene {
  nodes: SceneNode[]
  edges: SceneEdge[]
  axis: SceneAxisLine[]
  captions: SceneCaption[]
  frames: SceneFrame[]
}

export interface AuthorNode {
  index: number
  name: string
  paperIds: string[]
}

export interface AuthorGraph {
  authors: AuthorNode[]
  /** Co-authorship, deduplicated: one edge per pair however many papers they
   *  share. The count rides along so the panel can say how many. */
  edges: { a: number; b: number; papers: string[] }[]
}

/** A stable 32-bit hash. The only source of scatter in this module — see the
 *  note about determinism at the top. */
export function ghash(value: string): number {
  let h = 7
  for (let i = 0; i < value.length; i += 1) h = (h * 31 + value.charCodeAt(i)) >>> 0
  return h
}

export function cut(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

function surname(name: string): string {
  const parts = name.trim().split(/\s+/)
  return parts.length ? parts[parts.length - 1] : name
}

/** How a paper is labelled everywhere on the field: first author and year. */
export function paperLabel(paper: GraphPaperNode): string {
  const first = paper.authors[0]
  const who = first ? surname(first) : cut(paper.title, 18)
  return paper.year ? `${who} ${paper.year}` : who
}

// -- author graph -----------------------------------------------------------

/** Co-authorship across the run's papers.
 *
 *  Derived here rather than on the server because it is a pure function of the
 *  author lists that already arrive with the papers — a second payload for it
 *  would be a second thing that can disagree with the first.
 */
export function buildAuthorGraph(papers: GraphPaperNode[]): AuthorGraph {
  const index = new Map<string, number>()
  const authors: AuthorNode[] = []
  const pairs = new Map<string, { a: number; b: number; papers: string[] }>()

  for (const paper of papers) {
    const ids: number[] = []
    for (const name of paper.authors) {
      let at = index.get(name)
      if (at === undefined) {
        at = authors.length
        index.set(name, at)
        authors.push({ index: at, name, paperIds: [] })
      }
      // A paper listing the same person twice must not make them their own
      // co-author, and must not count the paper twice.
      if (!ids.includes(at)) {
        ids.push(at)
        authors[at].paperIds.push(paper.id)
      }
    }
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        const a = Math.min(ids[i], ids[j])
        const b = Math.max(ids[i], ids[j])
        const key = `${a}-${b}`
        const existing = pairs.get(key)
        if (existing) existing.papers.push(paper.id)
        else pairs.set(key, { a, b, papers: [paper.id] })
      }
    }
  }

  return { authors, edges: [...pairs.values()] }
}

// -- layout helpers ---------------------------------------------------------

interface Box {
  x: number
  y: number
  w: number
  h: number
}

type LabelSide = 'above' | 'below' | 'left' | 'right'

interface Pending extends SceneNode {
  side: LabelSide
}

function labelBox(
  cx: number,
  cy: number,
  half: number,
  side: LabelSide,
  size: number,
  text: string,
): { labelX: number; labelY: number; labelW: number; labelH: number; labelAlign: SceneNode['labelAlign'] } {
  const h = 15
  const w = Math.min(210, text.length * size * 0.58 + 10)
  return {
    labelX: side === 'right' ? cx + half + 6 : side === 'left' ? cx - half - 6 - w : cx - w / 2,
    labelY: side === 'below' ? cy + half + 4 : side === 'above' ? cy - half - 4 - h : cy - h / 2,
    labelW: w,
    labelH: h,
    labelAlign: side === 'right' ? 'flex-start' : side === 'left' ? 'flex-end' : 'center',
  }
}

/** Push labels off each other and off the geometry, once, in reading order. */
function placeLabels(nodes: SceneNode[], captions: SceneCaption[]): void {
  const MARGIN = 6
  const clash = (a: Box, b: Box): boolean =>
    Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 1 &&
    Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) + MARGIN > 1

  const withLabel = nodes.filter((node) => node.label)

  // Inside the canvas first: a right-anchored box that would run past the edge
  // flips to the other side of its node rather than being clipped.
  for (const node of withLabel) {
    if (node.labelX + node.labelW > GW - 8) {
      const flipped = node.labelX - node.labelW - 26
      if (node.labelAlign === 'flex-start' && flipped >= 8) {
        node.labelX = flipped
        node.labelAlign = 'flex-end'
      } else {
        node.labelX = GW - 8 - node.labelW
      }
    }
    if (node.labelX < 8) {
      const flipped = node.labelX + node.labelW + 26
      if (node.labelAlign === 'flex-end' && flipped + node.labelW <= GW - 8) {
        node.labelX = flipped
        node.labelAlign = 'flex-start'
      } else {
        node.labelX = 8
      }
    }
  }

  const placed: Box[] = [
    ...captions.map((caption) => ({ x: caption.x, y: caption.y, w: caption.w, h: caption.h })),
    ...nodes.map((node) => ({
      x: node.x - node.size / 2,
      y: node.y - node.size / 2,
      w: node.size,
      h: node.size,
    })),
  ]

  const ordered = [...withLabel].sort((a, b) => a.labelY - b.labelY || a.labelX - b.labelX)
  for (const node of ordered) {
    const home = node.labelY
    for (const direction of [1, -1]) {
      node.labelY = home
      let ok = true
      for (let step = 0; step < 40; step += 1) {
        const box = { x: node.labelX, y: node.labelY, w: node.labelW, h: node.labelH }
        const hit = placed.find((other) => clash(box, other))
        if (!hit) break
        node.labelY = direction > 0 ? hit.y + hit.h + MARGIN : hit.y - node.labelH - MARGIN
        if (node.labelY < 4 || node.labelY + node.labelH > GH - 4) {
          ok = false
          break
        }
      }
      const box = { x: node.labelX, y: node.labelY, w: node.labelW, h: node.labelH }
      if (ok && !placed.some((other) => clash(box, other))) break
    }
    node.labelY = Math.max(4, Math.min(GH - 20, node.labelY))
    placed.push({ x: node.labelX, y: node.labelY, w: node.labelW, h: node.labelH })
  }
}

export interface SceneOptions {
  tab: GraphTab
  hover: NodeRef | null
  pin: NodeRef | null
  showLabels: boolean
  motion: boolean
}

/** The ring a run's clusters sit on.
 *
 *  Scaled by count rather than fixed: the prototype drew six, and a real run
 *  can carry up to `max_clusters_per_query`. A fixed radius packs twenty-five
 *  squares into the space six were spaced for and the field becomes a smear.
 */
function ringRadius(count: number, base: number): number {
  if (count <= 6) return base
  return Math.min(base * 1.55, base * (1 + (count - 6) * 0.055))
}

export function buildScene(graph: GraphRead, options: SceneOptions): Scene {
  const { tab, hover, pin, showLabels, motion } = options
  const nodes: SceneNode[] = []
  const edges: SceneEdge[] = []
  const axis: SceneAxisLine[] = []
  const captions: SceneCaption[] = []
  const frames: SceneFrame[] = []
  const pendingSides: Pending[] = []

  const isActive = (kind: NodeKind, id: string): boolean =>
    (pin !== null && pin.kind === kind && pin.id === id) ||
    (hover !== null && hover.kind === kind && hover.id === id)

  const add = (
    kind: NodeKind,
    id: string,
    rawX: number,
    rawY: number,
    size: number,
    role: NodeRole,
    label: string,
    side: LabelSide,
    still = false,
  ): void => {
    // The last word on where a node may sit. Each layout keeps its own nodes in
    // frame, but a ring scaled for twenty-five clusters can still push a paper
    // orbiting it past the top edge — and a node nobody can see is worse than
    // one nudged ten pixels back inside.
    const margin = size / 2 + 6
    const cx = Math.max(margin, Math.min(GW - margin, rawX))
    const cy = Math.max(margin, Math.min(GH - margin, rawY))
    const active = isActive(kind, id)
    const h = ghash(`${kind}:${id}`)
    const text = showLabels || active ? label : ''
    const fontSize = size < 17 ? 9.5 : 11
    const node: Pending = {
      kind,
      id,
      key: `${kind}:${id}`,
      x: cx,
      y: cy,
      size,
      role,
      active,
      driftIndex: motion && !still ? h % 4 : -1,
      driftSeconds: 4 + (h % 35) / 10,
      driftDelay: -((h % 71) / 10),
      label: text,
      labelSize: fontSize,
      side,
      ...labelBox(cx, cy, size / 2, side, fontSize, text),
    }
    nodes.push(node)
    pendingSides.push(node)
  }

  if (tab === 'clusters') buildClusters(graph, { hover, add, edges })
  if (tab === 'papers') buildPapers(graph, { add, edges, frames, captions })
  if (tab === 'authors') buildAuthors(graph, { isActive, add, edges })
  if (tab === 'lineage') buildLineage(graph, { isActive, add, edges, axis, captions })

  placeLabels(nodes, captions)
  return { nodes, edges, axis, captions, frames }
}

// -- the four layouts -------------------------------------------------------

interface Sink {
  add: (
    kind: NodeKind,
    id: string,
    cx: number,
    cy: number,
    size: number,
    role: NodeRole,
    label: string,
    side: LabelSide,
    still?: boolean,
  ) => void
  edges: SceneEdge[]
}

/** Clusters on a ring around the run, expanding into their claims on hover.
 *
 *  A cluster's square is sized by how many papers stand behind it, and its
 *  spoke is weighted the same way, so the shape of the field is the shape of
 *  the evidence. A cluster with two or more contradicting claims is drawn
 *  dashed — disagreement is one of the three things Nodus exists to show, and
 *  it should be visible before anything is clicked.
 */
function buildClusters(
  graph: GraphRead,
  { hover, add, edges }: Sink & { hover: NodeRef | null },
): void {
  const clusters = graph.clusters
  if (!clusters.length) return

  const cx0 = 430
  const cy0 = 306
  const rx = ringRadius(clusters.length, 180)
  const ry = ringRadius(clusters.length, 150)

  clusters.forEach((cluster, index) => {
    const angle = -Math.PI / 2 + index * ((Math.PI * 2) / clusters.length)
    const x = cx0 + Math.cos(angle) * rx
    const y = cy0 + Math.sin(angle) * ry
    const conflicted = cluster.contradiction_count >= 2

    edges.push({
      x1: cx0,
      y1: cy0,
      x2: x,
      y2: y,
      tone: conflicted ? 'dashed' : 'weighted',
      weight: cluster.paper_count,
    })

    if (hover && hover.kind === 'cluster' && hover.id === cluster.id) {
      // Claims stack as a column beside their cluster at one fixed pitch, so
      // member labels cannot crowd each other however the cluster sits on the
      // ring. Clusters at the top and bottom share their x with the ring's left
      // side, so their column reaches further out to clear the ring entirely.
      const shown = cluster.claims.slice(0, 18)
      const direction = x <= 450 ? -1 : 1
      const pitch = 30
      const reach = Math.abs(Math.cos(angle)) < 0.3 ? 250 : 96
      const top = Math.max(40, Math.min(GH - 40 - (shown.length - 1) * pitch, y - ((shown.length - 1) * pitch) / 2))
      shown.forEach((claim, at) => {
        const px = x + direction * reach
        const py = top + at * pitch
        edges.push({ x1: x, y1: y, x2: px, y2: py, tone: 'thin' })
        add('claim', claim.id, px, py, 11, 'claim', cut(claim.citation || claim.id, 22), direction < 0 ? 'left' : 'right')
      })
    }

    // While one cluster is expanded the others drop to their number, so their
    // headings do not crowd the claim column.
    const dimmed = hover !== null && hover.kind === 'cluster' && hover.id !== cluster.id
    add(
      'cluster',
      cluster.id,
      x,
      y,
      Math.min(48, 17 + cluster.paper_count * 1.9),
      'cluster',
      dimmed ? `c${index + 1}` : `c${index + 1} · ${cut(cluster.theme, 30)}`,
      Math.sin(angle) < -0.3 ? 'above' : 'below',
    )
  })

  add('root', graph.query_id, cx0, cy0, 26, 'root', 'this run', 'above')
}

/** Papers around the clusters they contributed claims to.
 *
 *  A paper sits by the cluster it gave most of its claims to, with a faint link
 *  out to every other cluster it also reached — that second set is the whole
 *  point of the view: a paper touching three clusters is doing more work than
 *  its rank suggests. Papers that yielded nothing stand apart in the left
 *  margin, drawn dashed, because a run's silent failures are evidence too.
 */
function buildPapers(
  graph: GraphRead,
  { add, edges, frames, captions }: Sink & { frames: SceneFrame[]; captions: SceneCaption[] },
): void {
  const cx0 = 566
  const cy0 = 300
  const clusters = graph.clusters

  const membership = new Map<string, Map<string, number>>()
  for (const cluster of clusters) {
    for (const claim of cluster.claims) {
      const counts = membership.get(claim.paper_id) ?? new Map<string, number>()
      counts.set(cluster.id, (counts.get(cluster.id) ?? 0) + 1)
      membership.set(claim.paper_id, counts)
    }
  }

  const primary = new Map<string, string>()
  for (const [paperId, counts] of membership) {
    const best = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]
    if (best) primary.set(paperId, best[0])
  }

  const hubs = new Map<string, { x: number; y: number; angle: number }>()
  const rx = ringRadius(clusters.length, 236)
  const ry = ringRadius(clusters.length, 150)
  clusters.forEach((cluster, index) => {
    const angle = -Math.PI / 2 + index * ((Math.PI * 2) / (clusters.length || 1))
    hubs.set(cluster.id, { x: cx0 + Math.cos(angle) * rx, y: cy0 + Math.sin(angle) * ry, angle })
  })

  clusters.forEach((cluster, index) => {
    const hub = hubs.get(cluster.id)
    if (!hub) return
    const mine = graph.papers.filter((paper) => primary.get(paper.id) === cluster.id)
    mine.forEach((paper, at) => {
      const spread = hub.angle + (at - (mine.length - 1) / 2) * 0.54
      const reach = 84 + (at % 2) * 28
      const px = hub.x + Math.cos(spread) * reach
      const py = hub.y + Math.sin(spread) * reach * 0.84
      edges.push({ x1: hub.x, y1: hub.y, x2: px, y2: py, tone: 'base' })
      for (const other of membership.get(paper.id)?.keys() ?? []) {
        if (other === cluster.id) continue
        const target = hubs.get(other)
        if (target) edges.push({ x1: px, y1: py, x2: target.x, y2: target.y, tone: 'faint' })
      }
      const vertical = Math.abs(Math.sin(hub.angle)) > 0.6
      add(
        'paper',
        paper.id,
        px,
        py,
        15,
        'paper',
        paperLabel(paper),
        vertical ? (at % 2 ? 'above' : 'below') : Math.cos(spread) >= 0 ? 'right' : 'left',
      )
    })
    add('hub', cluster.id, hub.x, hub.y, 22, 'hub', `c${index + 1}`, Math.sin(hub.angle) < -0.3 ? 'above' : 'below')
  })

  const orphans = graph.papers.filter((paper) => !primary.has(paper.id))
  if (!orphans.length) return

  // Nothing clustered at all — which is a real outcome, not an error. There is
  // no ring to stand beside, so the papers get the whole canvas as a grid
  // rather than a margin column that would run off the bottom of it.
  if (!primary.size) {
    const columns = Math.max(1, Math.ceil(Math.sqrt((orphans.length * GW) / GH)))
    const rows = Math.ceil(orphans.length / columns)
    orphans.forEach((paper, at) => {
      const column = at % columns
      const row = Math.floor(at / columns)
      add(
        'paper',
        paper.id,
        ((column + 1) * GW) / (columns + 1),
        90 + (row * (GH - 150)) / Math.max(1, rows - 1 || 1),
        14,
        'paperDim',
        paperLabel(paper),
        'below',
        true,
      )
    })
    captions.push({
      text: 'no clusters were formed — no paper is placed',
      x: 30,
      y: 34,
      w: 320,
      h: 15,
      size: 9.5,
      align: 'flex-start',
      uppercase: true,
    })
    return
  }

  // Beside a populated ring, the stragglers are a margin column. The pitch is
  // fitted to the space rather than fixed: enough of them and a fixed 58px
  // stack walks off the bottom of the canvas, taking its labels with it.
  const top = 148
  const bottom = GH - 40
  const pitch =
    orphans.length > 1
      ? Math.max(24, Math.min(58, (bottom - top) / (orphans.length - 1)))
      : 58
  orphans.forEach((paper, at) => {
    add('paper', paper.id, 44, top + at * pitch, 13, 'paperDim', paperLabel(paper), 'right', true)
  })
  frames.push({
    x: 18,
    y: 56,
    w: 218,
    h: Math.min(GH - 66, top - 56 + (orphans.length - 1) * pitch + 40),
  })
  captions.push({
    text: 'no claims in any cluster',
    x: 30,
    y: 70,
    w: 170,
    h: 15,
    size: 9.5,
    align: 'flex-start',
    uppercase: true,
  })
}

/** Co-authorship, relaxed into place.
 *
 *  A force layout rather than a ring: who shares a paper with whom has no
 *  natural order to sit in, and a ring would assert one. Seeded from the hash
 *  of each name and run for a fixed number of steps, so it is the same picture
 *  every time it is drawn.
 */
function buildAuthors(
  graph: GraphRead,
  { isActive, add, edges }: Sink & { isActive: (kind: NodeKind, id: string) => boolean },
): void {
  const { authors, edges: pairs } = buildAuthorGraph(graph.papers)
  if (!authors.length) return

  const positions = authorLayout(authors, pairs)

  for (const pair of pairs) {
    const lit = isActive('author', String(pair.a)) || isActive('author', String(pair.b))
    edges.push({
      x1: positions[pair.a].x,
      y1: positions[pair.a].y,
      x2: positions[pair.b].x,
      y2: positions[pair.b].y,
      tone: lit ? 'accent' : 'faint',
    })
  }

  authors.forEach((author, index) => {
    const size = 11 + Math.min(3, author.paperIds.length) * 3
    add(
      'author',
      String(index),
      positions[index].x,
      positions[index].y,
      size,
      author.paperIds.length > 1 ? 'cluster' : 'author',
      author.name,
      'below',
    )
  })
}

const authorLayoutCache = new WeakMap<AuthorNode[], { x: number; y: number }[]>()

function authorLayout(
  authors: AuthorNode[],
  pairs: AuthorGraph['edges'],
): { x: number; y: number }[] {
  const cached = authorLayoutCache.get(authors)
  if (cached) return cached

  const n = authors.length
  const positions = authors.map((author, i) => {
    const angle = (i / n) * Math.PI * 2
    const radius = 150 + (ghash(author.name) % 70)
    return { x: GW / 2 + Math.cos(angle) * radius * 1.5, y: GH / 2 + Math.sin(angle) * radius * 0.95 }
  })

  for (let step = 0; step < 260; step += 1) {
    const fx = new Array<number>(n).fill(0)
    const fy = new Array<number>(n).fill(0)
    for (let i = 0; i < n; i += 1) {
      for (let j = i + 1; j < n; j += 1) {
        const dx = positions[j].x - positions[i].x
        const dy = positions[j].y - positions[i].y
        const d = Math.hypot(dx, dy) || 0.01
        const repulsion = -1800 / (d * d)
        fx[i] += (dx / d) * repulsion
        fy[i] += (dy / d) * repulsion
        fx[j] -= (dx / d) * repulsion
        fy[j] -= (dy / d) * repulsion
      }
    }
    for (const pair of pairs) {
      const dx = positions[pair.b].x - positions[pair.a].x
      const dy = positions[pair.b].y - positions[pair.a].y
      const d = Math.hypot(dx, dy) || 0.01
      const pull = (d - 58) * 0.055
      fx[pair.a] += (dx / d) * pull
      fy[pair.a] += (dy / d) * pull
      fx[pair.b] -= (dx / d) * pull
      fy[pair.b] -= (dy / d) * pull
    }
    for (let i = 0; i < n; i += 1) {
      fx[i] += (GW / 2 - positions[i].x) * 0.0075
      fy[i] += (GH / 2 - positions[i].y) * 0.011
      positions[i].x = Math.max(46, Math.min(GW - 46, positions[i].x + Math.max(-11, Math.min(11, fx[i]))))
      positions[i].y = Math.max(34, Math.min(GH - 34, positions[i].y + Math.max(-11, Math.min(11, fy[i]))))
    }
  }

  authorLayoutCache.set(authors, positions)
  return positions
}

/** Evidence lineage, left to right by publication year.
 *
 *  Every edge here is a step in a cluster's stored lineage tree — which paper
 *  stated a claim first and how each later one relates to it. It is not a
 *  citation graph and the caption under the view says so. A contradicting step
 *  is drawn dashed, which is the one relationship a reader should be able to
 *  find without hovering.
 */
function buildLineage(
  graph: GraphRead,
  {
    isActive,
    add,
    edges,
    axis,
    captions,
  }: Sink & {
    isActive: (kind: NodeKind, id: string) => boolean
    axis: SceneAxisLine[]
    captions: SceneCaption[]
  },
): void {
  const papers = graph.papers
  if (!papers.length) return

  const years = papers.map((paper) => paper.year).filter((year): year is number => year !== null)
  const y0 = years.length ? Math.min(...years) : 0
  const y1 = years.length ? Math.max(...years) : 0
  const span = y1 - y0
  // A run whose papers all share a year (or carry none) has no axis to spread
  // along, so they are spaced evenly instead of stacked on one column.
  const xFor = (year: number | null, index: number): number =>
    span > 0 && year !== null
      ? 92 + ((year - y0) / span) * 716
      : 92 + (papers.length > 1 ? (index / (papers.length - 1)) * 716 : 358)

  // Years sit far tighter than a label is wide, so lanes are assigned
  // round-robin in publication order rather than one lane per year.
  const ordered = [...papers].sort((a, b) => (a.year ?? 0) - (b.year ?? 0) || a.rank - b.rank)
  const LANES = [96, 206, 316, 426, 536]
  const positions = new Map<string, { x: number; y: number }>()
  ordered.forEach((paper, index) => {
    positions.set(paper.id, { x: xFor(paper.year, index), y: LANES[index % LANES.length] })
  })

  if (span > 0) {
    for (const year of [y0, Math.round((y0 + y1) / 2), y1]) {
      const x = 92 + ((year - y0) / span) * 716
      axis.push({ x1: x, y1: 60, x2: x, y2: 566 })
      captions.push({
        text: String(year),
        x: x - 40,
        y: 572,
        w: 80,
        h: 15,
        size: 10.5,
        align: 'center',
        uppercase: false,
      })
    }
  }

  const drawn = new Set<string>()
  for (const edge of graph.lineage) {
    const from = positions.get(edge.from_paper_id)
    const to = positions.get(edge.to_paper_id)
    if (!from || !to) continue
    // One line per pair per relationship: six clusters can assert the same step
    // and drawing it six times only thickens it.
    const key = `${edge.from_paper_id}>${edge.to_paper_id}:${edge.relationship}`
    if (drawn.has(key)) continue
    drawn.add(key)
    const lit = isActive('paper', edge.from_paper_id) || isActive('paper', edge.to_paper_id)
    edges.push({
      x1: from.x,
      y1: from.y,
      x2: to.x,
      y2: to.y,
      tone: lit ? 'accent' : edge.relationship === 'contradicts' ? 'dashed' : 'base',
    })
  }

  // Within a lane, flip a label above its node when its left-hand neighbour is
  // close enough that the two would print over each other.
  const byLane = new Map<number, GraphPaperNode[]>()
  ordered.forEach((paper, index) => {
    const lane = index % LANES.length
    byLane.set(lane, [...(byLane.get(lane) ?? []), paper])
  })
  const sides = new Map<string, LabelSide>()
  for (const list of byLane.values()) {
    const sorted = [...list].sort(
      (a, b) => (positions.get(a.id)?.x ?? 0) - (positions.get(b.id)?.x ?? 0),
    )
    let previous: GraphPaperNode | null = null
    let previousWidth = 0
    let previousSide: LabelSide = 'below'
    for (const paper of sorted) {
      const width = paperLabel(paper).length * 9.5 * 0.58 + 10
      const gap = previous
        ? (positions.get(paper.id)?.x ?? 0) - (positions.get(previous.id)?.x ?? 0)
        : Infinity
      const side: LabelSide =
        previous && gap < (width + previousWidth) / 2 + 8 && previousSide === 'below' ? 'above' : 'below'
      sides.set(paper.id, side)
      previous = paper
      previousWidth = width
      previousSide = side
    }
  }

  for (const paper of papers) {
    const at = positions.get(paper.id)
    if (!at) continue
    const dropped = paper.claim_count === 0
    add(
      'paper',
      paper.id,
      at.x,
      at.y,
      dropped ? 13 : 16,
      dropped ? 'paperDim' : 'paper',
      paperLabel(paper),
      sides.get(paper.id) ?? 'below',
    )
  }
}

// -- the pinned panel -------------------------------------------------------

export interface PanelRow {
  key: string
  value: string
}

export interface PanelItem {
  text: string
  sub: string
}

export interface GraphPanel {
  kicker: string
  title: string
  meta: PanelRow[]
  listLabel: string
  items: PanelItem[]
  /** Where this node leads, when it leads somewhere. A claim and a cluster both
   *  open the cluster screen; a paper and an author have no single destination. */
  go: { clusterId: string; label: string } | null
}

/** What the side panel says about the pinned node.
 *
 *  Built here rather than in the screen so the four kinds read as four cases of
 *  one thing, and so the screen has no branching of its own to get wrong.
 */
export function panelFor(graph: GraphRead, pin: NodeRef | null): GraphPanel | null {
  if (!pin) return null

  if (pin.kind === 'root') {
    const claims = graph.clusters.reduce((total, cluster) => total + cluster.claims.length, 0)
    const years = graph.papers.map((p) => p.year).filter((y): y is number => y !== null)
    return {
      kicker: 'run',
      title: graph.question,
      meta: [
        {
          key: 'papers',
          value: `${graph.papers.filter((p) => p.claim_count > 0).length} of ${graph.papers.length} yielded claims`,
        },
        { key: 'clusters', value: String(graph.clusters.length) },
        { key: 'clustered claims', value: String(claims) },
        {
          key: 'span',
          value: years.length ? `${Math.min(...years)}–${Math.max(...years)}` : '—',
        },
      ],
      listLabel: 'Clusters',
      items: graph.clusters.map((cluster, index) => ({
        text: cluster.theme,
        sub: `c${index + 1} · ${cluster.paper_count} papers · ${cluster.support_count} support · ${cluster.contradiction_count} contradict`,
      })),
      go: null,
    }
  }

  if (pin.kind === 'cluster' || pin.kind === 'hub') {
    const index = graph.clusters.findIndex((cluster) => cluster.id === pin.id)
    const cluster = graph.clusters[index]
    if (!cluster) return null
    return {
      kicker: `cluster c${index + 1}`,
      title: cluster.theme,
      meta: [
        { key: 'quality', value: cluster.quality_tier },
        { key: 'papers', value: String(cluster.paper_count) },
        {
          key: 'stance',
          value: `${cluster.support_count} / ${cluster.contradiction_count} / ${cluster.neutral_count}`,
        },
        { key: 'member claims', value: String(cluster.claims.length) },
      ],
      listLabel: 'Member claims',
      items: cluster.claims.map((claim) => ({
        text: claim.text,
        sub: `${claim.citation} · ${claim.stance}`,
      })),
      go: { clusterId: cluster.id, label: 'Open cluster detail →' },
    }
  }

  if (pin.kind === 'claim') {
    for (const [index, cluster] of graph.clusters.entries()) {
      const claim = cluster.claims.find((entry) => entry.id === pin.id)
      if (!claim) continue
      const paper = graph.papers.find((entry) => entry.id === claim.paper_id)
      return {
        kicker: 'claim',
        title: claim.text,
        meta: [
          { key: 'stance', value: claim.stance },
          { key: 'confidence', value: claim.confidence.toFixed(2) },
          { key: 'paper', value: paper ? paperLabel(paper) : '—' },
          { key: 'cluster', value: `c${index + 1}` },
        ],
        listLabel: 'Source',
        items: [{ text: claim.citation, sub: paper?.title ?? '' }],
        go: { clusterId: cluster.id, label: 'Open cluster detail →' },
      }
    }
    return null
  }

  if (pin.kind === 'paper') {
    const paper = graph.papers.find((entry) => entry.id === pin.id)
    if (!paper) return null
    const inClusters = graph.clusters
      .map((cluster, index) => ({
        cluster,
        index,
        claims: cluster.claims.filter((claim) => claim.paper_id === paper.id),
      }))
      .filter((entry) => entry.claims.length > 0)
    const claims = inClusters.flatMap((entry) =>
      entry.claims.map((claim) => ({
        text: claim.text,
        sub: `c${entry.index + 1} · ${claim.stance} · conf ${claim.confidence.toFixed(2)}`,
      })),
    )
    return {
      kicker: `paper · rank ${paper.rank}`,
      title: paper.title,
      meta: [
        { key: 'authors', value: paper.authors.join(', ') || '—' },
        {
          key: 'venue',
          value: [paper.venue, paper.year].filter(Boolean).join(', ') || '—',
        },
        { key: 'design', value: paper.study_type ?? '—' },
        {
          key: 'citations',
          value: paper.uploaded ? 'uploaded — not indexed' : String(paper.citation_count),
        },
        { key: 'claims extracted', value: String(paper.claim_count) },
      ],
      // Two different silences: a paper that yielded nothing, and one whose
      // claims all fell outside the clusters that were kept. Saying "no claims"
      // for the second would be wrong, and it is the more common of the two.
      listLabel: claims.length ? 'Clustered claims' : 'Nothing in a cluster',
      items: claims.length
        ? claims
        : [
            {
              text:
                paper.dropped_reason ??
                (paper.claim_count > 0
                  ? `${paper.claim_count} claims were extracted, but none reached one of the clusters that were kept.`
                  : 'No claims have been extracted from this paper yet.'),
              sub: '',
            },
          ],
      go: null,
    }
  }

  if (pin.kind === 'author') {
    const { authors, edges } = buildAuthorGraph(graph.papers)
    const index = Number(pin.id)
    const author = authors[index]
    if (!author) return null
    const coauthors = new Set<number>()
    for (const pair of edges) {
      if (pair.a === index) coauthors.add(pair.b)
      if (pair.b === index) coauthors.add(pair.a)
    }
    const papers = author.paperIds
      .map((id) => graph.papers.find((paper) => paper.id === id))
      .filter((paper): paper is GraphPaperNode => paper !== undefined)
    return {
      kicker: 'author',
      title: author.name,
      meta: [
        { key: 'papers in run', value: String(author.paperIds.length) },
        { key: 'co-authors', value: String(coauthors.size) },
        {
          key: 'years',
          value:
            papers
              .map((paper) => paper.year)
              .filter((year): year is number => year !== null)
              .sort((a, b) => a - b)
              .join(', ') || '—',
        },
      ],
      listLabel: 'Papers',
      items: papers.map((paper) => ({
        text: paper.title,
        sub: [paper.venue, paper.year, `${paper.claim_count} claims`].filter(Boolean).join(' · '),
      })),
      go: null,
    }
  }

  return null
}

/** What each tab says it is showing, above the field. */
export const TAB_HINTS: Record<GraphTab, string> = {
  clusters: 'Hover a cluster to expand it into its member claims. Click any node to pin it.',
  papers:
    'Papers sit by the cluster they gave most of their claims to, with a faint link to every other cluster they reached.',
  authors: 'Co-authorship across this run. Filled squares appear in more than one paper.',
  lineage:
    'Evidence lineage between papers, laid out left to right by publication year. Not citations — see the note below.',
}

export function tabCount(graph: GraphRead, tab: GraphTab): number {
  switch (tab) {
    case 'clusters':
      return graph.clusters.length
    case 'papers':
      return graph.papers.length
    case 'authors':
      return buildAuthorGraph(graph.papers).authors.length
    case 'lineage':
      return graph.lineage.length
  }
}

/** Nothing to draw, and why — so the tab can say which of the four it is
 *  rather than showing an empty grid that reads as a bug. */
export function emptyReason(graph: GraphRead, tab: GraphTab): string | null {
  if (tab === 'clusters') {
    return graph.clusters.length
      ? null
      : 'This run formed no clusters, so there is nothing to lay out. A run needs claims from more than one paper before anything clusters.'
  }
  if (tab === 'papers') {
    return graph.papers.length ? null : 'No papers are attached to this run yet.'
  }
  if (tab === 'authors') {
    return buildAuthorGraph(graph.papers).authors.length
      ? null
      : 'None of this run’s papers carry author names — uploaded PDFs often do not.'
  }
  return graph.lineage.length
    ? null
    : 'No lineage was recorded. Lineage is built per cluster from publication order and stance, so a run with no clusters has none.'
}
