import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Globe, Sparkles } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, PageHeader, Spinner } from '../components/ui'
import { Websites, errorMessage } from '../lib/api'

export default function NewWebsitePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [form, setForm] = useState({ url: '', name: '', industry: '', target_location: '', description: '' })
  const [error, setError] = useState('')

  const create = useMutation({
    mutationFn: () => Websites.create(form),
    onSuccess: (site) => {
      void qc.invalidateQueries({ queryKey: ['websites'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      navigate(`/websites/${site.id}`)
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError('')
    create.mutate()
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Connect a website" subtitle="We'll crawl it immediately and run the first audit — usually done in under a minute." />
      <form onSubmit={submit} className="card space-y-5 p-6">
        {error && <Alert kind="error">{error}</Alert>}
        <div>
          <label className="label">Website URL *</label>
          <div className="relative">
            <Globe className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input className="input pl-9" placeholder="https://www.yourbusiness.com" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} required autoFocus />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label className="label">Business name</label><input className="input" placeholder="Acme Dental Clinic" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label className="label">Industry / service</label><input className="input" placeholder="dentist, real estate, SaaS…" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} /></div>
        </div>
        <div>
          <label className="label">Target location <span className="font-normal normal-case text-slate-400">(for local SEO; leave empty if global)</span></label>
          <input className="input" placeholder="Delhi, India" value={form.target_location} onChange={(e) => setForm({ ...form, target_location: e.target.value })} />
        </div>
        <div>
          <label className="label">What does the business do? <span className="font-normal normal-case text-slate-400">(helps AI recommendations)</span></label>
          <textarea className="input min-h-24" placeholder="We provide… for… in…" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </div>
        <div className="flex items-center justify-between rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-800">
          <div className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Industry + location make keyword ideas and plans far more relevant.</div>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={() => navigate(-1)}>Cancel</button>
          <button className="btn-primary" disabled={create.isPending}>{create.isPending && <Spinner />} Connect & run first audit</button>
        </div>
      </form>
    </div>
  )
}
