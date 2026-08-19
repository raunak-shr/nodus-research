/** The landing hero's field: three axes crossing at a convergence point, with
 *  claims drifting inward along them and igniting as they arrive.
 *
 *  Ported from the canvas logic in `Nodus Landing.dc.html`. It draws the three
 *  axes the product is built on — lineage, disagreement, quality weighting —
 *  and the convergence they meet at, which is what a cluster is.
 *
 *  Colour is read from the CSS custom properties on the canvas rather than
 *  hard-coded, so the band stays consistent with the tokens. Because they are
 *  read once at mount, the effect is keyed on `theme`: a swap re-reads them.
 */

import { useEffect, useRef, type ReactElement } from 'react'

type Vec3 = [number, number, number]
type Rgb = [number, number, number]

interface FieldNode {
  /** Which axis the node travels along. */
  axis: number
  /** Halo nodes drift in the volume instead of hugging a hub. */
  halo: boolean
  /** Position along the axis, signed. */
  u: number
  ang: number
  r: number
  sz: number
  /** Convergence, 0 → 1. At 1 the node is consumed and respawned. */
  c: number
  v: number
  ph: number
  lx: number
  ly: number
  seen: boolean
}

const AXIS_NAMES = ['Lineage', 'Disagreement', 'Quality weighting']

/** Where nodes cluster along each axis — the papers a claim chain sits in. */
const HUBS: number[][] = [
  [-0.8, -0.38, 0.1, 0.52, 0.92],
  [-0.86, -0.42, 0.22, 0.74],
  [-0.62, -0.18, 0.36, 0.84],
]

