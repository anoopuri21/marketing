import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertTriangle, CheckSquare, Clock, Copy, Download, ExternalLink, Globe, Kanban, List, MapPin, Phone, Plus, RefreshCw, Search,
  Sparkles, Square, Star, Target, Trash2, Upload, X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, EmptyState, Modal, ScoreRing, Spinner, Stat } from '../../components/ui'
import { useToast } from '../../hooks/useToast'
import { Leads, errorMessage, type Lead, type LeadStatus } from '../../lib/api'
import { fmtDate, scoreColor, timeAgo } from '../../lib/utils'
import { useSite } from '../../hooks/useSite'

const STATUSES: { id: LeadStatus; label: string; color: string }[] = [
  { id: 'new', label: 'New', color: 'bg-slate-100 text-slate-700' },
  { id: 'contacted', label: 'Contacted', color: 'bg-sky-50 text-sky-700' },
  { id: 'replied', label: 'Replied', color: 'bg-violet-50 text-violet-700' },
  { id: 'qualified', label: 'Qualified', color: 'bg-amber-50 text-amber-700' },
  { id: 'won', label: 'Won', color: 'bg-emerald-50 text-emerald-700' },
  { id: 'lost', label: 'Lost', color: 'bg-red-50 text-red-600' },
]
const statusMeta = (s: LeadStatus) => STATUSES.find((x) => x.id === s) ?? STATUSES[0]

function ScorePill({ value, title }: { value: number; title?: string }) {
  const tone = value >= 70 ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : value >= 45 ? 'bg-amber-50 text-amber-700 ring-amber-200' : 'bg-slate-100 text-slate-600 ring-slate-200'
  return <span title={title} className={clsx('inline-flex h-8 min-w-8 items-center justify-center rounded-lg px-1.5 text-sm font-bold ring-1', tone)}>{value}</span>
}

