import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowDownRight, ArrowUpRight, Minus, Plus, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Alert, Modal, Spinner, useToast } from '../../components/ui'
import { Keywords, System, errorMessage } from '../../lib/api'
import { timeAgo } from '../../lib/utils'
import { useSite } from './WebsiteLayout'

export default function KeywordsTab() {
  const { site } = useSite()
  const qc = useQueryClient()
  const toast = useToast()
  const kws = useQuery({ queryKey: ['keywords', site.id], queryFn: () => Keywords.list(site.id) })
  const status = useQuery({ queryKey: ['system'], queryFn: System.status, staleTime: 60_000 })
  const [addOpen, setAddOpen] = useState(false)
  const [raw, setRaw] = useState('')
  const [location, setLocation] = useState(site.target_location || '')
  const [suggestOpen, setSuggestOpen] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['keywords', site.id] })
    void qc.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const add = useMutation({
    mutationFn: (terms: string[]) => Keywords.add(site.id, terms, location),
    onSuccess: (r) => { toast.push('success', `${r.length} keyword(s) added`); invalidate(); setAddOpen(false); setSuggestOpen(false); setRaw(''); setPicked(new Set()) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const remove = useMutation({ mutationFn: (id: number) => Keywords.remove(site.id, id), onSuccess: invalidate })
  const check = useMutation({
    mutationFn: () => Keywords.checkAll(site.id),
    onSuccess: () => { toast.push('success', 'Rank check complete'); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const suggest = useMutation({ mutationFn: () => Keywords.suggest(site.id), onSuccess: () => setSuggestOpen(true), onError: (e) => toast.push('error', errorMessage(e)) })

  const list = kws.data ?? []
  const noSerp = status.data?.serp_provider === 'none'

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add keywords</button>
        <button className="btn-secondary" onClick={() => suggest.mutate()} disabled={suggest.isPending}>{suggest.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />} Suggest keywords</button>
        <button className="btn-secondary" onClick={() => check.mutate()} disabled={check.isPending || list.length === 0}>{check.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Check rankings now</button>
      </div>

      {noSerp && (
        <div className="mb-4">
          <Alert kind="warning">
            Live Google positions need a SERP data provider. Set <code className="rounded bg-amber-100 px-1">SERPAPI_KEY</code> in the backend <code className="rounded bg-amber-100 px-1">.env</code> and restart — keywords you add now will start populating automatically.
          </Alert>
        </div>
      )}

      {kws.isLoading ? <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-brand-600" /></div> : list.length === 0 ? (
        <div className="card p-10 text-center text-sm text-slate-500">No keywords tracked yet. Add the searches your customers type into Google.</div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">Keyword</th><th className="px-3 py-2">Location</th><th className="px-3 py-2 text-right">Position</th><th className="px-3 py-2 text-right">Change</th><th className="px-3 py-2">Ranking URL</th><th className="px-3 py-2">Checked</th><th className="px-3 py-2"></th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {list.map((k) => {
                const change = k.latest_position && k.previous_position ? k.previous_position - k.latest_position : null
                return (
                  <tr key={k.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium text-slate-800">{k.term}</td>
                    <td className="px-3 py-2 text-slate-500">{k.location || <span className="text-slate-300">global</span>}</td>
                    <td className="px-3 py-2 text-right font-bold text-slate-800">{k.latest_position ?? (k.last_checked_at ? <span className="text-slate-400">100+</span> : <span className="text-slate-300">–</span>)}</td>
                    <td className={clsx('px-3 py-2 text-right font-semibold', change === null ? 'text-slate-300' : change > 0 ? 'text-emerald-600' : change < 0 ? 'text-red-600' : 'text-slate-400')}>
                      <span className="inline-flex items-center gap-0.5">{change === null ? '–' : change > 0 ? <><ArrowUpRight className="h-3.5 w-3.5" />{change}</> : change < 0 ? <><ArrowDownRight className="h-3.5 w-3.5" />{-change}</> : <Minus className="h-3.5 w-3.5" />}</span>
                    </td>
                    <td className="max-w-[14rem] truncate px-3 py-2 text-xs text-brand-600">{k.latest_url ? <a href={k.latest_url} target="_blank" rel="noreferrer" className="hover:underline">{k.latest_url.replace(/^https?:\/\//, '')}</a> : <span className="text-slate-300">–</span>}</td>
                    <td className="px-3 py-2 text-xs text-slate-400">{k.last_checked_at ? timeAgo(k.last_checked_at) : 'never'}</td>
                    <td className="px-3 py-2 text-right"><button className="rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => remove.mutate(k.id)} title="Remove"><Trash2 className="h-4 w-4" /></button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add keywords">
        <div className="space-y-4">
          <div><label className="label">Keywords (one per line)</label><textarea className="input min-h-32" placeholder={'best dentist in delhi\nteeth whitening cost\ndental implant near me'} value={raw} onChange={(e) => setRaw(e.target.value)} autoFocus /></div>
          <div><label className="label">Location (optional)</label><input className="input" placeholder="Delhi, India" value={location} onChange={(e) => setLocation(e.target.value)} /></div>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setAddOpen(false)}>Cancel</button><button className="btn-primary" disabled={add.isPending || !raw.trim()} onClick={() => add.mutate(raw.split('\n').map((s) => s.trim()).filter(Boolean))}>{add.isPending && <Spinner />} Add</button></div>
        </div>
      </Modal>

      <Modal open={suggestOpen} onClose={() => setSuggestOpen(false)} title="Suggested keywords" wide>
        {suggest.data && (
          <div className="space-y-4">
            <p className="text-xs text-slate-500">Source: {suggest.data.provider === 'rule-based' ? 'rule-based (configure an AI key for smarter suggestions)' : `AI · ${suggest.data.provider}`}. Select the ones to track.</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {suggest.data.suggestions.map((s) => {
                const on = picked.has(s.term)
                return (
                  <button key={s.term} onClick={() => { const n = new Set(picked); if (on) n.delete(s.term); else n.add(s.term); setPicked(n) }}
                    className={clsx('rounded-xl border px-3 py-2 text-left text-sm transition', on ? 'border-brand-500 bg-brand-50' : 'border-slate-200 hover:border-slate-300')}>
                    <div className="font-medium text-slate-800">{s.term}</div>
                    <div className="text-xs text-slate-500">{s.intent}{s.reason ? ` · ${s.reason}` : ''}</div>
                  </button>
                )
              })}
            </div>
            <div className="flex items-center justify-between">
              <button className="btn-ghost" onClick={() => setPicked(new Set(suggest.data!.suggestions.map((s) => s.term)))}>Select all</button>
              <button className="btn-primary" disabled={picked.size === 0 || add.isPending} onClick={() => add.mutate([...picked])}>{add.isPending && <Spinner />} Track {picked.size} keyword(s)</button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