export function HeroField({ theme }: { theme: 'light' | 'dark' }): ReactElement {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const ctx = cv.getContext('2d')
    if (!ctx) return

    const cs = getComputedStyle(cv)
    const pick = (name: string, fallback: string): string =>
      (cs.getPropertyValue(name) || '').trim() || fallback

    const rgbAccent = toRgb(pick('--l-accent', '#ec3013'), [236, 48, 19])
    const rgbInk = toRgb(pick('--l-void-ink', '#f3f2f2'), [243, 242, 242])
    const rgbVoid = toRgb(pick('--l-void', '#171615'), [23, 22, 21])
    const acc = ramp(rgbAccent)
    const ink = ramp(rgbInk)
    const accClear = `rgba(${rgbAccent.join(',')},0)`
    const voidFill = `rgb(${rgbVoid.join(',')})`
    const voidClear = `rgba(${rgbVoid.join(',')},0)`
    const monoFont = pick('--l-mono', 'ui-monospace, monospace')
    const sprAccent = sprite(rgbAccent)
    const sprInk = sprite(rgbInk)
    const dirs = axisTriad()

    let w = 0
    let h = 0
    let dpr = 1
    let field: FieldNode[] = []
    let pulses: { a: number }[] = []
    let order: number[] = []
    let xs = new Float32Array(0)
    let ys = new Float32Array(0)
    let fs = new Float32Array(0)

    let yaw = -0.55
    let clock = 0
    // Pointer parallax, eased toward the target rather than snapped to it.
    let px = 0
    let py = 0
    let tx = 0
    let ty = 0

    const targetCount = (): number =>
      Math.max(260, Math.min(680, Math.round(((w || 900) * (h || 560)) / 1250)))

    const build = (): void => {
      const n = targetCount()
      field = []
      for (let i = 0; i < n; i += 1) field.push(mkNode(i / n))
      pulses = []
      order = []
    }

    const p3: Vec3 = [0, 0, 0]

    const draw = (): void => {
      if (!w || !h || !field.length) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.fillStyle = voidFill
      ctx.fillRect(0, 0, w, h)

      const scale = Math.min(w * 0.36, h * 0.54)
      const ox = w * 0.53
      const oy = h * 0.5
      const depth = 3.2
      const a = yaw + px
      const pitch = -0.22 + Math.sin(clock * 0.13) * 0.05 + py
      const cA = Math.cos(a)
      const sA = Math.sin(a)
      const cB = Math.cos(pitch)
      const sB = Math.sin(pitch)

      const proj = (x: number, y: number, z: number): void => {
        const X = x * cA + z * sA
        const zr = z * cA - x * sA
        const Y = y * cB - zr * sB
        const Z = y * sB + zr * cB
        const f = depth / (depth + Z)
        p3[0] = ox + X * scale * f
        p3[1] = oy + Y * scale * f
        p3[2] = f
      }

      proj(0, 0, 0)
      const cx = p3[0]
      const cy = p3[1]
      const cf = p3[2]

      // The axes: three passes per arm, widest and faintest first, so the line
      // reads as a shaft of light rather than a stroke.
      const segs = 14
      const reach = 1.34
      for (let ax = 0; ax < 3; ax += 1) {
        const d = dirs[ax]
        const core = ax === 0 ? 2.3 : ax === 1 ? 1.8 : 1.4
        const peak = ax === 0 ? 17 : ax === 1 ? 12 : 8
        for (let pass = 0; pass < 3; pass += 1) {
          ctx.lineWidth = pass === 0 ? core * 5 : pass === 1 ? core * 2.4 : core
          for (let sg = -1; sg <= 1; sg += 2) {
            let x0 = cx
            let y0 = cy
            for (let k = 1; k <= segs; k += 1) {
              const t = (k / segs) * reach * sg
              proj(d[0] * t, d[1] * t, d[2] * t)
              const fall = 1 - (k - 1) / segs
              const step = Math.round((pass === 0 ? 1.1 : pass === 1 ? 2.4 : peak) * fall)
              // The disagreement axis is dashed: it is a split, not a chain.
              const skip = ax === 1 && k % 2 === 0
              if (step >= 1 && !skip) {
                ctx.strokeStyle = ink[Math.min(20, step)]
                ctx.beginPath()
                ctx.moveTo(x0, y0)
                ctx.lineTo(p3[0], p3[1])
                ctx.stroke()
              }
              x0 = p3[0]
              y0 = p3[1]
            }
          }
        }
        // The quality axis carries tick bars — the weighting scale.
        if (ax === 2) {
          for (let sg = -1; sg <= 1; sg += 2) {
            for (let k = 1; k <= 9; k += 1) {
              const t = (k / 9) * reach * sg
              proj(d[0] * t, d[1] * t, d[2] * t)
              const fall = 1 - (k - 1) / 9
              const bw = 13 * p3[2] * fall + 3
              const bh = Math.max(1.2, 2.4 * p3[2])
              ctx.fillStyle = ink[Math.max(2, Math.round(9 * fall))]
              ctx.fillRect(p3[0] - bw / 2, p3[1] - bh / 2, bw, bh)
            }
          }
        }
      }

      // Axis labels, pinned to whichever end faces the viewer, on a leader.
      ctx.font = `600 10px ${monoFont}`
      ctx.textBaseline = 'middle'
      for (let ax = 0; ax < 3; ax += 1) {
        const d = dirs[ax]
        proj(d[0] * reach, d[1] * reach, d[2] * reach)
        const pa: Vec3 = [p3[0], p3[1], p3[2]]
        proj(-d[0] * reach, -d[1] * reach, -d[2] * reach)
        const pb: Vec3 = [p3[0], p3[1], p3[2]]
        const end = pa[2] >= pb[2] ? pa : pb
        const label = AXIS_NAMES[ax].toUpperCase()
        const track = 1.6
        let span = 0
        for (const ch of label) span += ctx.measureText(ch).width + track
        const vx = end[0] - cx
        const vy = end[1] - cy
        const vm = Math.hypot(vx, vy) || 1
        const ax1 = end[0] + (vx / vm) * 16
        const ay1 = end[1] + (vy / vm) * 16
        const left = vx < 0
        const lx = Math.max(8, Math.min(w - span - 8, left ? ax1 - span : ax1))
        const ly = Math.max(12, Math.min(h - 12, ay1))
        ctx.strokeStyle = ink[ax === 0 ? 8 : ax === 1 ? 6 : 5]
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(end[0], end[1])
        ctx.lineTo(left ? lx + span + 4 : lx - 4, ly)
        ctx.stroke()
        ctx.fillStyle = ink[ax === 0 ? 19 : ax === 1 ? 15 : 12]
        let pen = lx
        for (const ch of label) {
          ctx.fillText(ch, pen, ly)
          pen += ctx.measureText(ch).width + track
        }
      }
      ctx.textBaseline = 'alphabetic'

      // Project every node, then paint back to front.
      const n = field.length
      if (order.length !== n) {
        order = new Array<number>(n)
        xs = new Float32Array(n)
        ys = new Float32Array(n)
        fs = new Float32Array(n)
      }
      for (let i = 0; i < n; i += 1) {
        const node = field[i]
        const e = node.c ** 2.3
        const d = dirs[node.axis]
        const b1 = dirs[(node.axis + 1) % 3]
        const b2 = dirs[(node.axis + 2) % 3]
        const u = node.u * (1 - e * 0.98)
        const rr = node.r * (1 - e) ** 1.25 + Math.sin(clock * 0.5 + node.ph) * 0.014
        const ang = node.ang + e * 2.2 + clock * 0.05
        const ca = Math.cos(ang) * rr
        const sa = Math.sin(ang) * rr
        proj(
          d[0] * u + b1[0] * ca + b2[0] * sa,
          d[1] * u + b1[1] * ca + b2[1] * sa,
          d[2] * u + b1[2] * ca + b2[2] * sa,
        )
        xs[i] = p3[0]
        ys[i] = p3[1]
        fs[i] = p3[2]
        order[i] = i
      }
      order.sort((A, B) => fs[A] - fs[B])

      for (let k = 0; k < n; k += 1) {
        const i = order[k]
        const node = field[i]
        const f = fs[i]
        const X = xs[i]
        const Y = ys[i]
        if (f <= 0.2) {
          node.seen = false
          continue
        }
        const conv = node.c
        const near = conv > 0.62
        // The three axes are not equals: lineage leads, quality is the quietest.
        const tier = node.axis === 0 ? 1 : node.axis === 1 ? 0.66 : 0.44
        let al = (node.halo ? 0.36 : 0.95) * tier * (0.34 + (0.66 * Math.min(f, 1.7)) / 1.7)
        if (near) al = Math.min(1, al + (conv - 0.62) * 1.2)
        const step = Math.max(1, Math.min(20, Math.round(al * 20)))
        const hot = conv > 0.72
        const pal = hot ? acc : ink
        const size = Math.max(1, node.sz * f * (near ? 1 - (conv - 0.62) * 0.45 : 1))
        if (near && node.seen) {
          // A trail, drawn from the previous frame's position — the node is
          // moving fast enough by now that a point alone reads as a flicker.
          ctx.strokeStyle = pal[Math.max(1, Math.round(step * 0.55))]
          ctx.beginPath()
          ctx.moveTo(X + (node.lx - X) * 4.2, Y + (node.ly - Y) * 4.2)
          ctx.lineTo(X, Y)
          ctx.stroke()
        }
        const gs = size * (near ? 6.5 : 4.6)
        ctx.globalAlpha = Math.min(0.85, al * (near ? 0.8 : 0.5))
        ctx.drawImage(hot ? sprAccent : sprInk, X - gs / 2, Y - gs / 2, gs, gs)
        ctx.globalAlpha = 1
        ctx.fillStyle = pal[step]
        ctx.fillRect(X - size / 2, Y - size / 2, size, size)
        node.lx = X
        node.ly = Y
        node.seen = true
      }

      // The last stretch: a line to the centre, so arrival is visible.
      let links = 0
      for (let k = n - 1; k >= 0 && links < 9; k -= 1) {
        const i = order[k]
        const node = field[i]
        if (node.c > 0.89) {
          ctx.strokeStyle = acc[Math.max(2, Math.min(12, Math.round((node.c - 0.89) * 9 * 12)))]
          ctx.beginPath()
          ctx.moveTo(xs[i], ys[i])
          ctx.lineTo(cx, cy)
          ctx.stroke()
          links += 1
        }
      }

      // The convergence itself.
      const gr = 78 * cf
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, gr)
      glow.addColorStop(0, acc[6])
      glow.addColorStop(0.45, acc[2])
      glow.addColorStop(1, accClear)
      ctx.fillStyle = glow
      ctx.fillRect(cx - gr, cy - gr, gr * 2, gr * 2)
      for (const q of pulses) {
        const sz = (26 + (1 - q.a) * 104) * cf
        ctx.strokeStyle = acc[Math.max(1, Math.round(q.a * 7))]
        ctx.strokeRect(cx - sz / 2, cy - sz / 2, sz, sz)
      }
      ctx.strokeStyle = acc[11]
      ctx.lineWidth = 1.4
      const os = 24 * cf
      ctx.strokeRect(cx - os / 2, cy - os / 2, os, os)
      ctx.fillStyle = acc[20]
      const is = 11 * cf
      ctx.fillRect(cx - is / 2, cy - is / 2, is, is)

      // Vignette back to the ground, so the field has no cut edge.
      const vr = Math.hypot(w, h) * 0.62
      const vg = ctx.createRadialGradient(cx, cy, vr * 0.06, cx, cy, vr)
      vg.addColorStop(0, voidClear)
      vg.addColorStop(0.55, voidClear)
      vg.addColorStop(1, voidFill)
      ctx.globalAlpha = 0.7
      ctx.fillStyle = vg
      ctx.fillRect(0, 0, w, h)
      ctx.globalAlpha = 1
    }

    const step = (dt: number): void => {
      const e = Math.min(dt * 2.6, 1)
      px += (tx - px) * e
      py += (ty - py) * e
      clock += dt
      yaw += dt * 0.085
      for (let i = 0; i < field.length; i += 1) {
        const node = field[i]
        node.c += node.v * dt
        if (node.c >= 1) {
          field[i] = mkNode(0)
          if (i % 9 === 0 && pulses.length < 4) pulses.push({ a: 1 })
        }
      }
      for (let i = pulses.length - 1; i >= 0; i -= 1) {
        pulses[i].a -= dt * 1.05
        if (pulses[i].a <= 0) pulses.splice(i, 1)
      }
    }

    const resize = (): void => {
      const r = cv.getBoundingClientRect()
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = r.width
      h = r.height
      cv.width = Math.max(1, Math.round(r.width * dpr))
      cv.height = Math.max(1, Math.round(r.height * dpr))
      const n = targetCount()
      // Rebuild only on a real change of scale: a few pixels of reflow must not
      // discard the field and restart every claim's approach.
      if (!field.length || Math.abs(n - field.length) > n * 0.25) build()
      draw()
    }

    let observer: ResizeObserver | null = null
    if (window.ResizeObserver) {
      observer = new ResizeObserver(resize)
      observer.observe(cv)
    } else {
      window.addEventListener('resize', resize)
    }
    resize()

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    if (reduced) {
      // One static frame, and no pointer parallax either: motion on hover is
      // still motion.
      return () => {
        observer?.disconnect()
        window.removeEventListener('resize', resize)
      }
    }

    const onMove = (e: PointerEvent): void => {
      const r = cv.getBoundingClientRect()
      tx = ((e.clientX - r.left) / r.width - 0.5) * 0.7
      ty = ((e.clientY - r.top) / r.height - 0.5) * 0.34
    }
    const onLeave = (): void => {
      tx = 0
      ty = 0
    }
    cv.addEventListener('pointermove', onMove)
    cv.addEventListener('pointerleave', onLeave)

    let offscreen = false
    let visAt = 0
    let last = performance.now()
    let lastDraw = 0
    let raf = 0
    const loop = (now: number): void => {
      raf = requestAnimationFrame(loop)
      if (now - lastDraw < 15) return
      const dt = Math.min((now - last) / 1000, 0.05)
      last = now
      lastDraw = now
      if (now - visAt >= 250) {
        visAt = now
        const r = cv.getBoundingClientRect()
        const vh = window.innerHeight || document.documentElement.clientHeight || 800
        offscreen = r.bottom < -160 || r.top > vh + 160
      }
      if (offscreen) return
      step(dt)
      draw()
    }
    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      observer?.disconnect()
      window.removeEventListener('resize', resize)
      cv.removeEventListener('pointermove', onMove)
      cv.removeEventListener('pointerleave', onLeave)
    }
  }, [theme])

  return <canvas ref={ref} className="lp-field" aria-hidden="true" />
}

