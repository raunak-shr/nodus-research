export function num(value: number | null | undefined, fallback = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  return value.toLocaleString('en-US')
}

export function score(value: number | null | undefined, digits = 2, fallback = '—'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback
  return value.toFixed(digits)
}

/** mm:ss, the run header's elapsed clock. */
export function clock(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** "4 m 12 s" — how a finished run reports its duration. */
export function duration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m} m ${String(s).padStart(2, '0')} s`
}

export function timeOfDay(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

export function relativeDay(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const now = new Date()
  const days = Math.floor((startOfDay(now) - startOfDay(d)) / 86_400_000)
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  if (days === 0) return `today, ${time}`
  if (days === 1) return `yesterday, ${time}`
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}, ${time}`
}

export function longDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** Authors as the reading views cite them: three names then et al. */
export function authorLine(authors: { name?: string }[] | undefined): string {
  if (!authors?.length) return 'Unknown authors'
  const names = authors.map((a) => a.name ?? '').filter(Boolean)
  if (names.length <= 3) return names.join(', ')
  return `${names.slice(0, 3).join(', ')} et al.`
}

export function surname(authors: { name?: string }[] | undefined): string {
  const first = authors?.[0]?.name
  if (!first) return 'Unknown'
  const parts = first.trim().split(/\s+/)
  return parts[parts.length - 1] ?? first
}

export function pluralize(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}

export function titleCase(value: string): string {
  return value.replace(/_/g, ' ')
}
