import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bot, Lightbulb, Search, Sparkles, Target, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { EmptyState, ScoreBar, Spinner } from '../../components/ui'
import { Audits, Integrations, Tasks, type AnalyticsData, type SearchPerformance } from '../../lib/api'
import { fmtDate, priorityStyles, severityStyles } from '../../lib/utils'
import { useSite } from '../../hooks/useSite'

export default function OverviewTab() {
  const { site, audits, latestCompleted, running } = useSite()
  const latest = useQuery({ queryKey: ['latest-audit', site.id], queryFn: () => Audits.latest(site.id), enabled: !!latestCompleted, retry: false })
  const tasks = useQuery({ queryKey: ['tasks', site.id], queryFn: () => Tasks.list(site.id) })
  const perf = useQuery({ queryKey: ['search-performance', site.id], queryFn: () => Integrations.searchPerformance(site.id) })
  const analytics = useQuery({ queryKey: ['analytics', site.id], queryFn: () => Integrations.analytics(site.id) })

  if (!latestCompleted) {
    const failed = audits.find((a) => a.status === 'failed')
    return (
      <EmptyState
        icon={running ? <Spinner className="h-6 w-6" /> : <Target className="h-6 w-6" />}
        title={running ? 'First audit in progress…' : failed ? 'The last audit failed' : 'No audit yet'}
        description={running ? 'Crawling pages, checking SEO, AEO, AI-readiness, performance and social signals. This page refreshes automatically.' : failed ? failed.error || 'Unknown error' : 'Click "Run audit" to analyse this website.'}
      />
    )
  }
  if (latest.isLoading) return <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-brand-600" /></div>
  const a = latest.data!
  const ins = a.ai_insights || {}
  const history = [...audits].filter((x) => x.status === 'completed').reverse().map((x) => ({ date: fmtDate(x.finished_at, 'dd MMM'), score: x.overall_score }))
  const sev = (a.summary.issue_counts as Record<string, number>) || {}
  const openTasks = (tasks.data ?? []).filter((t) => t.status === 'todo' || t.status === 'in_progress')

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        {/* Category scores */}
        <div className="card p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900">Health by category</h2>
            <span className="text-xs text-slate-400">{a.pages_crawled} pages crawled · {fmtDate(a.finished_at)}</span>
          </div>
          <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
            <ScoreBar label="On-page SEO" value={a.seo_score} />
            <ScoreBar label="Technical" value={a.technical_score} />
            <ScoreBar label="Content" value={a.content_score} />
            <ScoreBar label="Answer engines (AEO)" value={a.aeo_score} />
            <ScoreBar label="AI search readiness" value={a.ai_readiness_score} />
            <ScoreBar label="Performance" value={a.performance_score} />
            <ScoreBar label="Social" value={a.social_score} />
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            {(['critical', 'high', 'medium', 'low', 'info'] as const).filter((s) => sev[s]).map((s) => (
              <Link to="issues" key={s} className={clsx('badge px-3 py-1 text-xs hover:opacity-80', severityStyles[s])}>{sev[s]} {s}</Link>
            ))}
          </div>
        </div>

        {/* Executive summary */}
        {ins.executive_summary && (
          <div className="card p-5">
            <div className="mb-2 flex items-center gap-2">
              <Bot className="h-4 w-4 text-brand-600" />
              <h2 className="font-semibold text-slate-900">Executive summary</h2>
              <span className="badge bg-slate-100 text-slate-500">{ins.provider === 'rule-based' ? 'rule-based (add an AI key for richer insights)' : `AI · ${ins.provider}`}</span>
            </div>
            <p className="text-sm leading-6 text-slate-700">{ins.executive_summary}</p>
          </div>
        )}

        {/* Quick wins & strategy */}
        <div className="grid gap-6 md:grid-cols-2">
          <div className="card p-5">
            <div className="mb-3 flex items-center gap-2"><TrendingUp className="h-4 w-4 text-emerald-600" /><h2 className="font-semibold text-slate-900">Quick wins (this week)</h2></div>
            <ol className="space-y-3 text-sm">
              {(ins.quick_wins ?? []).map((q, i) => (
                <li key={i} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-xs font-bold text-emerald-700">{i + 1}</span>
                  <div><div className="font-medium text-slate-800">{q.title}</div>{q.how && <div className="mt-0.5 text-slate-500">{q.how}</div>}</div>
                </li>
              ))}
            </ol>
          </div>
          <div className="card p-5">
            <div className="mb-3 flex items-center gap-2"><Lightbulb className="h-4 w-4 text-amber-500" /><h2 className="font-semibold text-slate-900">Strategic priorities (90 days)</h2></div>
            <ul className="space-y-3 text-sm">
              {(ins.strategic_priorities ?? []).map((q, i) => (
                <li key={i}><div className="font-medium text-slate-800">{q.title}</div><div className="mt-0.5 text-slate-500">{q.why} {q.how}</div></li>
              ))}
            </ul>
          </div>
        </div>

        {/* AEO */}
        {ins.aeo_recommendations && ins.aeo_recommendations.length > 0 && (
          <div className="card p-5">
            <h2 className="mb-3 font-semibold text-slate-900">Answer-engine & AI search recommendations</h2>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">{ins.aeo_recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
        )}
      </div>

      <div className="space-y-6">
        <GoogleSnapshot gsc={perf.data?.summary.totals ? perf.data : undefined} ga4={analytics.data?.summary?.totals ? analytics.data : undefined} loaded={perf.isFetched && analytics.isFetched} />

        <div className="card p-5">
          <h2 className="mb-3 font-semibold text-slate-900">Score trend</h2>
          {history.length < 2 ? (
            <p className="text-sm text-slate-500">The trend appears after the second audit. Automatic audits run weekly.</p>
          ) : (
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history} margin={{ left: -20, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="score" stroke="#4f46e5" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="card p-5">
          <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-slate-900">Open tasks</h2><Link to="plan" className="text-xs font-semibold text-brand-600">View all →</Link></div>
          {openTasks.length === 0 ? <p className="text-sm text-slate-500">No open tasks 🎉</p> : (
            <ul className="space-y-2 text-sm">
              {openTasks.slice(0, 6).map((t) => (
                <li key={t.id} className="flex items-start gap-2">
                  <span className={clsx('badge mt-0.5 shrink-0', priorityStyles[t.priority])}>{t.priority}</span>
                  <span className="text-slate-700">{t.title}</span>
                </li>
              ))}
            </ul>
          )}
          {openTasks.length > 6 && <div className="mt-2 text-xs text-slate-400">+{openTasks.length - 6} more</div>}
        </div>

        <div className="card p-5">
          <h2 className="mb-3 font-semibold text-slate-900">Site facts</h2>
          <dl className="space-y-1.5 text-sm">
            <Fact label="HTTPS" ok={!!a.summary.https} />
            <Fact label="robots.txt" ok={!!a.summary.robots_txt_found} />
            <Fact label="XML sitemap" ok={!!a.summary.sitemap_found} extra={a.summary.sitemap_url_count ? `${a.summary.sitemap_url_count} URLs` : ''} />
            <Fact label="llms.txt (AI)" ok={!!a.summary.llms_txt_found} />
            <Fact label="Structured data" ok={((a.summary.schema_types as string[]) || []).length > 0} extra={((a.summary.schema_types as string[]) || []).slice(0, 4).join(', ')} />
            <Fact label="FAQ markup" ok={Number(a.summary.faq_pages || 0) > 0} />
            <Fact label="AI crawlers blocked" ok={((a.summary.robots_blocks_ai_bots as string[]) || []).length === 0} extra={((a.summary.robots_blocks_ai_bots as string[]) || []).join(', ')} invert />
            <div className="flex justify-between"><dt className="text-slate-500">Homepage TTFB</dt><dd className="font-medium">{a.summary.home_ttfb_ms as number} ms</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Avg. words / page</dt><dd className="font-medium">{a.summary.avg_word_count as number}</dd></div>
          </dl>
        </div>

        {ins.keyword_themes && ins.keyword_themes.length > 0 && (
          <div className="card p-5">
            <h2 className="mb-3 font-semibold text-slate-900">Keyword themes to own</h2>
            <div className="flex flex-wrap gap-1.5">{ins.keyword_themes.map((k, i) => <span key={i} className="badge bg-brand-50 px-2.5 py-1 text-xs text-brand-700">{k}</span>)}</div>
            <Link to="keywords" className="mt-3 inline-block text-xs font-semibold text-brand-600">Track these →</Link>
          </div>
        )}
      </div>
    </div>
  )
}

function GoogleSnapshot({ gsc, ga4, loaded }: { gsc?: SearchPerformance; ga4?: AnalyticsData; loaded: boolean }) {
  if (!loaded) return null
  if (!gsc && !ga4) {
    return (
      <div className="card border-dashed p-5">
        <div className="mb-1 flex items-center gap-2"><Search className="h-4 w-4 text-brand-600" /><h2 className="font-semibold text-slate-900">Real Google data</h2></div>
        <p className="text-sm text-slate-500">Connect Search Console to see the actual searches bringing visitors, page-1 opportunities and true positions for your keywords.</p>
        <Link to="google" className="btn-primary mt-3 inline-flex">Connect Google</Link>
      </div>
    )
  }
  const t = gsc?.summary.totals
  const g = ga4?.summary?.totals
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-slate-900">Google · last 28 days</h2><Link to="google" className="text-xs font-semibold text-brand-600">Details →</Link></div>
      <div className="grid grid-cols-2 gap-2">
        {t && <MetricItem label="Clicks" value={t.clicks.toLocaleString()} ch={percentChange(t.clicks, t.prev_clicks)} />}
        {t && <MetricItem label="Impressions" value={t.impressions.toLocaleString()} ch={percentChange(t.impressions, t.prev_impressions)} />}
        {g && <MetricItem label="Sessions" value={g.sessions.toLocaleString()} ch={percentChange(g.sessions, g.prev_sessions)} />}
        {g && <MetricItem label="Conversions" value={g.conversions.toLocaleString()} ch={percentChange(g.conversions, g.prev_conversions)} />}
        {t && !g && <MetricItem label="Avg. position" value={String(t.avg_position ?? '–')} ch={null} />}
        {t && !g && <MetricItem label="CTR" value={`${t.ctr}%`} ch={null} />}
      </div>
      {gsc && gsc.opportunities.length > 0 && (
        <div className="mt-3 text-xs text-slate-500"><Sparkles className="mr-1 inline h-3 w-3 text-amber-500" /><b>{gsc.opportunities.length}</b> quick-win queries sit on positions 5-20 · <Link to="google" className="text-brand-600 hover:underline">see them</Link></div>
      )}
    </div>
  )
}

const percentChange = (cur: number, prev: number) => (prev ? Math.round(((cur - prev) / prev) * 1000) / 10 : null)

function MetricItem({ label, value, ch }: { label: string; value: string; ch: number | null }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="flex items-baseline gap-1.5"><span className="text-lg font-bold text-slate-900">{value}</span>{ch !== null && <span className={clsx('text-[11px] font-semibold', ch >= 0 ? 'text-emerald-600' : 'text-red-500')}>{ch >= 0 ? '+' : ''}{ch}%</span>}</div>
    </div>
  )
}

function Fact({ label, ok, extra, invert }: { label: string; ok: boolean; extra?: string; invert?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="flex items-center gap-2 truncate">
        {extra && <span className="truncate text-xs text-slate-400">{extra}</span>}
        <span className={clsx('h-2.5 w-2.5 rounded-full', ok ? 'bg-emerald-500' : 'bg-red-400')} title={ok ? (invert ? 'none' : 'yes') : invert ? 'yes' : 'no'} />
      </dd>
    </div>
  )
}