/** One claim on its way in. `seed` fixes the starting convergence so a fresh
 *  field is already spread along the axes instead of all leaving at once. */
function mkNode(seed: number | null): FieldNode {
  const axis = Math.floor(Math.random() * 3)
  const halo = Math.random() < 0.3
  const hubs = HUBS[axis]
  return {
    axis,
    halo,
    u: halo
      ? (Math.random() * 2 - 1) * 1.2
      : hubs[Math.floor(Math.random() * hubs.length)] + (Math.random() - 0.5) * 0.16,
    ang: Math.random() * 6.283,
    r: halo ? 0.55 + Math.random() * 1.1 : 0.03 + Math.random() ** 2 * 0.26,
    sz: 1.3 + Math.random() ** 2.4 * 4.2,
    c: seed == null ? Math.random() : seed,
    v: 0.032 + Math.random() * 0.075,
    ph: Math.random() * 6.283,
    lx: 0,
    ly: 0,
    seen: false,
  }
}

/** Three orthonormal directions, tilted off the viewport axes so none of them
 *  reads as a screen edge. */
function axisTriad(): Vec3[] {
  const d0 = norm([1, 0.17, 0.12])
  const d2 = norm(cross(d0, norm([-0.1, 1, 0.26])))
  const d1 = norm(cross(d2, d0))
  return [d0, d1, d2]
}

