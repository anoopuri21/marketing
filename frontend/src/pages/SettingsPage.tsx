import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { CheckCircle2, CircleAlert } from 'lucide-react'
import { PageHeader, Spinner } from '../components/ui'
import { System } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function SettingsPage() {
  const { user, workspaces } = useAuth()
  const status = useQuery({ queryKey: ['system'], queryFn: System.status })
  if (status.isLoading) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6 text-brand-600" /></div>
  const s = status.data!

  const rows: { label: string; value: string; ok: boolean; hint: string }[] = [
    { label: 'AI provider', value: s.ai_provider, ok: s.ai_provider !== 'none', hint: 'Set OPENAI_API_KEY or ANTHROPIC_API_KEY in backend/.env for AI-written insights, plans, keyword ideas and social copy. Without it, rule-based logic is used.' },
    { label: 'Rank tracking (SERP)', value: s.serp_provider, ok: s.serp_provider !== 'none', hint: 'Set SERPAPI_KEY to fetch live Google positions for tracked keywords.' },
    { label: 'Email delivery', value: s.email_backend, ok: s.email_backend === 'smtp', hint: 'Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM to deliver scheduled reports to client inboxes. Currently reports are saved to backend/data/outbox.' },
    { label: 'Scheduler', value: s.scheduler_enabled ? 'running' : 'disabled', ok: s.scheduler_enabled, hint: 'Sends due reports and runs automatic weekly audits every minute tick.' },
  ]

  return (
    <>
      <PageHeader title="Settings & system status" subtitle={`${s.app_name} v${s.version} · ${s.environment}`} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="card p-5 lg:col-span-2">
          <h2 className="mb-4 font-semibold text-slate-900">Platform capabilities</h2>
          <div className="divide-y divide-slate-100">
            {rows.map((r) => (
              <div key={r.label} className="flex items-start gap-3 py-3">
                {r.ok ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" /> : <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />}
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-sm font-medium text-slate-800">{r.label} <span className={clsx('badge', r.ok ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700')}>{r.value}</span></div>
                  <div className="mt-0.5 text-xs text-slate-500">{r.hint}</div>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 rounded-xl bg-slate-50 p-3 text-xs text-slate-500">All keys live in <code>backend/.env</code> (see <code>backend/.env.example</code>). Restart the API after changing them.</p>
        </div>
        <div className="card p-5">
          <h2 className="mb-3 font-semibold text-slate-900">Account</h2>
          <dl className="space-y-2 text-sm">
            <div><dt className="text-xs uppercase tracking-wide text-slate-400">Name</dt><dd className="text-slate-800">{user?.full_name || '—'}</dd></div>
            <div><dt className="text-xs uppercase tracking-wide text-slate-400">Email</dt><dd className="text-slate-800">{user?.email}</dd></div>
            <div><dt className="text-xs uppercase tracking-wide text-slate-400">Workspaces</dt><dd className="text-slate-800">{workspaces.map((w) => w.name).join(', ')}</dd></div>
          </dl>
        </div>
      </div>
    </>
  )
}
