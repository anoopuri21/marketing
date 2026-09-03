import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Eye, Mail, Plus, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Alert, Modal, Spinner, useToast } from '../../components/ui'
import { Reports, System, errorMessage, type ReportSchedule } from '../../lib/api'
import { fmtDate, fmtDateTz, pad, weekdays } from '../../lib/utils'
import { useSite } from './WebsiteLayout'

type Form = Omit<ReportSchedule, 'id' | 'website_id' | 'next_run_at' | 'last_run_at' | 'created_at'>
const defaultForm = (): Form => ({
  recipients: [], frequency: 'weekly', day_of_week: 0, day_of_month: 1, hour: 9, minute: 0,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata', enabled: true, run_fresh_audit: true,
})

export default function ReportsTab() {
  const { site } = useSite()
  const qc = useQueryClient()
  const toast = useToast()
  const schedules = useQuery({ queryKey: ['schedules', site.id], queryFn: () => Reports.schedules(site.id) })
  const runs = useQuery({ queryKey: ['report-runs', site.id], queryFn: () => Reports.runs(site.id) })
  const status = useQuery({ queryKey: ['system'], queryFn: System.status, staleTime: 60_000 })
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<Form>(defaultForm())
  const [recipientsRaw, setRecipientsRaw] = useState('')
  const [sendOpen, setSendOpen] = useState(false)
  const [sendTo, setSendTo] = useState('')
  const [sendPeriod, setSendPeriod] = useState<'weekly' | 'monthly'>('weekly')
  const [sendFresh, setSendFresh] = useState(false)

  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['schedules', site.id] }); void qc.invalidateQueries({ queryKey: ['report-runs', site.id] }); void qc.invalidateQueries({ queryKey: ['dashboard'] }) }
  const parseEmails = (raw: string) => raw.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean)

  const create = useMutation({
    mutationFn: () => Reports.createSchedule(site.id, { ...form, recipients: parseEmails(recipientsRaw) }),
    onSuccess: () => { toast.push('success', 'Schedule created'); invalidate(); setOpen(false); setForm(defaultForm()); setRecipientsRaw('') },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const toggle = useMutation({ mutationFn: (s: ReportSchedule) => Reports.updateSchedule(site.id, s.id, { enabled: !s.enabled }), onSuccess: invalidate })
  const remove = useMutation({ mutationFn: (id: number) => Reports.deleteSchedule(site.id, id), onSuccess: invalidate })
  const sendNow = useMutation({
    mutationFn: () => Reports.sendNow(site.id, { recipients: parseEmails(sendTo).length ? parseEmails(sendTo) : undefined, period: sendPeriod, run_fresh_audit: sendFresh }),
    onSuccess: (r) => { toast.push(r.status === 'sent' ? 'success' : 'error', r.status === 'sent' ? r.delivery_info : r.error); invalidate(); setSendOpen(false) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })

  const emailBackend = status.data?.email_backend

  return (
    <div className="space-y-6">
      {emailBackend && emailBackend !== 'smtp' && (
        <Alert kind="warning">
          Email delivery is in <b>{emailBackend}</b> mode — reports are generated and saved to the server outbox instead of being emailed. Add <code className="rounded bg-amber-100 px-1">SMTP_HOST / SMTP_USER / SMTP_PASSWORD</code> to the backend <code className="rounded bg-amber-100 px-1">.env</code> to deliver to client inboxes.
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New schedule</button>
        <button className="btn-secondary" onClick={() => setSendOpen(true)}><Send className="h-4 w-4" /> Send report now</button>
        <a className="btn-secondary" href={Reports.previewUrl(site.id, 'weekly')} target="_blank" rel="noreferrer" onClick={(e) => { e.preventDefault(); openPreview(site.id, 'weekly') }}><Eye className="h-4 w-4" /> Preview weekly</a>
        <a className="btn-secondary" href={Reports.previewUrl(site.id, 'monthly')} onClick={(e) => { e.preventDefault(); openPreview(site.id, 'monthly') }}><Eye className="h-4 w-4" /> Preview monthly</a>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Schedules</h2>
        {schedules.isLoading ? <Spinner /> : (schedules.data ?? []).length === 0 ? (
          <div className="card p-8 text-center text-sm text-slate-500">No schedules. Create one to email clients automatically every week or month.</div>
        ) : (
          <div className="card divide-y divide-slate-100">
            {schedules.data!.map((s) => (
              <div key={s.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><Mail className="h-4 w-4" /></div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-800">
                    {s.frequency === 'weekly' ? `Every ${weekdays[s.day_of_week]}` : `Monthly on day ${s.day_of_month}`} at {pad(s.hour)}:{pad(s.minute)} <span className="text-slate-400">({s.timezone})</span>
                    {s.run_fresh_audit && <span className="badge ml-2 bg-slate-100 text-slate-500">fresh audit first</span>}
                  </div>
                  <div className="truncate text-xs text-slate-500">To: {s.recipients.join(', ')}</div>
                  <div className="text-xs text-slate-400">Next: {fmtDateTz(s.next_run_at, s.timezone)} · Last: {fmtDateTz(s.last_run_at, s.timezone)} <span className="text-slate-300">({s.timezone})</span></div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => toggle.mutate(s)} className={clsx('badge px-3 py-1 text-xs', s.enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500')}>{s.enabled ? 'enabled' : 'paused'}</button>
                  <button className="rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => remove.mutate(s.id)}><Trash2 className="h-4 w-4" /></button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Sent reports</h2>
        {runs.isLoading ? <Spinner /> : (runs.data ?? []).length === 0 ? (
          <div className="card p-8 text-center text-sm text-slate-500">No reports sent yet.</div>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-2">When</th><th className="px-3 py-2">Period</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Recipients</th><th className="px-3 py-2">Delivery</th><th className="px-3 py-2"></th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {runs.data!.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 text-slate-600">{fmtDate(r.created_at)}</td>
                    <td className="px-3 py-2 text-slate-600">{r.period_label}</td>
                    <td className="px-3 py-2"><span className={clsx('badge', r.status === 'sent' ? 'bg-emerald-100 text-emerald-700' : r.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700')}>{r.status}</span></td>
                    <td className="max-w-[12rem] truncate px-3 py-2 text-xs text-slate-500">{r.recipients.join(', ')}</td>
                    <td className="max-w-[16rem] truncate px-3 py-2 text-xs text-slate-500" title={r.delivery_info || r.error}>{r.delivery_info || r.error}</td>
                    <td className="px-3 py-2 text-right"><button className="btn-ghost px-2 py-1 text-xs" onClick={() => openRun(site.id, r.id)}><Eye className="h-3 w-3" /> View</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="New report schedule">
        <div className="space-y-4">
          <div><label className="label">Recipient emails (comma or newline separated)</label><textarea className="input min-h-20" placeholder="client@company.com, owner@company.com" value={recipientsRaw} onChange={(e) => setRecipientsRaw(e.target.value)} autoFocus /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">Frequency</label><select className="input" value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as Form['frequency'] })}><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div>
            {form.frequency === 'weekly' ? (
              <div><label className="label">Day</label><select className="input" value={form.day_of_week} onChange={(e) => setForm({ ...form, day_of_week: Number(e.target.value) })}>{weekdays.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></div>
            ) : (
              <div><label className="label">Day of month</label><select className="input" value={form.day_of_month} onChange={(e) => setForm({ ...form, day_of_month: Number(e.target.value) })}>{Array.from({ length: 28 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}</select></div>
            )}
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><label className="label">Hour</label><select className="input" value={form.hour} onChange={(e) => setForm({ ...form, hour: Number(e.target.value) })}>{Array.from({ length: 24 }, (_, i) => i).map((h) => <option key={h} value={h}>{pad(h)}</option>)}</select></div>
            <div><label className="label">Minute</label><select className="input" value={form.minute} onChange={(e) => setForm({ ...form, minute: Number(e.target.value) })}>{[0, 15, 30, 45].map((m) => <option key={m} value={m}>{pad(m)}</option>)}</select></div>
            <div><label className="label">Timezone</label><input className="input" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} /></div>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={form.run_fresh_audit} onChange={(e) => setForm({ ...form, run_fresh_audit: e.target.checked })} /> Run a fresh audit right before sending</label>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setOpen(false)}>Cancel</button><button className="btn-primary" disabled={create.isPending || parseEmails(recipientsRaw).length === 0} onClick={() => create.mutate()}>{create.isPending && <Spinner />} Create schedule</button></div>
        </div>
      </Modal>

      <Modal open={sendOpen} onClose={() => setSendOpen(false)} title="Send a report now">
        <div className="space-y-4">
          <div><label className="label">Recipients (blank = use schedule recipients)</label><input className="input" placeholder="client@company.com" value={sendTo} onChange={(e) => setSendTo(e.target.value)} /></div>
          <div><label className="label">Period</label><select className="input" value={sendPeriod} onChange={(e) => setSendPeriod(e.target.value as 'weekly' | 'monthly')}><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></div>
          <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={sendFresh} onChange={(e) => setSendFresh(e.target.checked)} /> Run a fresh audit first (takes ~30-60s)</label>
          <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setSendOpen(false)}>Cancel</button><button className="btn-primary" disabled={sendNow.isPending} onClick={() => sendNow.mutate()}>{sendNow.isPending ? <Spinner /> : <Send className="h-4 w-4" />} Send</button></div>
        </div>
      </Modal>
    </div>
  )
}

async function fetchHtml(url: string): Promise<string> {
  const token = localStorage.getItem('rankpilot_token')
  const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  return res.text()
}

function showHtml(html: string) {
  const w = window.open('', '_blank')
  if (!w) return
  w.document.open()
  w.document.write(html)
  w.document.close()
}

function openPreview(siteId: number, period: 'weekly' | 'monthly') {
  void fetchHtml(Reports.previewUrl(siteId, period)).then(showHtml)
}

function openRun(siteId: number, runId: number) {
  void fetchHtml(Reports.runHtmlUrl(siteId, runId)).then(showHtml)
}
