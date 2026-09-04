import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, BarChart3, ExternalLink, Minus, RefreshCw, Search, Sparkles, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Alert, Modal, Spinner } from '../../components/ui'
import { useToast } from '../../hooks/useToast'
import { Integrations, errorMessage, type AnalyticsData, type Integration, type IntegrationMeta, type SearchPerformance, type SearchStat } from '../../lib/api'
import { fmtDate, timeAgo } from '../../lib/utils'
import { useSite } from '../../hooks/useSite'

const GSC = 'google_search_console'
const GA4 = 'ga4'

export default function GoogleTab() {
  const { site } = useSite()
  const qc = useQueryClient()
  const toast = useToast()
  const catalog = useQuery({ queryKey: ['integrations-catalog'], queryFn: Integrations.catalog, staleTime: Infinity })
  const integrations = useQuery({ queryKey: ['integrations', site.id], queryFn: () => Integrations.list(site.id) })
  const perf = useQuery({ queryKey: ['search-performance', site.id], queryFn: () => Integrations.searchPerformance(site.id) })
  const analytics = useQuery({ queryKey: ['analytics', site.id], queryFn: () => Integrations.analytics(site.id) })
  const [connect, setConnect] = useState<string | null>(null)

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['integrations', site.id] })
    void qc.invalidateQueries({ queryKey: ['search-performance', site.id] })
    void qc.invalidateQueries({ queryKey: ['analytics', site.id] })
    void qc.invalidateQueries({ queryKey: ['keywords', site.id] })
  }
  const sync = useMutation({
    mutationFn: (provider: string) => Integrations.sync(site.id, provider),
    onSuccess: (r) => { toast.push(r.status === 'connected' ? 'success' : 'error', r.status === 'connected' ? 'Data refreshed from Google' : r.last_error); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (provider: string) => Integrations.remove(site.id, provider),
    onSuccess: () => { toast.push('success', 'Disconnected'); invalidate() },
  })

  const gsc = integrations.data?.find((i) => i.provider === GSC)
  const ga4 = integrations.data?.find((i) => i.provider === GA4)
  const loading = integrations.isLoading || perf.isLoading || analytics.isLoading

  if (loading) return <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-brand-600" /></div>

  return (
    <div className="space-y-6">
      {!gsc && !ga4 && (
        <Alert kind="info">
          Connect Google Search Console to see the <b>real</b> queries that bring visitors, page-1 opportunities and true Google positions for your tracked keywords.
          GA4 adds sessions, conversions and traffic channels. Both are read-only and take about two minutes to set up.
        </Alert>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <ConnectionCard
          icon={<Search className="h-5 w-5" />} title="Google Search Console" row={gsc} meta={catalog.data?.[GSC]}
          description="Clicks, impressions, average position and the exact search queries from Google."
          onConnect={() => setConnect(GSC)} onSync={() => sync.mutate(GSC)} onRemove={() => remove.mutate(GSC)} syncing={sync.isPending && sync.variables === GSC}
        />
        <ConnectionCard
          icon={<BarChart3 className="h-5 w-5" />} title="Google Analytics 4" row={ga4} meta={catalog.data?.[GA4]}
          description="Sessions, users, conversions, channels and top landing pages."
          onConnect={() => setConnect(GA4)} onSync={() => sync.mutate(GA4)} onRemove={() => remove.mutate(GA4)} syncing={sync.isPending && sync.variables === GA4}
        />
      </div>

      {perf.data?.connected && perf.data.summary.totals && <SearchConsolePanel data={perf.data} />}
      {analytics.data?.connected && analytics.data.summary?.totals && <AnalyticsPanel data={analytics.data} />}

      <ConnectModal
        provider={connect} meta={connect ? catalog.data?.[connect] : undefined} siteId={site.id} siteUrl={site.url}
        onClose={() => setConnect(null)} onDone={(r) => { setConnect(null); invalidate(); toast.push(r.status === 'connected' ? 'success' : 'error', r.status === 'connected' ? 'Connected – first sync complete' : r.last_error || 'Could not connect') }}
      />
    </div>
  )
}

// ------------------------------------------------------------------ connection card
function ConnectionCard({ icon, title, description, row, meta, onConnect, onSync, onRemove, syncing }: {
  icon: ReactNode; title: string; description: string; row?: Integration; meta?: IntegrationMeta
  onConnect: () => void; onSync: () => void; onRemove: () => void; syncing: boolean
}) {
  const status = row?.status
  const cfg = (row?.config ?? {}) as Record<string, string>
  return (
    <div className={clsx('card p-5', status === 'error' && 'border-red-200')}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className={clsx('flex h-10 w-10 items-center justify-center rounded-xl', status === 'connected' ? 'bg-emerald-50 text-emerald-600' : status === 'error' ? 'bg-red-50 text-red-600' : 'bg-slate-100 text-slate-500')}>{icon}</div>
          <div>
            <div className="font-semibold text-slate-900">{title}</div>
            <div className="text-xs text-slate-500">{description}</div>
          </div>
        </div>
        <StatusPill status={status} />
      </div>
      {row && (
        <div className="mt-3 space-y-1 text-xs text-slate-500">
          {cfg.site_url && <div>Property: <code className="rounded bg-slate-100 px-1 text-slate-700">{cfg.site_url}</code></div>}
          {cfg.property_id && <div>Property ID: <code className="rounded bg-slate-100 px-1 text-slate-700">{cfg.property_id}</code></div>}
          {cfg.service_account_json && <div className="truncate">Service account: <span className="text-slate-700">{/\((.+)\)/.exec(String(cfg.service_account_json))?.[1] ?? 'key stored'}</span></div>}
          <div>Last sync: {row.last_synced_at ? timeAgo(row.last_synced_at) : 'never'} · auto-refresh daily and before every report</div>
          {status === 'error' && row.last_error && <div className="mt-2 flex gap-2 rounded-lg bg-red-50 p-2 text-red-700"><AlertTriangle className="h-4 w-4 shrink-0" /><span className="break-words">{row.last_error}</span></div>}
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {!row ? (
          <button className="btn-primary" onClick={onConnect}>Connect</button>
        ) : (
          <>
            <button className="btn-secondary" onClick={onSync} disabled={syncing}>{syncing ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Sync now</button>
            <button className="btn-ghost" onClick={onConnect}>Update credentials</button>
            <button className="btn-ghost text-red-600 hover:bg-red-50" onClick={onRemove}><Trash2 className="h-4 w-4" /> Disconnect</button>
          </>
        )}
        {meta?.status === 'planned' && <span className="text-xs text-slate-400">coming soon</span>}
      </div>
    </div>
  )
}

function StatusPill({ status }: { status?: string }) {
  const map: Record<string, string> = { connected: 'bg-emerald-50 text-emerald-700', error: 'bg-red-50 text-red-700', pending: 'bg-amber-50 text-amber-700' }
  const label = status === 'connected' ? 'Connected' : status === 'error' ? 'Needs attention' : status === 'pending' ? 'Pending' : 'Not connected'
  return <span className={clsx('badge shrink-0', map[status ?? ''] ?? 'bg-slate-100 text-slate-500')}>{label}</span>
}

// ------------------------------------------------------------------ connect modal
function ConnectModal({ provider, meta, siteId, siteUrl, onClose, onDone }: {
  provider: string | null; meta?: IntegrationMeta; siteId: number; siteUrl: string; onClose: () => void; onDone: (r: Integration) => void
}) {
  const [form, setForm] = useState<Record<string, string>>({})
  const [localError, setLocalError] = useState('')
  const save = useMutation({
    mutationFn: () => Integrations.upsert(siteId, provider!, form),
    onSuccess: (r) => { setForm({}); onDone(r) },
    onError: (e) => setLocalError(errorMessage(e)),
  })
  const email = (() => { try { return JSON.parse(form.service_account_json || '{}').client_email as string | undefined } catch { return undefined } })()
  const fields = meta?.fields ?? []
  const required = fields.every((f) => (form[f] ?? '').trim())
  const isGsc = provider === GSC

  return (
    <Modal open={!!provider} onClose={onClose} title={`Connect ${meta?.label ?? ''}`} wide>
      {provider && (
        <div className="grid gap-5 md:grid-cols-5">
          <ol className="space-y-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600 md:col-span-2">
            <li className="font-semibold text-slate-800">Setup (one time, ~2 min)</li>
            <li>1. In <a className="text-brand-600 hover:underline" href="https://console.cloud.google.com/apis/library" target="_blank" rel="noreferrer">Google Cloud Console <ExternalLink className="inline h-3 w-3" /></a> enable the <b>{isGsc ? 'Google Search Console API' : 'Google Analytics Data API'}</b>.</li>
            <li>2. Go to <b>IAM &amp; Admin → Service accounts</b>, create one, then <b>Keys → Add key → JSON</b>. Download the file.</li>
            <li>3. {isGsc ? <>In <a className="text-brand-600 hover:underline" href="https://search.google.com/search-console/users" target="_blank" rel="noreferrer">Search Console → Settings → Users</a> add the service-account email as a user (Full).</> : <>In GA4 <b>Admin → Property access management</b> add the service-account email as <b>Viewer</b>. Copy the numeric Property ID from <b>Property settings</b>.</>}</li>
            <li>4. Paste the JSON below. We only read data – nothing is ever written to your Google account.</li>
            {isGsc && <li className="text-slate-500">Property for <code>{siteUrl.replace(/^https?:\/\//, '')}</code> is detected automatically (domain or URL-prefix).</li>}
          </ol>
          <div className="space-y-3 md:col-span-3">
            {fields.filter((f) => f !== 'service_account_json').map((f) => (
              <div key={f}><label className="label">{f.replace(/_/g, ' ')}</label><input className="input" value={form[f] ?? ''} placeholder={f === 'property_id' ? 'e.g. 123456789' : ''} onChange={(e) => setForm({ ...form, [f]: e.target.value })} /></div>
            ))}
            {fields.includes('service_account_json') && (
              <div>
                <label className="label">Service account JSON key</label>
                <textarea className="input min-h-40 font-mono text-[11px]" placeholder={'{\n  "type": "service_account",\n  "project_id": "...",\n  "private_key": "-----BEGIN PRIVATE KEY-----...",\n  "client_email": "name@project.iam.gserviceaccount.com",\n  ...\n}'} value={form.service_account_json ?? ''} onChange={(e) => setForm({ ...form, service_account_json: e.target.value })} />
                {email && <div className="mt-1 text-xs text-emerald-700">Service account: <b>{email}</b> – make sure this email has access in Google.</div>}
                <div className="mt-1 text-xs text-slate-400">Or upload the file: <input type="file" accept="application/json,.json" className="text-xs" onChange={(e) => { const f = e.target.files?.[0]; if (!f) return; void f.text().then((t) => setForm((prev) => ({ ...prev, service_account_json: t }))) }} /></div>
              </div>
            )}
            {isGsc && <div><label className="label">Property URL (optional – auto-detected)</label><input className="input" placeholder="sc-domain:example.com or https://www.example.com/" value={form.site_url ?? ''} onChange={(e) => setForm({ ...form, site_url: e.target.value })} /></div>}
            {localError && <Alert kind="error">{localError}</Alert>}
            <div className="flex justify-end gap-2">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn-primary" disabled={!required || save.isPending} onClick={() => { setLocalError(''); save.mutate() }}>{save.isPending && <Spinner />} {save.isPending ? 'Connecting & syncing…' : 'Connect'}</button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ------------------------------------------------------------------ Search Console panel
function SearchConsolePanel({ data }: { data: SearchPerformance }) {
  const t = data.summary.totals!
  const period = data.summary.period
  const [view, setView] = useState<'queries' | 'pages' | 'opportunities'>('queries')
  const rows = view === 'queries' ? data.queries : view === 'pages' ? data.pages : data.opportunities
  const daily = (data.summary.daily ?? []).map((d) => ({ ...d, label: fmtDate(d.date, 'dd MMM') }))

  return (
    <div className="card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-semibold text-slate-900">Search performance</h2>
          <div className="text-xs text-slate-400">{period ? `${fmtDate(period.start, 'dd MMM')} – ${fmtDate(period.end, 'dd MMM yyyy')} · vs previous ${period.days} days` : ''} · {data.summary.property}</div>
        </div>
        {(data.summary.matched_keywords ?? 0) > 0 && <Link to="../keywords" className="text-xs text-brand-600 hover:underline">{data.summary.matched_keywords} tracked keyword(s) now show real Google positions →</Link>}
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <Metric label="Clicks" value={t.clicks.toLocaleString()} change={pct(t.clicks, t.prev_clicks)} />
        <Metric label="Impressions" value={t.impressions.toLocaleString()} change={pct(t.impressions, t.prev_impressions)} />
        <Metric label="Average CTR" value={`${t.ctr}%`} />
        <Metric label="Average position" value={t.avg_position ?? '–'} />
      </div>
      {daily.length > 1 && (
        <div className="mt-4 h-44">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={daily} margin={{ left: -16, right: 8, top: 8 }}>
              <defs><linearGradient id="clicks" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4f46e5" stopOpacity={0.3} /><stop offset="100%" stopColor="#4f46e5" stopOpacity={0} /></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Area type="monotone" dataKey="clicks" stroke="#4f46e5" fill="url(#clicks)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        {(['queries', 'pages', 'opportunities'] as const).map((v) => (
          <button key={v} onClick={() => setView(v)} className={clsx('rounded-full px-3 py-1 text-xs font-medium transition', view === v ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')}>
            {v === 'opportunities' ? <span className="inline-flex items-center gap-1"><Sparkles className="h-3 w-3" /> Quick-win opportunities ({data.opportunities.length})</span> : v === 'queries' ? `Top queries (${data.queries.length})` : `Top pages (${data.pages.length})`}
          </button>
        ))}
      </div>
      {view === 'opportunities' && <p className="mt-2 text-xs text-slate-500">Queries ranking between positions 5 and 20 with real demand. Improving title/meta, adding a focused section or an FAQ typically moves these to page 1 within weeks.</p>}
      <div className="mt-3 overflow-x-auto">
        {rows.length === 0 ? <div className="py-8 text-center text-sm text-slate-400">No data for this view yet.</div> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="py-2 pr-3">{view === 'pages' ? 'Page' : 'Query'}</th><th className="py-2 pr-3 text-right">Clicks</th><th className="py-2 pr-3 text-right">Impressions</th><th className="py-2 pr-3 text-right">CTR</th><th className="py-2 text-right">Position</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.slice(0, 50).map((r) => <StatRow key={r.key} r={r} isPage={view === 'pages'} />)}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function StatRow({ r, isPage }: { r: SearchStat; isPage: boolean }) {
  const clickDelta = r.prev_clicks !== null && r.prev_clicks !== undefined ? r.clicks - r.prev_clicks : null
  const posDelta = r.prev_position !== null && r.prev_position !== undefined ? r.prev_position - r.position : null // positive = improved
  return (
    <tr className="hover:bg-slate-50">
      <td className="max-w-[22rem] truncate py-2 pr-3 font-medium text-slate-800">{isPage ? <a href={r.key} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">{r.key.replace(/^https?:\/\/[^/]+/, '') || '/'}</a> : r.key}</td>
      <td className="py-2 pr-3 text-right"><span className="font-semibold">{r.clicks}</span> <Delta v={clickDelta} /></td>
      <td className="py-2 pr-3 text-right text-slate-600">{r.impressions.toLocaleString()}</td>
      <td className="py-2 pr-3 text-right text-slate-600">{r.ctr}%</td>
      <td className="py-2 text-right"><span className={clsx('font-semibold', r.position <= 3 ? 'text-emerald-600' : r.position <= 10 ? 'text-slate-800' : 'text-amber-600')}>{r.position.toFixed(1)}</span> <Delta v={posDelta !== null ? Math.round(posDelta * 10) / 10 : null} /></td>
    </tr>
  )
}

function Delta({ v }: { v: number | null }) {
  if (v === null || Number.isNaN(v)) return null
  if (v === 0) return <Minus className="inline h-3 w-3 text-slate-300" />
  return <span className={clsx('inline-flex items-center text-[11px] font-semibold', v > 0 ? 'text-emerald-600' : 'text-red-500')}>{v > 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}{Math.abs(v)}</span>
}

// ------------------------------------------------------------------ GA4 panel
function AnalyticsPanel({ data }: { data: AnalyticsData }) {
  const s = data.summary!
  const t = s.totals!
  const daily = (s.daily ?? []).map((d) => ({ ...d, label: fmtDate(d.date, 'dd MMM') }))
  const maxCh = Math.max(1, ...(s.channels ?? []).map((c) => c.sessions))
  return (
    <div className="card p-5">
      <div className="mb-4">
        <h2 className="font-semibold text-slate-900">Website traffic (GA4)</h2>
        <div className="text-xs text-slate-400">{s.period ? `${fmtDate(s.period.start, 'dd MMM')} – ${fmtDate(s.period.end, 'dd MMM yyyy')} · vs previous ${s.period.days} days` : ''} · {s.property}</div>
      </div>
      <div className="grid gap-3 sm:grid-cols-5">
        <Metric label="Sessions" value={t.sessions.toLocaleString()} change={pct(t.sessions, t.prev_sessions)} />
        <Metric label="Users" value={t.users.toLocaleString()} change={pct(t.users, t.prev_users)} />
        <Metric label="Conversions" value={t.conversions.toLocaleString()} change={pct(t.conversions, t.prev_conversions)} />
        <Metric label="Engagement rate" value={`${t.engagement_rate}%`} hint={`${Math.round(t.avg_session_duration)}s avg. session`} />
        <Metric label="Organic share" value={`${t.organic_share}%`} hint={`${t.organic_sessions.toLocaleString()} organic sessions`} />
      </div>
      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          {daily.length > 1 && (
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={daily} margin={{ left: -16, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="sessions" fill="#4f46e5" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Top pages</div>
            <table className="w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {(s.top_pages ?? []).slice(0, 8).map((p) => (
                  <tr key={p.path}><td className="max-w-[20rem] truncate py-1.5 pr-3 text-slate-800">{p.path}</td><td className="py-1.5 text-right text-slate-600">{p.views.toLocaleString()} views</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="space-y-5">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Channels</div>
            <div className="space-y-2">
              {(s.channels ?? []).slice(0, 6).map((c) => (
                <div key={c.channel}>
                  <div className="flex justify-between text-xs"><span className="text-slate-700">{c.channel}</span><span className="text-slate-500">{c.sessions.toLocaleString()}{c.conversions ? ` · ${c.conversions} conv.` : ''}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className={clsx('h-1.5 rounded-full', c.channel.toLowerCase().startsWith('organic search') ? 'bg-emerald-500' : 'bg-brand-500')} style={{ width: `${Math.max(3, (c.sessions / maxCh) * 100)}%` }} /></div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Devices</div>
              {(s.devices ?? []).map((d) => <div key={d.device} className="flex justify-between text-xs text-slate-600"><span className="capitalize">{d.device}</span><span>{t.sessions ? Math.round((d.sessions / t.sessions) * 100) : 0}%</span></div>)}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Countries</div>
              {(s.countries ?? []).slice(0, 5).map((c) => <div key={c.country} className="flex justify-between text-xs text-slate-600"><span className="truncate">{c.country}</span><span>{c.sessions.toLocaleString()}</span></div>)}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ bits
function Metric({ label, value, change, hint }: { label: string; value: ReactNode; change?: number | null; hint?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-2"><span className="text-xl font-bold text-slate-900">{value}</span>{change !== undefined && change !== null && <span className={clsx('text-xs font-semibold', change >= 0 ? 'text-emerald-600' : 'text-red-500')}>{change >= 0 ? '+' : ''}{change}%</span>}</div>
      {hint && <div className="text-[11px] text-slate-400">{hint}</div>}
    </div>
  )
}

function pct(cur: number, prev: number): number | null {
  if (!prev) return null
  return Math.round(((cur - prev) / prev) * 1000) / 10
}
