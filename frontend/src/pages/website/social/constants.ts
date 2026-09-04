import type { PostStatus } from '../../../lib/api'

export const PLATFORM_COLORS: Record<string, string> = {
  facebook: 'bg-[#1877F2]/10 text-[#1877F2]', instagram: 'bg-pink-50 text-pink-600', linkedin: 'bg-[#0A66C2]/10 text-[#0A66C2]',
  x: 'bg-slate-900/10 text-slate-900', webhook: 'bg-violet-50 text-violet-700', google_business: 'bg-emerald-50 text-emerald-700',
}
export const PLATFORM_LABELS: Record<string, string> = { facebook: 'Facebook', instagram: 'Instagram', linkedin: 'LinkedIn', x: 'X', webhook: 'Webhook', google_business: 'Google Business' }

export const STATUS_STYLES: Record<PostStatus, string> = {
  draft: 'bg-slate-100 text-slate-600', scheduled: 'bg-sky-50 text-sky-700', publishing: 'bg-amber-50 text-amber-700',
  published: 'bg-emerald-50 text-emerald-700', failed: 'bg-red-50 text-red-700',
}

/** ISO string → value for `<input type="datetime-local">` in the browser's local time. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fromLocalInput(v: string): string | null {
  return v ? new Date(v).toISOString() : null
}
