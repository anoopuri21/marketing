import clsx from 'clsx'
import { Globe, Webhook } from 'lucide-react'
import type { ComponentType, SVGProps } from 'react'
import type { PostStatus } from '../../../lib/api'
import { PLATFORM_COLORS, STATUS_STYLES } from './constants'

type IconProps = SVGProps<SVGSVGElement>
// Brand glyphs (lucide dropped brand icons) – simple path icons, currentColor.
const FacebookIcon = (p: IconProps) => <svg viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M13.5 21v-7.5h2.6l.4-3h-3V8.6c0-.9.3-1.5 1.5-1.5h1.6V4.4c-.3 0-1.2-.1-2.3-.1-2.3 0-3.9 1.4-3.9 4v2.2H7.8v3h2.6V21h3.1z" /></svg>
const InstagramIcon = (p: IconProps) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}><rect x="3" y="3" width="18" height="18" rx="5" /><circle cx="12" cy="12" r="4" /><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none" /></svg>
const LinkedinIcon = (p: IconProps) => <svg viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M6.4 9.2H3.3V20h3.1V9.2zM4.9 4a1.8 1.8 0 100 3.6 1.8 1.8 0 000-3.6zM20.7 13.4c0-3.2-1.7-4.6-4-4.6-1.8 0-2.7 1-3.1 1.7V9.2h-3.1c0 .9 0 10.8 0 10.8h3.1v-6c0-.3 0-.6.1-.9.3-.6.8-1.3 1.7-1.3 1.2 0 1.7.9 1.7 2.3V20h3.1v-6.6z" /></svg>
const XIcon = (p: IconProps) => <svg viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M17.5 3h3l-6.8 7.8L21.7 21h-6.2l-4.9-6.4L5 21H2l7.3-8.3L1.6 3H8l4.4 5.8L17.5 3zm-1.1 16.2h1.7L7.1 4.7H5.3l11.1 14.5z" /></svg>

const PLATFORM_ICONS: Record<string, ComponentType<IconProps>> = { facebook: FacebookIcon, instagram: InstagramIcon, linkedin: LinkedinIcon, x: XIcon, webhook: Webhook, google_business: Globe }

export function PlatformIcon({ platform, className }: { platform: string; className?: string }) {
  const Icon = PLATFORM_ICONS[platform] ?? Globe
  return <span className={clsx('inline-flex h-7 w-7 items-center justify-center rounded-lg', PLATFORM_COLORS[platform] ?? 'bg-slate-100 text-slate-600', className)}><Icon className="h-4 w-4" /></span>
}

export function StatusBadge({ status }: { status: PostStatus }) {
  return <span className={clsx('badge capitalize', STATUS_STYLES[status])}>{status}</span>
}
