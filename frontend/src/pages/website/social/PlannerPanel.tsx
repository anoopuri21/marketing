import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarDays, CheckSquare, ExternalLink, List, Plus, RefreshCw, Send, Sparkles, Square, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Alert, EmptyState, Modal, Spinner, useToast } from '../../../components/ui'
import { Social, errorMessage, type PostStatus, type SocialPost } from '../../../lib/api'
import { fmtDate, timeAgo } from '../../../lib/utils'
import PostEditor, { emptyEditor, fromPost, type EditorState } from './PostEditor'
import { PLATFORM_LABELS, PlatformIcon, StatusBadge } from './shared'

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

export default function PlannerPanel({ siteId, siteUrl, connected }: { siteId: number; siteUrl: string; connected: string[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const posts = useQuery({ queryKey: ['social-posts', siteId], queryFn: () => Social.posts(siteId), refetchInterval: (q) => (q.state.data?.some((p) => p.status === 'publishing') ? 3000 : 30000) })
  const [view, setView] = useState<'list' | 'calendar'>('list')
  const [filter, setFilter] = useState<PostStatus | 'all'>('all')
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [planOpen, setPlanOpen] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['social-posts', siteId] }); void qc.invalidateQueries({ queryKey: ['social-summary', siteId] }); setSelected(new Set()) }

  const publish = useMutation({
    mutationFn: (id: number) => Social.publishNow(siteId, id),
    onSuccess: (p) => { toast.push(p.status === 'published' ? 'success' : 'error', p.status === 'published' ? 'Published' : p.error); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const remove = useMutation({ mutationFn: (id: number) => Social.deletePost(siteId, id), onSuccess: invalidate })
  const bulk = useMutation({
    mutationFn: (action: 'schedule' | 'draft' | 'delete') => Social.bulk(siteId, [...selected], action),
    onSuccess: (r, action) => { toast.push('success', `${r.updated} post(s) ${action === 'delete' ? 'deleted' : action === 'schedule' ? 'scheduled' : 'moved to drafts'}`); invalidate() },
  })

  const list = useMemo(() => (posts.data ?? []).filter((p) => filter === 'all' || p.status === filter), [posts.data, filter])
  const counts = useMemo(() => (posts.data ?? []).reduce<Record<string, number>>((acc, p) => { acc[p.status] = (acc[p.status] ?? 0) + 1; return acc }, {}), [posts.data])
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={() => setPlanOpen(true)}><Sparkles className="h-4 w-4" /> Generate content plan</button>
        <button className="btn-secondary" onClick={() => setEditor(emptyEditor(connected[0] ?? 'instagram', siteUrl))}><Plus className="h-4 w-4" /> New post</button>
        <div className="ml-auto flex items-center gap-2">
          {selected.size > 0 && (
            <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 text-xs">
              <span className="px-2 text-slate-500">{selected.size} selected</span>
              <button className="btn-secondary px-2 py-1 text-xs" onClick={() => bulk.mutate('schedule')}>Schedule</button>
              <button className="btn-secondary px-2 py-1 text-xs" onClick={() => bulk.mutate('draft')}>To drafts</button>
              <button className="btn-danger px-2 py-1 text-xs" onClick={() => bulk.mutate('delete')}>Delete</button>
            </div>
          )}
          <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs">
            <button className={clsx('rounded-md p-1.5', view === 'list' ? 'bg-white shadow-sm' : 'text-slate-500')} onClick={() => setView('list')} title="List"><List className="h-4 w-4" /></button>
            <button className={clsx('rounded-md p-1.5', view === 'calendar' ? 'bg-white shadow-sm' : 'text-slate-500')} onClick={() => setView('calendar')} title="Calendar"><CalendarDays className="h-4 w-4" /></button>
          </div>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
        {(['all', 'draft', 'scheduled', 'published', 'failed'] as const).map((s) => (
          <button key={s} onClick={() => setFilter(s)} className={clsx('rounded-full px-3 py-1 font-medium capitalize', filter === s ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')}>{s} {s === 'all' ? posts.data?.length ?? 0 : counts[s] ?? 0}</button>
        ))}
      </div>

      {posts.isLoading ? <div className="flex justify-center py-12"><Spinner className="h-6 w-6 text-brand-600" /></div> : list.length === 0 ? (
        <EmptyState icon={<CalendarDays className="h-6 w-6" />} title={filter === 'all' ? 'No posts yet' : `No ${filter} posts`} description="Generate a two-week content plan with branded graphics in one click, or write a single post." action={filter === 'all' ? <button className="btn-primary" onClick={() => setPlanOpen(true)}><Sparkles className="h-4 w-4" /> Generate content plan</button> : undefined} />
      ) : view === 'calendar' ? (
        <CalendarView posts={list} onOpen={(p) => setEditor(fromPost(p))} />
      ) : (
        <div className="space-y-2">
          {list.map((p) => (
            <div key={p.id} className={clsx('card flex gap-3 p-3', p.status === 'failed' && 'border-red-200')}>
              <button className="mt-1 text-slate-400 hover:text-brand-600" onClick={() => toggle(p.id)}>{selected.has(p.id) ? <CheckSquare className="h-4 w-4 text-brand-600" /> : <Square className="h-4 w-4" />}</button>
              {p.creative_url ? <img src={p.creative_url} alt="" className="h-20 w-20 shrink-0 rounded-lg object-cover" loading="lazy" /> : <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-[10px] text-slate-400">no image</div>}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <PlatformIcon platform={p.platform} className="h-6 w-6 rounded-md" />
                  <span className="text-xs font-semibold text-slate-700">{PLATFORM_LABELS[p.platform] ?? p.platform}</span>
                  <StatusBadge status={p.status} />
                  {p.generated_by_ai && <span className="badge bg-violet-50 text-violet-700">AI</span>}
                  <span className="text-xs text-slate-400">{p.status === 'published' ? `published ${timeAgo(p.published_at)}` : p.scheduled_for ? fmtDate(p.scheduled_for, 'EEE dd MMM, HH:mm') : `created ${timeAgo(p.created_at)}`}</span>
                  {p.external_url && <a href={p.external_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline">View <ExternalLink className="h-3 w-3" /></a>}
                </div>
                {p.topic && <div className="mt-1 truncate text-xs font-medium text-slate-500">{p.topic}</div>}
                <p className="mt-1 line-clamp-2 whitespace-pre-line text-sm text-slate-700">{p.content}</p>
                {p.hashtags.length > 0 && <p className="mt-0.5 truncate text-xs text-brand-600">{p.hashtags.join(' ')}</p>}
                {p.error && <p className="mt-1 text-xs text-red-600">{p.error}</p>}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                {p.status !== 'published' && <button className="btn-secondary px-2 py-1 text-xs" onClick={() => setEditor(fromPost(p))}>Edit</button>}
                {p.status !== 'published' && p.status !== 'publishing' && <button className="btn-primary px-2 py-1 text-xs" disabled={!connected.includes(p.platform) || publish.isPending} title={connected.includes(p.platform) ? 'Publish now' : 'Connect the channel first'} onClick={() => publish.mutate(p.id)}><Send className="h-3 w-3" /> Publish</button>}
                {p.status === 'failed' && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => publish.mutate(p.id)}><RefreshCw className="h-3 w-3" /> Retry</button>}
                <button className="btn-ghost px-2 py-1 text-xs text-red-600 hover:bg-red-50" onClick={() => remove.mutate(p.id)}><Trash2 className="h-3 w-3" /></button>
              </div>
            </div>
          ))}
        </div>
      )}

      <PostEditor siteId={siteId} siteUrl={siteUrl} state={editor} connected={connected} onClose={() => setEditor(null)} />
      <PlanModal siteId={siteId} open={planOpen} connected={connected} onClose={() => setPlanOpen(false)} onDone={invalidate} />
    </div>
  )
}

// ------------------------------------------------------------------ calendar view
function CalendarView({ posts, onOpen }: { posts: SocialPost[]; onOpen: (p: SocialPost) => void }) {
  const dated = posts.filter((p) => p.scheduled_for || p.published_at)
  const byDay = new Map<string, SocialPost[]>()
  for (const p of dated) {
    const key = fmtDate(p.scheduled_for ?? p.published_at, 'yyyy-MM-dd')
    byDay.set(key, [...(byDay.get(key) ?? []), p])
  }
  const start = new Date(); start.setHours(0, 0, 0, 0); start.setDate(start.getDate() - start.getDay())
  const days = Array.from({ length: 35 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  const today = fmtDate(new Date().toISOString(), 'yyyy-MM-dd')
  return (
    <div className="card overflow-hidden">
      <div className="grid grid-cols-7 border-b border-slate-100 bg-slate-50 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-500">{['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => <div key={d} className="py-2">{d}</div>)}</div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const key = fmtDate(d.toISOString(), 'yyyy-MM-dd')
          const items = byDay.get(key) ?? []
          return (
            <div key={key} className={clsx('min-h-24 border-b border-r border-slate-100 p-1.5', key === today && 'bg-brand-50/40')}>
              <div className={clsx('mb-1 text-[11px]', key === today ? 'font-bold text-brand-700' : 'text-slate-400')}>{d.getDate()}</div>
              <div className="space-y-1">
                {items.slice(0, 3).map((p) => (
                  <button key={p.id} onClick={() => onOpen(p)} className={clsx('flex w-full items-center gap-1 rounded-md px-1 py-0.5 text-left text-[10px] leading-tight', p.status === 'published' ? 'bg-emerald-50 text-emerald-800' : p.status === 'failed' ? 'bg-red-50 text-red-700' : p.status === 'scheduled' ? 'bg-sky-50 text-sky-800' : 'bg-slate-100 text-slate-600')}>
                    <PlatformIcon platform={p.platform} className="h-3.5 w-3.5 rounded-sm" /><span className="truncate">{fmtDate(p.scheduled_for ?? p.published_at, 'HH:mm')} {p.topic || p.content}</span>
                  </button>
                ))}
                {items.length > 3 && <div className="text-[10px] text-slate-400">+{items.length - 3} more</div>}
              </div>
            </div>
          )
        })}
      </div>
      {dated.length === 0 && <p className="p-4 text-center text-xs text-slate-400">Scheduled posts appear on the calendar.</p>}
    </div>
  )
}

// ------------------------------------------------------------------ plan generator
function PlanModal({ siteId, open, connected, onClose, onDone }: { siteId: number; open: boolean; connected: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [form, setForm] = useState({ platforms: ['instagram', 'facebook', 'linkedin'], weeks: 2, posts_per_week: 3, tone: 'friendly', goals: '', generate_creatives: true, auto_schedule: false })
  const gen = useMutation({
    mutationFn: () => Social.calendar(siteId, { ...form, timezone: TZ }),
    onSuccess: (r) => { toast.push('success', `${r.created} posts created (${r.provider})`); onDone() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const togglePlatform = (p: string) => setForm((f) => ({ ...f, platforms: f.platforms.includes(p) ? f.platforms.filter((x) => x !== p) : [...f.platforms, p] }))
  return (
    <Modal open={open} onClose={() => { gen.reset(); onClose() }} title="Generate a content plan" wide>
      {gen.data ? (
        <div className="space-y-4">
          <Alert kind="success">{gen.data.created} posts added as {form.auto_schedule ? 'scheduled posts (connected channels) / drafts' : 'drafts'} with {form.generate_creatives ? 'branded graphics' : 'no graphics'}. Review, tweak, then schedule.</Alert>
          <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-700"><b>Strategy:</b> {gen.data.strategy}</div>
          <div className="grid max-h-80 gap-2 overflow-y-auto sm:grid-cols-2">
            {gen.data.posts.map((p) => (
              <div key={p.id} className="flex gap-2 rounded-xl border border-slate-200 p-2">
                {p.creative_url && <img src={p.creative_url} alt="" className="h-16 w-16 rounded-md object-cover" />}
                <div className="min-w-0 text-xs"><div className="flex items-center gap-1 font-semibold text-slate-700"><PlatformIcon platform={p.platform} className="h-4 w-4 rounded-sm" />{PLATFORM_LABELS[p.platform]} · {fmtDate(p.scheduled_for, 'EEE dd MMM HH:mm')}</div><div className="truncate font-medium text-slate-600">{p.topic}</div><p className="line-clamp-2 text-slate-500">{p.content}</p></div>
              </div>
            ))}
          </div>
          <div className="flex justify-end"><button className="btn-primary" onClick={() => { gen.reset(); onClose() }}>Done</button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">We use your audit insights, tracked keywords and real Google queries to write a platform-native calendar with a branded graphic per post. Posts land as drafts you can edit before scheduling.</p>
          <div>
            <label className="label">Platforms</label>
            <div className="flex flex-wrap gap-1.5">{['instagram', 'facebook', 'linkedin', 'x', 'webhook'].map((p) => <button key={p} onClick={() => togglePlatform(p)} className={clsx('flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', form.platforms.includes(p) ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600')}><PlatformIcon platform={p} className="h-5 w-5 rounded-md" />{PLATFORM_LABELS[p]}{connected.includes(p) && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />}</button>)}</div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><label className="label">Weeks</label><select className="input" value={form.weeks} onChange={(e) => setForm({ ...form, weeks: Number(e.target.value) })}>{[1, 2, 3, 4, 6, 8].map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
            <div><label className="label">Posts / week</label><select className="input" value={form.posts_per_week} onChange={(e) => setForm({ ...form, posts_per_week: Number(e.target.value) })}>{[1, 2, 3, 4, 5, 7].map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
            <div><label className="label">Tone</label><select className="input" value={form.tone} onChange={(e) => setForm({ ...form, tone: e.target.value })}>{['friendly', 'professional', 'bold', 'educational', 'witty'].map((t) => <option key={t}>{t}</option>)}</select></div>
          </div>
          <div><label className="label">Goals / focus (optional)</label><input className="input" placeholder="e.g. more enquiries for kitchen renovations before Diwali" value={form.goals} onChange={(e) => setForm({ ...form, goals: e.target.value })} /></div>
          <div className="flex flex-wrap gap-4 text-sm text-slate-700">
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.generate_creatives} onChange={(e) => setForm({ ...form, generate_creatives: e.target.checked })} /> Generate a branded graphic per post</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.auto_schedule} onChange={(e) => setForm({ ...form, auto_schedule: e.target.checked })} /> Auto-schedule on connected channels</label>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{form.weeks * form.posts_per_week} posts · best-practice posting times in {TZ}</span>
            <button className="btn-primary" disabled={form.platforms.length === 0 || gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? <><Spinner /> Writing & rendering…</> : <><Sparkles className="h-4 w-4" /> Generate</>}</button>
          </div>
        </div>
      )}
    </Modal>
  )
}
