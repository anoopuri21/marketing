import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ExternalLink, Play, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useOutletContext, useParams } from 'react-router-dom'
import { Alert, ScoreRing, Spinner, useToast } from '../../components/ui'
import { Audits, Websites, errorMessage, type AuditSummary, type Website } from '../../lib/api'
import { timeAgo } from '../../lib/utils'

export interface SiteCtx { site: Website; audits: AuditSummary[]; latestCompleted: AuditSummary | undefined; running: boolean }

export function useSite(): SiteCtx {
  return useOutletContext<SiteCtx>()
}

const tabs = [
  { to: '', label: 'Overview', end: true },
  { to: 'issues', label: 'Issues & pages' },
  { to: 'keywords', label: 'Keywords & rankings' },
  { to: 'plan', label: 'Plan & tasks' },
  { to: 'content', label: 'Content & social' },
  { to: 'reports', label: 'Reports' },
  { to: 'settings', label: 'Settings' },
]

export default function WebsiteLayout() {
  const { id } = useParams()
  const siteId = Number(id)
  const qc = useQueryClient()
  const toast = useToast()

  const site = useQuery({ queryKey: ['website', siteId], queryFn: () => Websites.get(siteId), enabled: !!siteId })
  const audits = useQuery({
    queryKey: ['audits', siteId],
    queryFn: () => Audits.list(siteId),
    enabled: !!siteId,
    refetchInterval: (q) => (q.state.data?.some((a) => a.status === 'queued' || a.status === 'running') ? 3000 : false),
  })

  const running = !!audits.data?.some((a) => a.status === 'queued' || a.status === 'running')
  const latestCompleted = audits.data?.find((a) => a.status === 'completed')

  const start = useMutation({
    mutationFn: () => Audits.start(siteId),
    onSuccess: (r) => {
      toast.push('info', r.message)
      void qc.invalidateQueries({ queryKey: ['audits', siteId] })
    },
    onError: (e) => toast.push('error', errorMessage(e)),
  })

  // when an audit finishes, refresh everything that depends on it
  const prevRunning = useRef(false)
  useEffect(() => {
    if (prevRunning.current && !running) {
      void qc.invalidateQueries({ queryKey: ['website', siteId] })
      void qc.invalidateQueries({ queryKey: ['latest-audit', siteId] })
      void qc.invalidateQueries({ queryKey: ['tasks', siteId] })
      void qc.invalidateQueries({ queryKey: ['websites'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      toast.push('success', 'Audit completed — dashboard updated')
    }
    prevRunning.current = running
  }, [running, siteId, qc, toast])

  if (site.isLoading || audits.isLoading) return <div className="flex justify-center py-20"><Spinner className="h-6 w-6 text-brand-600" /></div>
  if (site.isError || !site.data) return <Alert kind="error">{errorMessage(site.error, 'Website not found')}</Alert>
  const s = site.data

  return (
    <>
      <div className="card mb-6 p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-center">
          <ScoreRing value={s.last_score} size={84} stroke={8} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-xl font-bold text-slate-900">{s.name || s.domain}</h1>
              {s.verified ? (
                <span className="badge bg-emerald-100 text-emerald-700"><ShieldCheck className="mr-1 h-3 w-3" /> verified</span>
              ) : (
                <NavLink to="settings" className="badge bg-amber-100 text-amber-700 hover:bg-amber-200"><ShieldAlert className="mr-1 h-3 w-3" /> not verified</NavLink>
              )}
              {running && <span className="badge bg-brand-100 text-brand-700"><Spinner className="mr-1 h-3 w-3" /> audit running</span>}
            </div>
            <a href={s.url} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600">
              {s.url} <ExternalLink className="h-3 w-3" />
            </a>
            <div className="mt-1 text-xs text-slate-400">
              {[s.industry, s.target_location].filter(Boolean).join(' · ') || 'Add industry & location in Settings for better recommendations'}
              {' · '}
              {s.last_audit_at ? `last audit ${timeAgo(s.last_audit_at)}` : 'no completed audit yet'}
            </div>
          </div>
          <div className="flex gap-2">
            <button className="btn-primary" onClick={() => start.mutate()} disabled={running || start.isPending}>
              {running ? <Spinner /> : <Play className="h-4 w-4" />} {running ? 'Auditing…' : 'Run audit'}
            </button>
          </div>
        </div>
      </div>

      <div className="mb-6 -mx-4 overflow-x-auto border-b border-slate-200 px-4 sm:mx-0 sm:px-0">
        <div className="flex gap-1">
          {tabs.map((t) => (
            <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => clsx('tab', isActive && 'active')}>
              {t.label}
            </NavLink>
          ))}
        </div>
      </div>

      <Outlet context={{ site: s, audits: audits.data ?? [], latestCompleted, running } satisfies SiteCtx} />
    </>
  )
}
