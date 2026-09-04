import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarDays, FileText, ImagePlus, Lightbulb, Plug } from 'lucide-react'
import { useState } from 'react'
import { Alert, Spinner } from '../../components/ui'
import { Audits, Social } from '../../lib/api'
import { fmtDate } from '../../lib/utils'
import { useSite } from '../../hooks/useSite'
import ChannelsPanel from './social/ChannelsPanel'
import CreativeStudio from './social/CreativeStudio'
import PlannerPanel from './social/PlannerPanel'
import { PLATFORM_LABELS } from './social/constants'
import { PlatformIcon } from './social/shared'

type Section = 'planner' | 'studio' | 'channels' | 'ideas'

export default function ContentTab() {
  const { site, latestCompleted } = useSite()
  const [section, setSection] = useState<Section>('planner')
  const summary = useQuery({ queryKey: ['social-summary', site.id], queryFn: () => Social.summary(site.id) })
  const latest = useQuery({ queryKey: ['latest-audit', site.id], queryFn: () => Audits.latest(site.id), enabled: !!latestCompleted && section === 'ideas', retry: false })
  const connected = summary.data?.connected ?? []
  const counts = summary.data?.counts ?? {}

  const nav: { id: Section; label: string; icon: typeof CalendarDays; hint?: string }[] = [
    { id: 'planner', label: 'Planner & posts', icon: CalendarDays, hint: summary.data ? `${counts.scheduled ?? 0} scheduled · ${counts.published ?? 0} published` : undefined },
    { id: 'studio', label: 'Creative studio', icon: ImagePlus },
    { id: 'channels', label: 'Channels', icon: Plug, hint: connected.length ? `${connected.length} connected` : 'none connected' },
    { id: 'ideas', label: 'Content ideas', icon: Lightbulb },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {nav.map((n) => (
          <button key={n.id} onClick={() => setSection(n.id)} className={clsx('flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition', section === n.id ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300')}>
            <n.icon className="h-4 w-4" />{n.label}{n.hint && <span className="hidden text-[11px] font-normal text-slate-400 sm:inline">· {n.hint}</span>}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-1">
          {connected.map((p) => <PlatformIcon key={p} platform={p} className="h-6 w-6 rounded-md" />)}
          {summary.data?.next_scheduled_for && <span className="ml-2 text-xs text-slate-400">next post {fmtDate(summary.data.next_scheduled_for, 'EEE dd MMM, HH:mm')}</span>}
        </div>
      </div>

      {summary.data && connected.length === 0 && section === 'planner' && (
        <Alert kind="info">No channels connected yet – posts can still be planned, written and designed. <button className="font-semibold underline" onClick={() => setSection('channels')}>Connect Facebook, Instagram, LinkedIn, X or a webhook</button> to publish automatically at the scheduled time.</Alert>
      )}

      {section === 'planner' && <PlannerPanel siteId={site.id} siteUrl={site.url} connected={connected} />}
      {section === 'studio' && <CreativeStudio siteId={site.id} />}
      {section === 'channels' && <ChannelsPanel siteId={site.id} />}
      {section === 'ideas' && <IdeasPanel loading={latest.isLoading} hasAudit={!!latestCompleted} ideas={latest.data?.ai_insights?.content_ideas ?? []} themes={latest.data?.ai_insights?.keyword_themes ?? []} onUse={() => setSection('planner')} />}
    </div>
  )
}

function IdeasPanel({ loading, hasAudit, ideas, themes, onUse }: { loading: boolean; hasAudit: boolean; ideas: { title: string; type: string; target_query: string }[]; themes: string[]; onUse: () => void }) {
  if (loading) return <div className="flex justify-center py-12"><Spinner className="h-6 w-6 text-brand-600" /></div>
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="card p-5 lg:col-span-2">
        <div className="mb-3 flex items-center gap-2"><FileText className="h-4 w-4 text-brand-600" /><h2 className="font-semibold text-slate-900">Content ideas from the audit</h2></div>
        {!hasAudit ? <p className="text-sm text-slate-500">Run an audit to get content ideas.</p> : ideas.length === 0 ? <p className="text-sm text-slate-500">No ideas generated yet.</p> : (
          <ul className="divide-y divide-slate-100">
            {ideas.map((c, i) => (
              <li key={i} className="flex items-start justify-between gap-3 py-3">
                <div>
                  <div className="text-sm font-medium text-slate-800">{c.title}</div>
                  <div className="mt-0.5 text-xs text-slate-500"><span className="badge mr-1 bg-slate-100 text-slate-600">{c.type}</span> target: “{c.target_query}”</div>
                </div>
                <button className="btn-ghost shrink-0 px-2 py-1 text-xs" onClick={onUse}>Plan posts →</button>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-slate-400">The content planner already uses these ideas, your tracked keywords and real Search Console queries when it writes a calendar.</p>
      </div>
      <div className="card p-5">
        <h2 className="mb-3 font-semibold text-slate-900">Keyword themes to reinforce</h2>
        {themes.length === 0 ? <p className="text-sm text-slate-500">Themes appear after the first audit.</p> : <div className="flex flex-wrap gap-1.5">{themes.map((k, i) => <span key={i} className="badge bg-brand-50 px-2.5 py-1 text-xs text-brand-700">{k}</span>)}</div>}
        <div className="mt-4 text-xs text-slate-500">Tip: every social post should point back to a page that answers the question – that's how social activity turns into rankings. Supported networks: {Object.values(PLATFORM_LABELS).slice(0, 5).join(', ')}.</div>
      </div>
    </div>
  )
}
