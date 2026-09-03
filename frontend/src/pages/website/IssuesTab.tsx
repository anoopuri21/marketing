import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, ChevronRight, FileSearch } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { EmptyState, Spinner } from '../../components/ui'
import { Audits, type AuditIssue } from '../../lib/api'
import { categoryLabels, severityStyles } from '../../lib/utils'
import { useSite } from './WebsiteLayout'

const SEV_ORDER = ['critical', 'high', 'medium', 'low', 'info']

export default function IssuesTab() {
  const { site, latestCompleted } = useSite()
  const { auditId } = useParams()
  const id = auditId ? Number(auditId) : undefined
  const audit = useQuery({
    queryKey: id ? ['audit', site.id, id] : ['latest-audit', site.id],
    queryFn: () => (id ? Audits.get(site.id, id) : Audits.latest(site.id)),
    enabled: !!latestCompleted || !!id,
    retry: false,
  })
  const [view, setView] = useState<'issues' | 'pages'>('issues')
  const [sevFilter, setSevFilter] = useState<string>('all')
  const [catFilter, setCatFilter] = useState<string>('all')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const groups = useMemo(() => {
    const issues = audit.data?.issues ?? []
    const filtered = issues.filter((i) => (sevFilter === 'all' || i.severity === sevFilter) && (catFilter === 'all' || i.category === catFilter))
    const map = new Map<string, AuditIssue[]>()
    for (const i of filtered) {
      const arr = map.get(i.code) ?? []
      arr.push(i)
      map.set(i.code, arr)
    }
    return [...map.values()].sort((a, b) => SEV_ORDER.indexOf(a[0].severity) - SEV_ORDER.indexOf(b[0].severity) || b.length - a.length)
  }, [audit.data, sevFilter, catFilter])

  if (!latestCompleted && !id) return <EmptyState icon={<FileSearch className="h-6 w-6" />} title="No completed audit yet" description="Run an audit to see issues and page-level details." />
  if (audit.isLoading) return <div className="flex justify-center py-16"><Spinner className="h-6 w-6 text-brand-600" /></div>
  if (!audit.data) return <EmptyState title="Audit not found" />
  const a = audit.data
  const cats = [...new Set(a.issues.map((i) => i.category))]

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-slate-200 bg-white p-0.5 text-sm">
          <button className={clsx('rounded-lg px-3 py-1.5 font-medium', view === 'issues' ? 'bg-brand-600 text-white' : 'text-slate-600')} onClick={() => setView('issues')}>Issues ({a.issues.length})</button>
          <button className={clsx('rounded-lg px-3 py-1.5 font-medium', view === 'pages' ? 'bg-brand-600 text-white' : 'text-slate-600')} onClick={() => setView('pages')}>Pages ({a.pages.length})</button>
        </div>
        {view === 'issues' && (
          <>
            <select className="input w-auto" value={sevFilter} onChange={(e) => setSevFilter(e.target.value)}>
              <option value="all">All severities</option>
              {SEV_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className="input w-auto" value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
              <option value="all">All categories</option>
              {cats.map((c) => <option key={c} value={c}>{categoryLabels[c] ?? c}</option>)}
            </select>
          </>
        )}
        <span className="ml-auto text-xs text-slate-400">Audit #{a.id} · {a.pages_crawled} pages</span>
      </div>

      {view === 'issues' ? (
        <div className="space-y-2">
          {groups.length === 0 && <div className="card p-6 text-center text-sm text-slate-500">No issues match the filter. 🎉</div>}
          {groups.map((g) => {
            const first = g[0]
            const open = expanded[first.code]
            return (
              <div key={first.code} className="card overflow-hidden">
                <button className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50" onClick={() => setExpanded({ ...expanded, [first.code]: !open })}>
                  {open ? <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-slate-400" /> : <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-slate-400" />}
                  <span className={clsx('badge mt-0.5 shrink-0', severityStyles[first.severity])}>{first.severity}</span>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-slate-900">{first.title.replace(/\s*\(\d+ chars\)$/, '')}</div>
                    <div className="mt-0.5 text-xs text-slate-500">{categoryLabels[first.category] ?? first.category} · {g.length} {g.length === 1 ? 'occurrence' : 'occurrences'}</div>
                  </div>
                </button>
                {open && (
                  <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-3 text-sm">
                    {first.description && <p className="text-slate-600">{first.description}</p>}
                    {first.recommendation && <p className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-emerald-800"><b>Fix:</b> {first.recommendation}</p>}
                    {g.some((i) => i.page_url) && (
                      <ul className="mt-3 max-h-56 space-y-1 overflow-y-auto text-xs">
                        {g.map((i) => (
                          <li key={i.id} className="flex flex-wrap gap-x-2">
                            <a href={i.page_url} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">{i.page_url || '(site-wide)'}</a>
                            {i.title !== first.title && <span className="text-slate-400">— {i.title}</span>}
                            {i.description && i.description !== first.description && i.page_url && <span className="w-full truncate text-slate-400">{i.description}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-2">URL</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Time</th><th className="px-3 py-2">Title</th><th className="px-3 py-2">Words</th><th className="px-3 py-2">H1</th><th className="px-3 py-2">Schema</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {a.pages.map((p) => {
                const schema = (p.data.schema_types as string[]) || []
                return (
                  <tr key={p.id} className="align-top hover:bg-slate-50">
                    <td className="max-w-xs px-4 py-2"><a href={p.url} target="_blank" rel="noreferrer" className="block truncate text-brand-600 hover:underline">{p.url.replace(/^https?:\/\/[^/]+/, '') || '/'}</a></td>
                    <td className="px-3 py-2"><span className={clsx('badge', !p.status_code ? 'bg-red-100 text-red-700' : p.status_code < 300 ? 'bg-emerald-100 text-emerald-700' : p.status_code < 400 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700')}>{p.status_code ?? 'ERR'}</span></td>
                    <td className="px-3 py-2 text-slate-500">{p.response_ms ?? '–'} ms</td>
                    <td className="max-w-xs px-3 py-2"><div className="truncate" title={p.title}>{p.title || <span className="text-red-500">missing</span>}</div><div className="truncate text-xs text-slate-400" title={p.meta_description}>{p.meta_description || 'no meta description'}</div></td>
                    <td className="px-3 py-2 text-slate-600">{p.word_count}</td>
                    <td className="max-w-[10rem] truncate px-3 py-2 text-slate-600" title={p.h1}>{p.h1 || <span className="text-red-500">–</span>}</td>
                    <td className="max-w-[10rem] truncate px-3 py-2 text-xs text-slate-500" title={schema.join(', ')}>{schema.join(', ') || '–'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
