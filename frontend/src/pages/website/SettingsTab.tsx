import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Check, Copy, Plug, ShieldCheck, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert, Modal, Spinner } from '../../components/ui'
import { useToast } from '../../hooks/useToast'
import { Integrations, Websites, errorMessage } from '../../lib/api'
import { timeAgo } from '../../lib/utils'
import { useSite } from '../../hooks/useSite'

export default function SettingsTab() {
  const { site } = useSite()
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: site.name, industry: site.industry, target_location: site.target_location, description: site.description, auto_audit_enabled: site.auto_audit_enabled })
  const [verifyMsg, setVerifyMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const verification = useQuery({ queryKey: ['verification', site.id], queryFn: () => Websites.verification(site.id) })
  const catalog = useQuery({ queryKey: ['integrations-catalog'], queryFn: Integrations.catalog, staleTime: Infinity })
  const integrations = useQuery({ queryKey: ['integrations', site.id], queryFn: () => Integrations.list(site.id) })
  const [intOpen, setIntOpen] = useState<string | null>(null)
  const [intForm, setIntForm] = useState<Record<string, string>>({})

  const save = useMutation({
    mutationFn: () => Websites.update(site.id, form),
    onSuccess: () => { toast.push('success', 'Saved'); void qc.invalidateQueries({ queryKey: ['website', site.id] }); void qc.invalidateQueries({ queryKey: ['websites'] }) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const verify = useMutation({
    mutationFn: () => Websites.verify(site.id, 'auto'),
    onSuccess: (r) => { setVerifyMsg({ ok: r.verified, text: r.detail }); if (r.verified) { void qc.invalidateQueries({ queryKey: ['website', site.id] }); void qc.invalidateQueries({ queryKey: ['websites'] }) } },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: () => Websites.remove(site.id),
    onSuccess: () => { toast.push('success', 'Website removed'); void qc.invalidateQueries({ queryKey: ['websites'] }); navigate('/') },
  })
  const upsertInt = useMutation({
    mutationFn: () => Integrations.upsert(site.id, intOpen!, intForm),
    onSuccess: () => { toast.push('success', 'Integration saved'); void qc.invalidateQueries({ queryKey: ['integrations', site.id] }); setIntOpen(null); setIntForm({}) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const removeInt = useMutation({ mutationFn: (p: string) => Integrations.remove(site.id, p), onSuccess: () => void qc.invalidateQueries({ queryKey: ['integrations', site.id] }) })

  const copy = (text: string) => { void navigator.clipboard.writeText(text); toast.push('success', 'Copied to clipboard') }
  const v = verification.data

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="card p-5">
        <h2 className="mb-4 font-semibold text-slate-900">Business profile</h2>
        <div className="space-y-3">
          <div><label className="label">Name</label><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">Industry</label><input className="input" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></div>
            <div><label className="label">Target location</label><input className="input" value={form.target_location} onChange={(e) => setForm({ ...form, target_location: e.target.value })} /></div>
          </div>
          <div><label className="label">Description</label><textarea className="input min-h-24" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={form.auto_audit_enabled} onChange={(e) => setForm({ ...form, auto_audit_enabled: e.target.checked })} /> Automatic weekly audits</label>
          <div className="flex justify-end"><button className="btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending && <Spinner />} Save</button></div>
        </div>
      </div>

      <div className="card p-5">
        <div className="mb-1 flex items-center gap-2"><ShieldCheck className={clsx('h-5 w-5', site.verified ? 'text-emerald-500' : 'text-slate-400')} /><h2 className="font-semibold text-slate-900">Ownership verification</h2></div>
        {site.verified ? (
          <Alert kind="success">Verified via {site.verification_method}. Full automation is enabled for this site.</Alert>
        ) : (
          <>
            <p className="mb-3 text-sm text-slate-500">Prove you control this site with <b>any one</b> of the methods below, then click Verify.</p>
            {v && (
              <div className="space-y-3 text-sm">
                <Method title="1. HTML meta tag" desc="Add inside <head> of your homepage:" code={v.meta_tag} onCopy={copy} />
                <Method title="2. HTML file" desc={`Upload a file named ${v.html_file_name} to the site root containing:`} code={v.html_file_content} onCopy={copy} extra={v.html_file_url} />
                <Method title="3. DNS TXT record" desc="Add a TXT record on your domain with this value:" code={v.dns_record} onCopy={copy} />
              </div>
            )}
            <div className="mt-4 flex items-center gap-3">
              <button className="btn-primary" disabled={verify.isPending} onClick={() => verify.mutate()}>{verify.isPending ? <Spinner /> : <Check className="h-4 w-4" />} Verify now</button>
              {verifyMsg && <span className={clsx('text-sm', verifyMsg.ok ? 'text-emerald-600' : 'text-red-600')}>{verifyMsg.text}</span>}
            </div>
          </>
        )}
      </div>

      <div className="card p-5 lg:col-span-2">
        <div className="mb-1 flex items-center gap-2"><Plug className="h-5 w-5 text-brand-600" /><h2 className="font-semibold text-slate-900">Integrations</h2></div>
        <p className="mb-4 text-sm text-slate-500">Google Search Console and GA4 sync live data (daily + before every report) – set them up in the <Link to="../google" className="text-brand-600 hover:underline">Google data</Link> tab. Social publishing credentials are stored here for the upcoming publishing module.</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {catalog.data && Object.entries(catalog.data).map(([key, meta]) => {
            const row = integrations.data?.find((i) => i.provider === key)
            const live = meta.status === 'live'
            const statusLabel = !row ? 'not connected' : row.status === 'connected' ? (row.last_synced_at ? `connected · synced ${timeAgo(row.last_synced_at)}` : 'connected') : row.status === 'error' ? 'needs attention' : row.status === 'pending' ? 'pending' : 'incomplete'
            return (
              <div key={key} className={clsx('flex items-center justify-between rounded-xl border p-3', row?.status === 'error' ? 'border-red-200' : 'border-slate-200')}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium text-slate-800">{meta.label}{!live && <span className="badge bg-slate-100 text-[10px] text-slate-500">soon</span>}</div>
                  <div className={clsx('truncate text-xs', row?.status === 'error' ? 'text-red-600' : row?.status === 'connected' ? 'text-emerald-600' : 'text-slate-400')}>{statusLabel}</div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {row && <button className="rounded-md p-1 text-slate-400 hover:text-red-600" onClick={() => removeInt.mutate(key)} title="Disconnect"><Trash2 className="h-4 w-4" /></button>}
                  {live ? (
                    <Link to="../google" className="btn-secondary px-3 py-1 text-xs">{row ? 'Manage' : 'Connect'}</Link>
                  ) : (
                    <button className="btn-secondary px-3 py-1 text-xs" onClick={() => { setIntOpen(key); setIntForm({}) }}>{row ? 'Edit' : 'Add credentials'}</button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="card border-red-200 p-5 lg:col-span-2">
        <h2 className="mb-1 font-semibold text-red-700">Danger zone</h2>
        <p className="mb-3 text-sm text-slate-500">Removing the website deletes its audits, keywords, tasks and report schedules.</p>
        <button className="btn-danger" onClick={() => setConfirmDelete(true)}><Trash2 className="h-4 w-4" /> Remove website</button>
      </div>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Remove this website?">
        <p className="text-sm text-slate-600">This cannot be undone. All data for <b>{site.domain}</b> will be deleted.</p>
        <div className="mt-4 flex justify-end gap-2"><button className="btn-secondary" onClick={() => setConfirmDelete(false)}>Cancel</button><button className="btn-danger" onClick={() => remove.mutate()} disabled={remove.isPending}>{remove.isPending && <Spinner />} Remove</button></div>
      </Modal>

      <Modal open={!!intOpen} onClose={() => setIntOpen(null)} title={intOpen ? `Connect ${catalog.data?.[intOpen]?.label}` : ''}>
        {intOpen && catalog.data && (
          <div className="space-y-3">
            {catalog.data[intOpen].fields.map((f) => (
              <div key={f}><label className="label">{f.replace(/_/g, ' ')}</label>
                {f.endsWith('json') ? <textarea className="input min-h-24 font-mono text-xs" value={intForm[f] ?? ''} onChange={(e) => setIntForm({ ...intForm, [f]: e.target.value })} /> : <input className="input" type={/token|secret|password/.test(f) ? 'password' : 'text'} value={intForm[f] ?? ''} onChange={(e) => setIntForm({ ...intForm, [f]: e.target.value })} />}
              </div>
            ))}
            <div className="flex justify-end gap-2"><button className="btn-secondary" onClick={() => setIntOpen(null)}>Cancel</button><button className="btn-primary" disabled={upsertInt.isPending} onClick={() => upsertInt.mutate()}>{upsertInt.isPending && <Spinner />} Save</button></div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function Method({ title, desc, code, extra, onCopy }: { title: string; desc: string; code: string; extra?: string; onCopy: (t: string) => void }) {
  return (
    <div className="rounded-xl border border-slate-200 p-3">
      <div className="font-medium text-slate-800">{title}</div>
      <div className="text-xs text-slate-500">{desc}</div>
      <div className="mt-1 flex items-center gap-2">
        <code className="flex-1 truncate rounded-lg bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700">{code}</code>
        <button className="rounded-md p-1 text-slate-400 hover:text-brand-600" onClick={() => onCopy(code)} title="Copy"><Copy className="h-4 w-4" /></button>
      </div>
      {extra && <div className="mt-1 truncate text-[11px] text-slate-400">{extra}</div>}
    </div>
  )
}