export default function LeadsTab() {
  const { site } = useSite()
  const qc = useQueryClient()
  const toast = useToast()
  const [view, setView] = useState<'list' | 'board'>('list')
  const [filter, setFilter] = useState<LeadStatus | 'all' | 'due'>('all')
  const [campaign, setCampaign] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [open, setOpen] = useState<number | null>(null)
  const [findOpen, setFindOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const summary = useQuery({ queryKey: ['lead-summary', site.id], queryFn: () => Leads.summary(site.id) })
  const leads = useQuery({
    queryKey: ['leads', site.id, campaign],
    queryFn: () => Leads.list(site.id, { campaign: campaign || undefined, sort: 'score' }),
    refetchInterval: (query) => (query.state.data?.some((l) => !l.qualified_at && !l.qualify_error) ? 4000 : false),
  })
  const campaigns = useQuery({ queryKey: ['lead-campaigns', site.id], queryFn: () => Leads.campaigns(site.id) })
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['leads', site.id] }); void qc.invalidateQueries({ queryKey: ['lead-summary', site.id] }); void qc.invalidateQueries({ queryKey: ['lead-campaigns', site.id] }) }

  const bulk = useMutation({
    mutationFn: ({ action, status }: { action: 'qualify' | 'delete' | 'status'; status?: LeadStatus }) => Leads.bulk(site.id, [...selected], action, status),
    onSuccess: (r, v) => { toast.push('success', v.action === 'qualify' ? `${r.updated} lead(s) queued for qualification` : `${r.updated} lead(s) updated`); setSelected(new Set()); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const importCsv = useMutation({
    mutationFn: (f: File) => Leads.importCsv(site.id, f),
    onSuccess: (r) => { toast.push('success', `${r.created} imported, ${r.skipped} skipped · qualifying in background`); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const download = async () => {
    try {
      const blob = await Leads.exportBlob(site.id, filter !== 'all' && filter !== 'due' ? filter : undefined)
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `leads-${site.domain}.csv`; a.click(); URL.revokeObjectURL(url)
    } catch (e) { toast.push('error', errorMessage(e)) }
  }

  const now = leads.dataUpdatedAt // "due" is judged as of the last fetch – pure during render
  const list = useMemo(() => {
    return (leads.data ?? []).filter((l) => {
      if (filter === 'due') { if (!l.next_follow_up_at || new Date(l.next_follow_up_at).getTime() > now || l.status === 'won' || l.status === 'lost') return false }
      else if (filter !== 'all' && l.status !== filter) return false
      if (q) { const s = q.toLowerCase(); return [l.company, l.website_url, l.category, l.location, l.contact_name, l.pitch?.angle ?? ''].some((v) => v?.toLowerCase().includes(s)) }
      return true
    })
  }, [leads.data, filter, q, now])
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const allSelected = list.length > 0 && list.every((l) => selected.has(l.id))
  const pending = (leads.data ?? []).filter((l) => !l.qualified_at && !l.qualify_error).length
  const counts = summary.data?.counts

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Prospects" value={summary.data?.total ?? '–'} hint={summary.data?.provider === 'demo' ? 'demo mode' : `via ${summary.data?.provider ?? '…'}`} />
        <Stat label="Avg. opportunity" value={summary.data?.avg_score ?? '–'} hint="0–100, higher = needs you more" />
        <Stat label="In conversation" value={counts ? counts.contacted + counts.replied + counts.qualified : '–'} hint="contacted · replied · qualified" />
        <Stat label="Won" value={counts?.won ?? '–'} hint={counts ? `${counts.lost} lost` : undefined} accent="text-emerald-600" />
        <Stat label="Follow-ups due" value={summary.data?.follow_ups_due ?? '–'} hint={summary.data?.follow_ups_due ? <button className="text-brand-600 hover:underline" onClick={() => setFilter('due')}>show →</button> : 'nothing overdue'} accent={summary.data?.follow_ups_due ? 'text-amber-600' : undefined} />
      </div>

      {summary.data?.provider === 'demo' && (
        <Alert kind="info"><b>Demo mode:</b> prospects are sample businesses on example.com so you can try the whole flow. Add <code>SERPAPI_KEY</code> to <code>backend/.env</code> to discover real businesses from Google Maps and Google Search for any service + city.</Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={() => setFindOpen(true)}><Search className="h-4 w-4" /> Find prospects</button>
        <button className="btn-secondary" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add lead</button>
        <button className="btn-secondary" onClick={() => fileRef.current?.click()} disabled={importCsv.isPending}>{importCsv.isPending ? <Spinner /> : <Upload className="h-4 w-4" />} Import CSV</button>
        <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) importCsv.mutate(f); e.target.value = '' }} />
        <button className="btn-ghost" onClick={download} disabled={!leads.data?.length}><Download className="h-4 w-4" /> Export</button>
        {pending > 0 && <span className="flex items-center gap-1.5 text-xs text-slate-500"><Spinner /> qualifying {pending} lead{pending > 1 ? 's' : ''}…</span>}
        <div className="ml-auto flex items-center gap-2">
          {selected.size > 0 && (
            <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1 text-xs">
              <span className="px-2 text-slate-500">{selected.size} selected</span>
              <button className="btn-secondary px-2 py-1 text-xs" onClick={() => bulk.mutate({ action: 'qualify' })}>Re-qualify</button>
              <select className="input w-auto py-1 text-xs" value="" onChange={(e) => { if (e.target.value) bulk.mutate({ action: 'status', status: e.target.value as LeadStatus }) }}>
                <option value="">Move to…</option>{STATUSES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
              <button className="btn-danger px-2 py-1 text-xs" onClick={() => bulk.mutate({ action: 'delete' })}>Delete</button>
            </div>
          )}
          <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs">
            <button className={clsx('rounded-md p-1.5', view === 'list' ? 'bg-white shadow-sm' : 'text-slate-500')} onClick={() => setView('list')} title="List"><List className="h-4 w-4" /></button>
            <button className={clsx('rounded-md p-1.5', view === 'board' ? 'bg-white shadow-sm' : 'text-slate-500')} onClick={() => setView('board')} title="Pipeline board"><Kanban className="h-4 w-4" /></button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button onClick={() => setFilter('all')} className={clsx('rounded-full px-3 py-1 font-medium', filter === 'all' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')}>All {leads.data?.length ?? 0}</button>
        {STATUSES.map((s) => <button key={s.id} onClick={() => setFilter(s.id)} className={clsx('rounded-full px-3 py-1 font-medium', filter === s.id ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')}>{s.label} {counts?.[s.id] ?? 0}</button>)}
        <button onClick={() => setFilter('due')} className={clsx('rounded-full px-3 py-1 font-medium', filter === 'due' ? 'bg-amber-500 text-white' : 'bg-amber-50 text-amber-700 hover:bg-amber-100')}><Clock className="mr-1 inline h-3 w-3" />Follow-up due</button>
        <select className="input ml-auto w-auto py-1 text-xs" value={campaign} onChange={(e) => setCampaign(e.target.value)}>
          <option value="">All searches</option>
          {campaigns.data?.map((c) => <option key={c.campaign} value={c.campaign}>{c.query}{c.location ? ` · ${c.location}` : ''} ({c.campaign.replace('find-', '')})</option>)}
        </select>
        <div className="relative"><Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" /><input className="input w-48 py-1 pl-7 text-xs" placeholder="Search leads" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      </div>

      {leads.isLoading ? <div className="flex justify-center py-12"><Spinner className="h-6 w-6 text-brand-600" /></div> : list.length === 0 ? (
        <EmptyState icon={<Target className="h-6 w-6" />} title={leads.data?.length ? 'No leads match this filter' : 'No prospects yet'}
          description={leads.data?.length ? 'Try another status or clear the search.' : 'Search a service + city (e.g. “dentist in Delhi”). We find businesses, run a mini SEO audit on each website, score the opportunity and write a personalised pitch.'}
          action={!leads.data?.length ? <button className="btn-primary" onClick={() => setFindOpen(true)}><Search className="h-4 w-4" /> Find prospects</button> : undefined} />
      ) : view === 'board' ? (
        <Board leads={list} onOpen={setOpen} siteId={site.id} onChanged={invalidate} />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="w-8 px-3 py-2"><button onClick={() => setSelected(allSelected ? new Set() : new Set(list.map((l) => l.id)))} className="text-slate-400 hover:text-brand-600">{allSelected ? <CheckSquare className="h-4 w-4 text-brand-600" /> : <Square className="h-4 w-4" />}</button></th>
                <th className="px-3 py-2">Opportunity</th>
                <th className="px-3 py-2">Business</th>
                <th className="hidden px-3 py-2 md:table-cell">Website health</th>
                <th className="hidden px-3 py-2 lg:table-cell">Pitch angle</th>
                <th className="px-3 py-2">Status</th>
                <th className="hidden px-3 py-2 xl:table-cell">Next step</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {list.map((l) => {
                const due = l.next_follow_up_at && new Date(l.next_follow_up_at).getTime() <= now && !['won', 'lost'].includes(l.status)
                return (
                  <tr key={l.id} className="cursor-pointer hover:bg-slate-50/80" onClick={() => setOpen(l.id)}>
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}><button onClick={() => toggle(l.id)} className="text-slate-400 hover:text-brand-600">{selected.has(l.id) ? <CheckSquare className="h-4 w-4 text-brand-600" /> : <Square className="h-4 w-4" />}</button></td>
                    <td className="px-3 py-2.5"><ScorePill value={l.score} title="Opportunity score" /></td>
                    <td className="px-3 py-2.5">
                      <div className="font-medium text-slate-800">{l.company}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500">
                        {l.website_url ? <span className="inline-flex items-center gap-1"><Globe className="h-3 w-3" />{l.website_url.replace(/^https?:\/\//, '').replace(/\/$/, '')}</span> : <span className="inline-flex items-center gap-1 text-amber-600"><AlertTriangle className="h-3 w-3" /> no website</span>}
                        {l.location && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{l.location}</span>}
                        {l.rating != null && <span className="inline-flex items-center gap-1"><Star className="h-3 w-3 text-amber-500" />{l.rating}{l.reviews != null && <span className="text-slate-400">({l.reviews})</span>}</span>}
                        {l.phone && <span className="inline-flex items-center gap-1"><Phone className="h-3 w-3" />{l.phone}</span>}
                      </div>
                    </td>
                    <td className="hidden px-3 py-2.5 md:table-cell">
                      {!l.qualified_at && !l.qualify_error ? <span className="flex items-center gap-1 text-xs text-slate-400"><Spinner /> auditing…</span>
                        : l.website_score != null ? <div><span className={clsx('text-sm font-semibold', scoreColor(l.website_score))}>{l.website_score}</span><span className="text-xs text-slate-400">/100</span><div className="truncate text-[11px] text-slate-500">{(l.audit.gaps ?? []).slice(0, 2).map((g) => g.label).join(' · ')}</div></div>
                        : <span className="text-xs text-slate-500">{l.audit.gaps?.[0]?.label ?? '–'}</span>}
                    </td>
                    <td className="hidden max-w-xs px-3 py-2.5 lg:table-cell"><div className="truncate text-xs text-slate-600">{l.pitch?.angle ?? <span className="text-slate-400">pending</span>}</div></td>
                    <td className="px-3 py-2.5"><span className={clsx('badge', statusMeta(l.status).color)}>{statusMeta(l.status).label}</span></td>
                    <td className="hidden px-3 py-2.5 text-xs xl:table-cell">
                      {due ? <span className="font-medium text-amber-600">Follow up now</span> : l.next_follow_up_at ? <span className="text-slate-500">Follow up {fmtDate(l.next_follow_up_at, 'dd MMM')}</span> : l.status === 'new' && l.qualified_at ? <span className="text-slate-500">Send the pitch</span> : <span className="text-slate-400">–</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <LeadDrawer siteId={site.id} leadId={open} onClose={() => setOpen(null)} onChanged={invalidate} />
      {findOpen && <FindModal siteId={site.id} onClose={() => setFindOpen(false)} onDone={(c) => { setCampaign(c); invalidate() }} defaultQuery={site.industry || ''} defaultLocation={site.target_location || ''} />}
      <AddModal siteId={site.id} open={addOpen} onClose={() => setAddOpen(false)} onDone={invalidate} />
    </div>
  )
}

// ------------------------------------------------------------------ board
function Board({ leads, onOpen, siteId, onChanged }: { leads: Lead[]; onOpen: (id: number) => void; siteId: number; onChanged: () => void }) {
  const toast = useToast()
  const move = useMutation({ mutationFn: ({ id, status }: { id: number; status: LeadStatus }) => Leads.setStatus(siteId, id, status), onSuccess: onChanged, onError: (e) => toast.push('error', errorMessage(e)) })
  const [drag, setDrag] = useState<number | null>(null)
  return (
    <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      {STATUSES.map((s) => {
        const items = leads.filter((l) => l.status === s.id)
        return (
          <div key={s.id} className="rounded-2xl bg-slate-50 p-2" onDragOver={(e) => e.preventDefault()} onDrop={() => { if (drag != null) move.mutate({ id: drag, status: s.id }); setDrag(null) }}>
            <div className="mb-2 flex items-center justify-between px-1"><span className={clsx('badge', s.color)}>{s.label}</span><span className="text-xs text-slate-400">{items.length}</span></div>
            <div className="space-y-2">
              {items.map((l) => (
                <div key={l.id} draggable onDragStart={() => setDrag(l.id)} onClick={() => onOpen(l.id)} className="card cursor-pointer p-2.5 text-xs hover:border-brand-300">
                  <div className="flex items-start justify-between gap-2"><span className="font-semibold text-slate-800">{l.company}</span><ScorePill value={l.score} /></div>
                  <div className="mt-1 truncate text-slate-500">{l.pitch?.angle ?? l.category}</div>
                  {l.next_follow_up_at && !['won', 'lost'].includes(l.status) && <div className={clsx('mt-1 inline-flex items-center gap-1', new Date(l.next_follow_up_at).getTime() <= Date.now() ? 'text-amber-600' : 'text-slate-400')}><Clock className="h-3 w-3" />{fmtDate(l.next_follow_up_at, 'dd MMM')}</div>}
                </div>
              ))}
              {items.length === 0 && <div className="rounded-xl border border-dashed border-slate-200 p-3 text-center text-[11px] text-slate-400">Drop here</div>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------ find prospects
function FindModal({ siteId, onClose, onDone, defaultQuery, defaultLocation }: { siteId: number; onClose: () => void; onDone: (campaign: string) => void; defaultQuery: string; defaultLocation: string }) {
  const toast = useToast()
  // Mounted only while open, so the initial state is the "reset" – no effect needed.
  const [form, setForm] = useState({ query: '', location: defaultLocation, mode: 'maps' as 'maps' | 'organic' | 'both', limit: 20, qualify: true })
  const find = useMutation({
    mutationFn: () => Leads.discover(siteId, { ...form, query: form.query.trim(), location: form.location.trim() }),
    onSuccess: (r) => { toast.push('success', `${r.created} new prospects added${r.skipped ? ` (${r.skipped} already known)` : ''}`); onDone(r.campaign) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const suggestions = ['dentist', 'interior designer', 'real estate agent', 'coaching institute', 'restaurant', 'gym', 'salon', 'CA firm', 'wedding photographer', 'clinic']
  return (
    <Modal open onClose={() => { find.reset(); onClose() }} title="Find prospects" wide>
      {find.data ? (
        <div className="space-y-4">
          <Alert kind={find.data.created ? 'success' : 'info'}>{find.data.found} businesses found via {find.data.provider} · {find.data.created} new added{find.data.skipped ? ` · ${find.data.skipped} skipped (duplicates / your own site)` : ''}. {form.qualify && find.data.created ? 'Mini audits + pitches are being generated in the background – scores update live.' : ''}</Alert>
          {find.data.note && <p className="text-xs text-slate-500">{find.data.note}</p>}
          <div className="max-h-72 space-y-1.5 overflow-y-auto">
            {find.data.leads.map((l) => (
              <div key={l.id} className="flex items-center gap-3 rounded-xl border border-slate-200 p-2 text-xs">
                <ScorePill value={l.score} title="Provisional score – updates after the audit" />
                <div className="min-w-0 flex-1"><div className="font-semibold text-slate-800">{l.company}</div><div className="truncate text-slate-500">{l.website_url || 'no website'}{l.address ? ` · ${l.address}` : ''}</div></div>
                {l.rating != null && <span className="inline-flex items-center gap-1 text-slate-500"><Star className="h-3 w-3 text-amber-500" />{l.rating} ({l.reviews ?? 0})</span>}
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => find.reset()}>Search again</button><button className="btn-primary" onClick={() => { find.reset(); onClose() }}>Done</button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">Tell us who your ideal customer is. We search Google Maps / Google for matching businesses, skip directories and your own site, then audit each website to find what they need – so every pitch is specific.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div><label className="label">Business type / service</label><input className="input" placeholder={defaultQuery ? `e.g. ${defaultQuery}` : 'e.g. dentist, interior designer'} value={form.query} onChange={(e) => setForm({ ...form, query: e.target.value })} autoFocus />
              <div className="mt-1.5 flex flex-wrap gap-1">{suggestions.map((s) => <button key={s} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200" onClick={() => setForm({ ...form, query: s })}>{s}</button>)}</div></div>
            <div><label className="label">Location</label><input className="input" placeholder="e.g. Delhi, Gurgaon, Dubai" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div><label className="label">Source</label><select className="input" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as typeof form.mode })}><option value="maps">Google Maps (local businesses)</option><option value="organic">Google Search (companies ranking)</option><option value="both">Both</option></select></div>
            <div><label className="label">How many</label><select className="input" value={form.limit} onChange={(e) => setForm({ ...form, limit: Number(e.target.value) })}>{[10, 20, 40, 60].map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
            <div className="flex items-end pb-2"><label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={form.qualify} onChange={(e) => setForm({ ...form, qualify: e.target.checked })} /> Audit websites + write pitches</label></div>
          </div>
          <div className="flex justify-end"><button className="btn-primary" disabled={form.query.trim().length < 2 || find.isPending} onClick={() => find.mutate()}>{find.isPending ? <><Spinner /> Searching…</> : <><Search className="h-4 w-4" /> Find prospects</>}</button></div>
        </div>
      )}
    </Modal>
  )
}

// ------------------------------------------------------------------ add manually
function AddModal({ siteId, open, onClose, onDone }: { siteId: number; open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const empty = { company: '', website_url: '', contact_name: '', email: '', phone: '', category: '', location: '' }
  const [form, setForm] = useState(empty)
  const add = useMutation({
    mutationFn: () => Leads.create(siteId, form),
    onSuccess: () => { toast.push('success', 'Lead added – auditing in the background'); setForm(empty); onDone(); onClose() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  return (
    <Modal open={open} onClose={onClose} title="Add a lead">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><label className="label">Company *</label><input className="input" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} autoFocus /></div>
        <div className="sm:col-span-2"><label className="label">Website</label><input className="input" placeholder="example.in" value={form.website_url} onChange={(e) => setForm({ ...form, website_url: e.target.value })} /></div>
        <div><label className="label">Contact name</label><input className="input" value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} /></div>
        <div><label className="label">Phone</label><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
        <div><label className="label">Email</label><input className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
        <div><label className="label">Category</label><input className="input" placeholder="e.g. Dentist" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></div>
        <div className="sm:col-span-2"><label className="label">Location</label><input className="input" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
      </div>
      <div className="mt-4 flex justify-end gap-2"><button className="btn-secondary" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!form.company.trim() || add.isPending} onClick={() => add.mutate()}>{add.isPending ? <Spinner /> : <Plus className="h-4 w-4" />} Add & audit</button></div>
    </Modal>
  )
}

// ------------------------------------------------------------------ lead drawer
interface DrawerProps { siteId: number; leadId: number | null; onClose: () => void; onChanged: () => void }

/** Remounts the drawer body per lead (`key`) so tab/edit/note state resets without effects. */
function LeadDrawer({ leadId, ...rest }: DrawerProps) {
  if (leadId == null) return null
  return <LeadDrawerBody key={leadId} leadId={leadId} {...rest} />
}

function LeadDrawerBody({ siteId, leadId, onClose, onChanged }: DrawerProps & { leadId: number }) {
  const toast = useToast()
  const qc = useQueryClient()
  const lead = useQuery({ queryKey: ['lead', siteId, leadId], queryFn: () => Leads.get(siteId, leadId), refetchInterval: (q) => (q.state.data && !q.state.data.qualified_at && !q.state.data.qualify_error ? 3000 : false) })
  const [tab, setTab] = useState<'pitch' | 'audit' | 'activity'>('pitch')
  const [note, setNote] = useState('')
  const [tone, setTone] = useState('friendly')
  const [edit, setEdit] = useState<Partial<Lead> | null>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const refresh = (l: Lead) => { qc.setQueryData(['lead', siteId, l.id], l); onChanged() }
  const status = useMutation({ mutationFn: ({ s, days }: { s: LeadStatus; days?: number }) => Leads.setStatus(siteId, leadId, s, '', days), onSuccess: refresh, onError: (e) => toast.push('error', errorMessage(e)) })
  const qualify = useMutation({ mutationFn: () => Leads.qualify(siteId, leadId), onSuccess: (l) => { refresh(l); toast.push('success', 'Website audited') }, onError: (e) => toast.push('error', errorMessage(e)) })
  const pitch = useMutation({ mutationFn: () => Leads.pitch(siteId, leadId, tone), onSuccess: (l) => { refresh(l); toast.push('success', 'Pitch rewritten') }, onError: (e) => toast.push('error', errorMessage(e)) })
  const update = useMutation({ mutationFn: (p: Partial<Lead> & { activity_note?: string }) => Leads.update(siteId, leadId, p), onSuccess: (l) => { refresh(l); setEdit(null); setNote('') }, onError: (e) => toast.push('error', errorMessage(e)) })
  const remove = useMutation({ mutationFn: () => Leads.remove(siteId, leadId), onSuccess: () => { onChanged(); onClose() } })
  const copy = async (text: string, what: string) => { try { await navigator.clipboard.writeText(text); toast.push('success', `${what} copied`) } catch { toast.push('error', 'Copy failed') } }

  const l = lead.data
  const followUpDue = !!l?.next_follow_up_at && new Date(l.next_follow_up_at).getTime() <= lead.dataUpdatedAt
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40" onMouseDown={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col overflow-y-auto bg-white shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        {!l ? <div className="flex flex-1 items-center justify-center"><Spinner className="h-6 w-6 text-brand-600" /></div> : (
          <>
            <div className="border-b border-slate-100 p-5">
              <div className="flex items-start gap-4">
                <ScoreRing value={l.score} size={72} stroke={7} label="opportunity" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h2 className="text-lg font-semibold text-slate-900">{l.company}</h2>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                        {l.category && <span>{l.category}</span>}
                        {l.location && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{l.location}</span>}
                        {l.rating != null && <span className="inline-flex items-center gap-1"><Star className="h-3 w-3 text-amber-500" />{l.rating} ({l.reviews ?? 0} reviews)</span>}
                        <span className="badge bg-slate-100 text-slate-500">{l.source}</span>
                      </div>
                    </div>
                    <button className="rounded-lg p-1 text-slate-400 hover:bg-slate-100" onClick={onClose}><X className="h-5 w-5" /></button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {l.website_url ? <a href={l.website_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline"><Globe className="h-3 w-3" />{l.website_url.replace(/^https?:\/\//, '')}<ExternalLink className="h-3 w-3" /></a> : <span className="inline-flex items-center gap-1 text-amber-600"><AlertTriangle className="h-3 w-3" /> No website</span>}
                    {l.phone && <a href={`tel:${l.phone}`} className="inline-flex items-center gap-1 text-slate-600"><Phone className="h-3 w-3" />{l.phone}</a>}
                    {l.email && <a href={`mailto:${l.email}`} className="text-slate-600">{l.email}</a>}
                    {l.contact_name && <span className="text-slate-600">👤 {l.contact_name}</span>}
                    <button className="text-slate-400 hover:text-brand-600" onClick={() => setEdit({ contact_name: l.contact_name, email: l.email, phone: l.phone, website_url: l.website_url })}>edit</button>
                  </div>
                  {l.address && <div className="mt-1 text-xs text-slate-400">{l.address}</div>}
                </div>
              </div>
              {edit && (
                <div className="mt-3 grid gap-2 rounded-xl bg-slate-50 p-3 sm:grid-cols-2">
                  <input className="input" placeholder="Contact name" value={edit.contact_name ?? ''} onChange={(e) => setEdit({ ...edit, contact_name: e.target.value })} />
                  <input className="input" placeholder="Email" value={edit.email ?? ''} onChange={(e) => setEdit({ ...edit, email: e.target.value })} />
                  <input className="input" placeholder="Phone" value={edit.phone ?? ''} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} />
                  <input className="input" placeholder="Website" value={edit.website_url ?? ''} onChange={(e) => setEdit({ ...edit, website_url: e.target.value })} />
                  <div className="flex gap-2 sm:col-span-2"><button className="btn-primary px-3 py-1 text-xs" onClick={() => update.mutate(edit)}>Save</button><button className="btn-ghost px-3 py-1 text-xs" onClick={() => setEdit(null)}>Cancel</button></div>
                </div>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-1.5">
                {STATUSES.map((s) => <button key={s.id} onClick={() => status.mutate({ s: s.id })} className={clsx('rounded-full px-3 py-1 text-xs font-medium ring-1 transition', l.status === s.id ? clsx(s.color, 'ring-current') : 'bg-white text-slate-500 ring-slate-200 hover:bg-slate-50')}>{s.label}</button>)}
                <div className="ml-auto flex items-center gap-1 text-xs text-slate-500">
                  <Clock className="h-3 w-3" />
                  {l.next_follow_up_at ? <span className={followUpDue ? 'font-medium text-amber-600' : ''}>follow-up {fmtDate(l.next_follow_up_at, 'dd MMM')}</span> : 'no follow-up'}
                  <select className="input w-auto py-0.5 text-xs" value="" onChange={(e) => { if (e.target.value) status.mutate({ s: l.status, days: Number(e.target.value) }) }}>
                    <option value="">set…</option>{[1, 2, 3, 5, 7, 14, 30].map((d) => <option key={d} value={d}>in {d} day{d > 1 ? 's' : ''}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="flex gap-1 border-b border-slate-100 px-5 pt-3 text-sm">
              {(['pitch', 'audit', 'activity'] as const).map((t) => <button key={t} onClick={() => setTab(t)} className={clsx('rounded-t-lg px-3 py-1.5 font-medium capitalize', tab === t ? 'border-b-2 border-brand-600 text-brand-700' : 'text-slate-500 hover:text-slate-700')}>{t === 'audit' ? 'Website audit' : t}</button>)}
            </div>

            <div className="flex-1 space-y-4 p-5">
              {tab === 'pitch' && (
                !l.qualified_at && !l.qualify_error ? <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Auditing the website and writing the pitch…</div>
                : !l.pitch?.email ? <EmptyState title="No pitch yet" description="Run the audit to generate a personalised pitch." action={<button className="btn-primary" onClick={() => qualify.mutate()} disabled={qualify.isPending}>{qualify.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />} Audit & write pitch</button>} />
                : (
                  <>
                    <div className="rounded-xl border border-brand-100 bg-brand-50/60 p-3 text-sm">
                      <div className="text-[11px] font-semibold uppercase tracking-wide text-brand-700">Angle</div>
                      <div className="font-medium text-slate-800">{l.pitch.angle}</div>
                      {l.pitch.offer && <div className="mt-1 text-xs text-slate-600">Offer: {l.pitch.offer}</div>}
                    </div>
                    <PitchBlock title="Email" subject={l.pitch.email.subject} body={l.pitch.email.body} onCopy={copy} mailto={l.email ? `mailto:${l.email}?subject=${encodeURIComponent(l.pitch.email.subject)}&body=${encodeURIComponent(l.pitch.email.body)}` : undefined} />
                    {l.pitch.whatsapp && <PitchBlock title="WhatsApp / DM" body={l.pitch.whatsapp} onCopy={copy} wa={l.phone ? `https://wa.me/${l.phone.replace(/[^\d]/g, '')}?text=${encodeURIComponent(l.pitch.whatsapp)}` : undefined} />}
                    {(l.pitch.follow_ups ?? []).map((f, i) => <PitchBlock key={i} title={`Follow-up ${i + 1} · day ${f.day} · ${f.channel}`} subject={f.subject || undefined} body={f.body} onCopy={copy} />)}
                    <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-xs">
                      <span className="text-slate-400">Written by {l.pitch.provider ?? 'rule-based'}</span>
                      <select className="input ml-auto w-auto py-1 text-xs" value={tone} onChange={(e) => setTone(e.target.value)}>{['friendly', 'professional', 'bold', 'short & direct'].map((t) => <option key={t}>{t}</option>)}</select>
                      <button className="btn-secondary px-2 py-1 text-xs" onClick={() => pitch.mutate()} disabled={pitch.isPending}>{pitch.isPending ? <Spinner /> : <RefreshCw className="h-3 w-3" />} Rewrite</button>
                      {l.status === 'new' && <button className="btn-primary px-2 py-1 text-xs" onClick={() => status.mutate({ s: 'contacted' })}>Mark as contacted</button>}
                    </div>
                  </>
                )
              )}

              {tab === 'audit' && (
                <>
                  {l.qualify_error && <Alert kind="warning">Could not audit: {l.qualify_error}</Alert>}
                  {l.audit.demo && <Alert kind="info">Sample audit (demo prospect on example.com).</Alert>}
                  {l.audit.gaps?.length ? (
                    <div>
                      <div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-semibold text-slate-800">What's holding them back</h3>{l.website_score != null && <span className="text-sm">Health <b className={scoreColor(l.website_score)}>{l.website_score}</b><span className="text-xs text-slate-400">/100 · {l.audit.pages_crawled ?? 0} pages</span></span>}</div>
                      <ul className="space-y-1.5">{l.audit.gaps.map((g) => <li key={g.code} className="flex items-start gap-2 rounded-lg bg-slate-50 p-2 text-sm"><span className="mt-0.5 w-6 shrink-0 text-center text-xs font-bold text-slate-400">+{g.weight}</span><div><div className="font-medium text-slate-800">{g.label}{g.detail && <span className="font-normal text-slate-500"> · {g.detail}</span>}</div><div className="text-xs text-slate-500">Pitch: {g.pitch}</div></div></li>)}</ul>
                    </div>
                  ) : <p className="text-sm text-slate-500">{l.qualified_at ? 'No significant gaps – a healthy website.' : 'Not audited yet.'}</p>}
                  {l.audit.scores && Object.keys(l.audit.scores).length > 0 && (
                    <div><h3 className="mb-2 text-sm font-semibold text-slate-800">Category scores</h3><div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{Object.entries(l.audit.scores).map(([k, v]) => <div key={k} className="rounded-lg border border-slate-100 p-2 text-center"><div className={clsx('text-lg font-bold', scoreColor(v))}>{Math.round(v)}</div><div className="text-[11px] uppercase tracking-wide text-slate-400">{k}</div></div>)}</div></div>
                  )}
                  <div className="flex items-center gap-2 border-t border-slate-100 pt-3 text-xs"><span className="text-slate-400">{l.qualified_at ? `Audited ${timeAgo(l.qualified_at)}` : ''}</span><button className="btn-secondary ml-auto px-2 py-1 text-xs" onClick={() => qualify.mutate()} disabled={qualify.isPending}>{qualify.isPending ? <Spinner /> : <RefreshCw className="h-3 w-3" />} Re-audit</button></div>
                </>
              )}

              {tab === 'activity' && (
                <>
                  <div className="flex gap-2"><input className="input" placeholder="Add a note (call outcome, next step…)" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && note.trim()) update.mutate({ activity_note: note.trim() }) }} /><button className="btn-secondary" disabled={!note.trim()} onClick={() => update.mutate({ activity_note: note.trim() })}>Add</button></div>
                  <ol className="relative space-y-3 border-l border-slate-200 pl-4">
                    {[...(l.activity ?? [])].reverse().map((a, i) => <li key={i} className="text-sm"><span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-white bg-slate-300" /><div className="text-slate-800">{a.note}</div><div className="text-xs text-slate-400">{a.kind} · {fmtDate(a.at)}</div></li>)}
                  </ol>
                  {l.notes && <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-500">{l.notes}</div>}
                </>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 p-4 text-xs text-slate-400">
              <span>Added {timeAgo(l.created_at)}{l.search_query ? ` · search “${l.search_query}”` : ''}</span>
              <button className="btn-ghost px-2 py-1 text-xs text-red-600 hover:bg-red-50" onClick={() => remove.mutate()}><Trash2 className="h-3 w-3" /> Delete</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function PitchBlock({ title, subject, body, onCopy, mailto, wa }: { title: string; subject?: string; body: string; onCopy: (t: string, w: string) => void; mailto?: string; wa?: string }) {
  return (
    <div className="rounded-xl border border-slate-200">
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 text-xs">
        <span className="font-semibold text-slate-700">{title}</span>
        <div className="ml-auto flex gap-1">
          {mailto && <a href={mailto} className="btn-ghost px-2 py-0.5 text-xs">Open in mail</a>}
          {wa && <a href={wa} target="_blank" rel="noreferrer" className="btn-ghost px-2 py-0.5 text-xs">Open WhatsApp</a>}
          <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => onCopy(subject ? `Subject: ${subject}\n\n${body}` : body, title)}><Copy className="h-3 w-3" /> Copy</button>
        </div>
      </div>
      {subject && <div className="px-3 pt-2 text-sm font-medium text-slate-800">{subject}</div>}
      <pre className="whitespace-pre-wrap px-3 py-2 font-sans text-sm text-slate-700">{body}</pre>
    </div>
  )
}
