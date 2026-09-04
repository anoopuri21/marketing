import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowRight, CalendarClock, Globe, Plus, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, PageHeader, ScoreRing, Spinner, Stat } from '../components/ui'
import { System, Websites } from '../lib/api'
import { useAuth } from '../lib/authContext'
import { fmtDateTz, scoreColor, severityStyles, timeAgo, weekdays } from '../lib/utils'

export default function DashboardPage() {
  const { user } = useAuth()
  const dash = useQuery({ queryKey: ['dashboard'], queryFn: System.dashboard, refetchInterval: 15_000 })
  const websites = useQuery({ queryKey: ['websites'], queryFn: Websites.list, refetchInterval: 15_000 })

  if (dash.isLoading || websites.isLoading) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6 text-brand-600" /></div>
  const d = dash.data!
  const sites = websites.data ?? []
  const firstName = user?.full_name?.split(' ')[0]

  if (sites.length === 0) {
    return (
      <>
        <PageHeader title={`Welcome${firstName ? ', ' + firstName : ''} 👋`} subtitle="Connect a website to start the first automated audit." />
        <EmptyState
          icon={<Globe className="h-6 w-6" />}
          title="No websites connected yet"
          description="Paste any website URL. RankPilot will crawl it, score SEO / AEO / AI-readiness, create a task plan and set up your reporting."
          action={<Link to="/websites/new" className="btn-primary"><Plus className="h-4 w-4" /> Connect a website</Link>}
        />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={`Good to see you${firstName ? ', ' + firstName : ''}`}
        subtitle="Portfolio overview across all connected websites."
        actions={<Link to="/websites/new" className="btn-primary"><Plus className="h-4 w-4" /> Connect website</Link>}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Websites" value={d.websites} hint={`${d.verified_websites} verified`} />
        <Stat label="Avg. health" value={d.avg_score ?? '–'} accent={scoreColor(d.avg_score)} hint="out of 100" />
        <Stat label="Audits run" value={d.audits_completed} />
        <Stat label="Open tasks" value={d.open_tasks} />
        <Stat label="Keywords" value={d.tracked_keywords} hint="tracked" />
        <Stat label="Reports sent" value={d.reports_sent} />
        <Stat label="Leads" value={d.leads_total} hint={`${d.leads_active} in conversation · ${d.leads_won} won`} />
        <Stat label="Follow-ups due" value={d.follow_ups_due} accent={d.follow_ups_due ? 'text-amber-600' : undefined} hint={d.follow_ups_due ? 'overdue outreach' : 'all caught up'} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Websites</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {sites.map((w) => (
              <Link key={w.id} to={`/websites/${w.id}`} className="card group flex items-center gap-4 p-4 transition hover:border-brand-300 hover:shadow-md">
                <ScoreRing value={w.last_score} size={64} stroke={6} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="truncate font-semibold text-slate-900">{w.name || w.domain}</div>
                    {w.verified && <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-500" />}
                  </div>
                  <div className="truncate text-xs text-slate-500">{w.domain}</div>
                  <div className="mt-1 text-xs text-slate-400">{w.last_audit_at ? `Audited ${timeAgo(w.last_audit_at)}` : 'First audit running…'}</div>
                </div>
                <ArrowRight className="h-4 w-4 text-slate-300 group-hover:text-brand-500" />
              </Link>
            ))}
          </div>

          <h2 className="mt-8 mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Recent audits</h2>
          <div className="card divide-y divide-slate-100">
            {d.recent_audits.length === 0 && <div className="p-4 text-sm text-slate-500">No audits yet.</div>}
            {d.recent_audits.map((a) => {
              const site = sites.find((s) => s.id === a.website_id)
              return (
                <Link key={a.id} to={`/websites/${a.website_id}/audits/${a.id}`} className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-slate-50">
                  <span className={clsx('badge', a.status === 'completed' ? 'bg-emerald-100 text-emerald-700' : a.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700')}>{a.status}</span>
                  <span className="truncate font-medium text-slate-800">{site?.name || site?.domain || `Website #${a.website_id}`}</span>
                  <span className="text-xs text-slate-400">{a.pages_crawled} pages · {a.trigger}</span>
                  <span className="ml-auto text-xs text-slate-400">{timeAgo(a.created_at)}</span>
                  <span className={clsx('w-10 text-right font-bold', scoreColor(a.overall_score))}>{a.overall_score ?? '–'}</span>
                </Link>
              )
            })}
          </div>
        </div>

        <div className="space-y-6">
          <div>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Open issues (latest audits)</h2>
            <div className="card p-4">
              {Object.keys(d.open_issue_counts).length === 0 && <div className="text-sm text-slate-500">No issues recorded yet.</div>}
              <div className="flex flex-wrap gap-2">
                {(['critical', 'high', 'medium', 'low', 'info'] as const).filter((s) => d.open_issue_counts[s]).map((s) => (
                  <span key={s} className={clsx('badge px-3 py-1 text-xs', severityStyles[s])}>{d.open_issue_counts[s]} {s}</span>
                ))}
              </div>
            </div>
          </div>
          <div>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Upcoming reports</h2>
            <div className="card divide-y divide-slate-100">
              {d.upcoming_reports.length === 0 && <div className="p-4 text-sm text-slate-500">No report schedules yet. Open a website → Reports.</div>}
              {d.upcoming_reports.map((r) => {
                const site = sites.find((s) => s.id === r.website_id)
                return (
                  <Link key={r.id} to={`/websites/${r.website_id}/reports`} className="flex items-start gap-3 px-4 py-3 text-sm hover:bg-slate-50">
                    <CalendarClock className="mt-0.5 h-4 w-4 text-brand-500" />
                    <div className="min-w-0">
                      <div className="truncate font-medium text-slate-800">{site?.name || site?.domain}</div>
                      <div className="text-xs text-slate-500">
                        {r.frequency === 'weekly' ? `Every ${weekdays[r.day_of_week]}` : `Monthly on day ${r.day_of_month}`} · {fmtDateTz(r.next_run_at, r.timezone)}
                      </div>
                      <div className="truncate text-xs text-slate-400">{r.recipients.join(', ')}</div>
                    </div>
                  </Link>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
