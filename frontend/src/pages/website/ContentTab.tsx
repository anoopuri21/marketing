import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Copy, FileText, Megaphone, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Alert, Spinner, useToast } from '../../components/ui'
import { Audits, Social, errorMessage } from '../../lib/api'
import { useSite } from './WebsiteLayout'

const PLATFORMS = ['instagram', 'linkedin', 'facebook', 'x', 'google_business']

export default function ContentTab() {
  const { site, latestCompleted } = useSite()
  const toast = useToast()
  const latest = useQuery({ queryKey: ['latest-audit', site.id], queryFn: () => Audits.latest(site.id), enabled: !!latestCompleted, retry: false })
  const [topic, setTopic] = useState('')
  const [platforms, setPlatforms] = useState<string[]>(['instagram', 'linkedin', 'facebook'])
  const [tone, setTone] = useState('friendly')
  const draft = useMutation({ mutationFn: () => Social.draft(site.id, topic, platforms, tone), onError: (e) => toast.push('error', errorMessage(e)) })

  const ideas = latest.data?.ai_insights?.content_ideas ?? []

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5">
        <div className="mb-3 flex items-center gap-2"><FileText className="h-4 w-4 text-brand-600" /><h2 className="font-semibold text-slate-900">Content ideas</h2></div>
        {!latestCompleted ? <p className="text-sm text-slate-500">Run an audit to get content ideas.</p> : ideas.length === 0 ? <p className="text-sm text-slate-500">No ideas generated yet.</p> : (
          <ul className="divide-y divide-slate-100">
            {ideas.map((c, i) => (
              <li key={i} className="flex items-start justify-between gap-3 py-3">
                <div>
                  <div className="text-sm font-medium text-slate-800">{c.title}</div>
                  <div className="mt-0.5 text-xs text-slate-500"><span className="badge mr-1 bg-slate-100 text-slate-600">{c.type}</span> target: “{c.target_query}”</div>
                </div>
                <button className="btn-ghost shrink-0 px-2 py-1 text-xs" onClick={() => { setTopic(c.title); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>Draft posts →</button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card p-5">
        <div className="mb-3 flex items-center gap-2"><Megaphone className="h-4 w-4 text-brand-600" /><h2 className="font-semibold text-slate-900">Social post drafter</h2></div>
        <div className="mb-3"><Alert kind="info">Direct publishing to social accounts arrives in the next phase. Draft here, copy, and post — or schedule via your connected tools.</Alert></div>
        <div className="space-y-3">
          <div><label className="label">Topic / announcement</label><input className="input" placeholder="e.g. 5 things to check before buying a flat in Dwarka" value={topic} onChange={(e) => setTopic(e.target.value)} /></div>
          <div>
            <label className="label">Platforms</label>
            <div className="flex flex-wrap gap-1.5">{PLATFORMS.map((p) => { const on = platforms.includes(p); return <button key={p} onClick={() => setPlatforms(on ? platforms.filter((x) => x !== p) : [...platforms, p])} className={clsx('badge px-3 py-1 text-xs capitalize', on ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600')}>{p.replace('_', ' ')}</button> })}</div>
          </div>
          <div><label className="label">Tone</label><select className="input" value={tone} onChange={(e) => setTone(e.target.value)}>{['friendly', 'professional', 'bold', 'educational', 'witty'].map((t) => <option key={t}>{t}</option>)}</select></div>
          <button className="btn-primary" disabled={!topic.trim() || platforms.length === 0 || draft.isPending} onClick={() => draft.mutate()}>{draft.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />} Draft posts</button>
        </div>
        {draft.data && (
          <div className="mt-5 space-y-3">
            <div className="text-xs text-slate-400">Source: {draft.data.provider}</div>
            {draft.data.posts.map((p, i) => (
              <div key={i} className="rounded-xl border border-slate-200 p-3">
                <div className="mb-1 flex items-center justify-between"><span className="badge bg-brand-50 capitalize text-brand-700">{p.platform.replace('_', ' ')}</span>
                  <button className="btn-ghost px-2 py-1 text-xs" onClick={() => { void navigator.clipboard.writeText(p.content + (p.hashtags?.length ? '\n\n' + p.hashtags.join(' ') : '')); toast.push('success', 'Copied') }}><Copy className="h-3 w-3" /> Copy</button></div>
                <p className="whitespace-pre-line text-sm text-slate-700">{p.content}</p>
                {p.hashtags && p.hashtags.length > 0 && <p className="mt-1 text-xs text-brand-600">{p.hashtags.join(' ')}</p>}
                {p.image_idea && <p className="mt-1 text-xs text-slate-400">🖼 {p.image_idea}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