function norm(v: Vec3): Vec3 {
  const m = Math.hypot(v[0], v[1], v[2])
  return [v[0] / m, v[1] / m, v[2] / m]
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ]
}

function toRgb(value: string, fallback: Rgb): Rgb {
  const hex = /^#?([0-9a-f]{6})$/i.exec(value.trim())
  if (hex) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const fn = /rgba?\(([^)]+)\)/i.exec(value)
  if (fn) {
    const parts = fn[1].split(',').map(Number)
    if (parts.length >= 3) return [parts[0] | 0, parts[1] | 0, parts[2] | 0]
  }
  return fallback
}

/** 21 pre-mixed alpha steps. Building the string per point costs more than the
 *  whole projection does. */
function ramp(rgb: Rgb): string[] {
  const out: string[] = []
  for (let i = 0; i <= 20; i += 1) out.push(`rgba(${rgb.join(',')},${(i / 20).toFixed(3)})`)
  return out
}

/** A radial falloff, drawn once and blitted per node — a gradient per point
 *  would dominate the frame. */
function sprite(rgb: Rgb): HTMLCanvasElement {
  const r = 48
  const c = document.createElement('canvas')
  c.width = r * 2
  c.height = r * 2
  const g = c.getContext('2d')
  if (!g) return c
  const rg = g.createRadialGradient(r, r, 0, r, r, r)
  rg.addColorStop(0, `rgba(${rgb.join(',')},0.95)`)
  rg.addColorStop(0.22, `rgba(${rgb.join(',')},0.34)`)
  rg.addColorStop(0.55, `rgba(${rgb.join(',')},0.08)`)
  rg.addColorStop(1, `rgba(${rgb.join(',')},0)`)
  g.fillStyle = rg
  g.fillRect(0, 0, r * 2, r * 2)
  return c
}
