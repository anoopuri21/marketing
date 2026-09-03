import { formatDistanceToNow, format } from 'date-fns'

export function scoreColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'text-slate-400'
  if (v >= 80) return 'text-emerald-600'
  if (v >= 60) return 'text-amber-600'
  return 'text-red-600'
}

export function scoreBg(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'bg-slate-300'
  if (v >= 80) return 'bg-emerald-500'
  if (v >= 60) return 'bg-amber-500'
  return 'bg-red-500'
}

export function scoreHex(v: number | null | undefined): string {
  if (v === null || v === undefined) return '#cbd5e1'
  if (v >= 80) return '#10b981'
  if (v >= 60) return '#f59e0b'
  return '#ef4444'
}

export const severityStyles: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-sky-100 text-sky-700',
  info: 'bg-slate-100 text-slate-600',
}

export const priorityStyles: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-600',
}

export const categoryLabels: Record<string, string> = {
  seo: 'On-page SEO',
  technical: 'Technical',
  content: 'Content',
  aeo: 'Answer engines (AEO)',
  ai: 'AI search readiness',
  performance: 'Performance',
  social: 'Social',
  outreach: 'Outreach',
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true })
  } catch {
    return '—'
  }
}

export function fmtDate(iso: string | null | undefined, pattern = 'dd MMM yyyy, HH:mm'): string {
  if (!iso) return '—'
  try {
    return format(new Date(iso), pattern)
  } catch {
    return '—'
  }
}

export const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export function pad(n: number): string {
  return n.toString().padStart(2, '0')
}

/** Format an ISO timestamp in a specific IANA timezone (falls back to local). */
export function fmtDateTz(iso: string | null | undefined, tz: string): string {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz,
    }).format(new Date(iso))
  } catch {
    return fmtDate(iso)
  }
}
