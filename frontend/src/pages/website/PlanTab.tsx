import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarRange, Check, CheckCircle2, Circle, Plus, Sparkles, Trash2, Undo2, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Modal, Spinner } from '../../components/ui'
import { useToast } from '../../hooks/useToast'
import { Tasks, errorMessage, type Task } from '../../lib/api'
import { categoryLabels, fmtDate, priorityStyles } from '../../lib/utils'
import { useSite } from '../../hooks/useSite'

const COLUMNS: { key: Task['status']; label: string }[] = [
  { key: 'todo', label: 'To do' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'done', label: 'Done' },
]

export default function PlanTab() {
  const { site } = useSite()
  const qc = useQueryClient()
  const toast = useToast()
  const tasks = useQuery({ queryKey: ['tasks', site.id], queryFn: () => Tasks.list(site.id) })
  const [planOpen, setPlanOpen] = useState(false)
  const [weeks, setWeeks] = useState(4)
  const [focus, setFocus] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState<{ title: string; description: string; category: string; priority: Task['priority'] }>({ title: '', description: '', category: 'seo', priority: 'medium' })
  const [showDismissed, setShowDismissed] = useState(false)

  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['tasks', site.id] }); void qc.invalidateQueries({ queryKey: ['dashboard'] }) }
  const update = useMutation({ mutationFn: ({ id, ...p }: { id: number } & Partial<Task>) => Tasks.update(site.id, id, p), onSuccess: invalidate, onError: (e) => toast.push('error', errorMessage(e)) })
  const remove = useMutation({ mutationFn: (id: number) => Tasks.remove(site.id, id), onSuccess: invalidate })
  const create = useMutation({
    mutationFn: () => Tasks.create(site.id, form),
    onSuccess: () => { invalidate(); setAddOpen(false); setForm({ title: '', description: '', category: 'seo', priority: 'medium' }) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const plan = useMutation({
    mutationFn: () => Tasks.plan(site.id, weeks, focus),
    onSuccess: (r) => { toast.push('success', `Plan generated: ${r.created_tasks} new tasks added`); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })

  const all = tasks.data ?? []
  const byStatus = (s: Task['status']) => all.filter((t) => t.status === s)
  const dismissed = byStatus('dismissed')

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={() => setPlanOpen(true)}><Sparkles className="h-4 w-4" /> Generate action plan</button>
        <button className="btn-secondary" onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add task</button>
        <span className="ml-auto text-xs text-slate-400">{byStatus('todo').length + byStatus('in_progress').length} open · {byStatus('done').length} done</span>
      </div>

      {plan.data && (
        <div className="card mb-4 p-5">
          <div className="mb-2 flex items-center gap-2"><CalendarRange className="h-4 w-4 text-brand-600" /><h2 className="font-semibold text-slate-900">{weeks}-week strategy</h2><span className="badge bg-slate-100 text-slate-500">{plan.data.provider}</span></div>
          <p className="mb-3 text-sm text-slate-700">{plan.data.strategy_summary}</p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {plan.data.weeks.map((w) => (
              <div key={w.week} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-brand-700">Week {w.week}</div>
                <div className="text-sm font-medium text-slate-800">{w.theme}</div>
                <ul className="mt-2 space-y-1 text-xs text-slate-600">{w.tasks.map((t, i) => <li key={i}>• {t.title}</li>)}</ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {tasks.isLoading ? <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-brand-600" /></div> : (
        <div className="grid gap-4 lg:grid-cols-3">
          {COLUMNS.map((col) => (
            <div key={col.key} className="rounded-2xl bg-slate-100/70 p-3">
              <div className="mb-2 flex items-center justify-between px-1"><h3 className="text-sm font-semibold text-slate-700">{col.label}</h3><span className="text-xs text-slate-400">{byStatus(col.key).length}</span></div>
              <div className="space-y-2">
                {byStatus(col.key).length === 0 && <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">Nothing here</div>}
                {byStatus(col.key).map((t) => (
                  <TaskCard key={t.id} t={t} onStatus={(status) => update.mutate({ id: t.id, status })} onDelete={() => remove.mutate(t.id)} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {dismissed.length > 0 && (
        <div className="mt-4 text-xs text-slate-400">
          <button className="underline" onClick={() => setShowDismissed(!showDismissed)}>{showDismissed ? 'Hide' : 'Show'} {dismissed.length} dismissed</button>
          {showDismissed && <div className="mt-2 grid gap-2 md:grid-cols-3">{dismissed.map((t) => <TaskCard key={t.id} t={t} onStatus={(status) => update.mutate({ id: t.id, status })} onDelete={() => remove.mutate(t.id)} />)}</div>}
        </div>
      )}

      <Modal open={planOpen} onClose={() => setPlanOpen(false)} title="Generate an action plan">
        <div className="space-y-4">
          <p className="text-sm text-slate-600">Builds a week-by-week plan from the latest audit, your keywords and business context, and adds the steps as tasks.</p>
          <div><label className="label">Horizon</label>
            <div className="flex gap-2">{[2, 4, 8, 12].map((w) => <button key={w} className={clsx('btn', weeks === w ? 'bg-brand-600 text-white' : 'border border-slate-200 bg-white text-slate-700')} onClick={() => setWeeks(w)}>{w} weeks</button>)}</div>
          </div>
          <div><label className="label">Main goal (optional)</label><input className="input" placeholder="e.g. rank #1 for 'dentist in delhi', get more leads from Instagram" value={focus} onChange={(e) => setFocus(e.target.value)} /></div>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setPlanOpen(false)}>Cancel</button><button className="btn-primary" disabled={plan.isPending} onClick={() => plan.mutate(undefined, { onSuccess: () => setPlanOpen(false) })}>{plan.isPending && <Spinner />} Generate</button></div>
        </div>
      </Modal>

      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add a task">
        <div className="space-y-4">
          <div><label className="label">Title</label><input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus /></div>
          <div><label className="label">Details</label><textarea className="input min-h-20" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">Category</label><select className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{Object.entries(categoryLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
            <div><label className="label">Priority</label><select className="input" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as Task['priority'] })}>{['low', 'medium', 'high', 'critical'].map((p) => <option key={p}>{p}</option>)}</select></div>
          </div>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setAddOpen(false)}>Cancel</button><button className="btn-primary" disabled={!form.title.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending && <Spinner />} Add</button></div>
        </div>
      </Modal>
    </div>
  )
}

function TaskCard({ t, onStatus, onDelete }: { t: Task; onStatus: (s: Task['status']) => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={clsx('card p-3 text-sm', t.status === 'done' && 'opacity-70')}>
      <div className="flex items-start gap-2">
        <button className="mt-0.5 text-slate-400 hover:text-brand-600" onClick={() => onStatus(t.status === 'done' ? 'todo' : 'done')} title={t.status === 'done' ? 'Reopen' : 'Mark done'}>
          {t.status === 'done' ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <Circle className="h-4 w-4" />}
        </button>
        <div className="min-w-0 flex-1 cursor-pointer" onClick={() => setOpen(!open)}>
          <div className={clsx('font-medium text-slate-800', t.status === 'done' && 'line-through')}>{t.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
            <span className={clsx('badge', priorityStyles[t.priority])}>{t.priority}</span>
            <span>{categoryLabels[t.category] ?? t.category}</span>
            <span>· {t.source === 'audit' ? 'from audit' : t.source === 'ai' ? 'from plan' : 'manual'}</span>
            {t.due_date && <span>· due {fmtDate(t.due_date, 'dd MMM')}</span>}
          </div>
          {open && (
            <div className="mt-2 space-y-1 text-xs text-slate-600">
              {t.description && <p className="whitespace-pre-line">{t.description}</p>}
              {t.page_url && <a href={t.page_url} target="_blank" rel="noreferrer" className="block truncate text-brand-600 hover:underline">{t.page_url}</a>}
            </div>
          )}
        </div>
      </div>
      {open && (
        <div className="mt-2 flex flex-wrap gap-1 border-t border-slate-100 pt-2">
          {t.status !== 'in_progress' && t.status !== 'done' && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => onStatus('in_progress')}><Check className="h-3 w-3" /> Start</button>}
          {t.status !== 'done' && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => onStatus('done')}><CheckCircle2 className="h-3 w-3" /> Done</button>}
          {t.status === 'done' && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => onStatus('todo')}><Undo2 className="h-3 w-3" /> Reopen</button>}
          {t.status !== 'dismissed' ? <button className="btn-ghost px-2 py-1 text-xs" onClick={() => onStatus('dismissed')}><XCircle className="h-3 w-3" /> Dismiss</button> : <button className="btn-ghost px-2 py-1 text-xs" onClick={() => onStatus('todo')}><Undo2 className="h-3 w-3" /> Restore</button>}
          <button className="btn-ghost ml-auto px-2 py-1 text-xs text-red-600" onClick={onDelete}><Trash2 className="h-3 w-3" /> Delete</button>
        </div>
      )}
    </div>
  )
}
