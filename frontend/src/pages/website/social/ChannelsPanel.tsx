import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, ExternalLink, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Alert, Modal, Spinner } from '../../../components/ui'
import { useToast } from '../../../hooks/useToast'
import { Social, errorMessage, type Channel, type PlatformMeta } from '../../../lib/api'
import { timeAgo } from '../../../lib/utils'
import { PlatformIcon } from './shared'

const DOCS: Record<string, string> = {
  facebook: 'https://developers.facebook.com/docs/pages-api/posts/',
  instagram: 'https://developers.facebook.com/docs/instagram-platform/content-publishing/',
  linkedin: 'https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api',
  x: 'https://developer.x.com/en/docs/x-api/tweets/manage-tweets/introduction',
  webhook: 'https://zapier.com/apps/webhook/integrations',
}

export default function ChannelsPanel({ siteId }: { siteId: number }) {
  const qc = useQueryClient()
  const toast = useToast()
  const platforms = useQuery({ queryKey: ['social-platforms'], queryFn: Social.platforms, staleTime: Infinity })
  const channels = useQuery({ queryKey: ['social-channels', siteId], queryFn: () => Social.channels(siteId) })
  const [open, setOpen] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [err, setErr] = useState('')
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['social-channels', siteId] }); void qc.invalidateQueries({ queryKey: ['social-summary', siteId] }) }

  const save = useMutation({
    mutationFn: () => Social.upsertChannel(siteId, open!, form),
    onSuccess: () => { toast.push('success', 'Channel connected'); invalidate(); setOpen(null); setForm({}) },
    onError: (e) => setErr(errorMessage(e)),
  })
  const test = useMutation({
    mutationFn: (p: string) => Social.testChannel(siteId, p),
    onSuccess: (r) => { toast.push(r.ok ? 'success' : 'error', r.detail); invalidate() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const remove = useMutation({ mutationFn: (p: string) => Social.removeChannel(siteId, p), onSuccess: () => { toast.push('success', 'Disconnected'); invalidate() } })

  if (platforms.isLoading || channels.isLoading) return <div className="flex justify-center py-12"><Spinner className="h-6 w-6 text-brand-600" /></div>
  const byPlatform = new Map((channels.data ?? []).map((c) => [c.platform, c]))
  const meta = open ? platforms.data?.[open] : undefined

  return (
    <div className="space-y-4">
      <Alert kind="info">
        Connect the accounts you want RankPilot to post to. Credentials are stored per website and only used at publish time.
        No developer account yet? Use the <b>Webhook</b> channel to push posts into Zapier / Make / Buffer in two minutes.
      </Alert>
      <div className="grid gap-3 md:grid-cols-2">
        {Object.entries(platforms.data ?? {}).map(([key, m]) => {
          const row = byPlatform.get(key)
          return <ChannelCard key={key} platform={key} meta={m} row={row} onConnect={() => { setOpen(key); setForm({}); setErr('') }} onTest={() => test.mutate(key)} onRemove={() => remove.mutate(key)} testing={test.isPending && test.variables === key} />
        })}
      </div>

      <Modal open={!!open} onClose={() => setOpen(null)} title={`Connect ${meta?.label ?? ''}`} wide>
        {open && meta && (
          <div className="grid gap-5 md:grid-cols-5">
            <div className="space-y-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-600 md:col-span-2">
              <div className="font-semibold text-slate-800">How to get these</div>
              <p>{meta.help}</p>
              {DOCS[open] && <a className="inline-flex items-center gap-1 text-brand-600 hover:underline" href={DOCS[open]} target="_blank" rel="noreferrer">Official docs <ExternalLink className="h-3 w-3" /></a>}
              {open === 'webhook' && <p className="text-slate-500">Payload: <code>{'{content, hashtags, image_url, link_url, platform, topic, website}'}</code>. With a secret we add <code>X-RankPilot-Signature</code> (HMAC-SHA256).</p>}
            </div>
            <div className="space-y-3 md:col-span-3">
              {[...meta.fields, ...meta.optional_fields].map((f) => (
                <div key={f}>
                  <label className="label">{f.replace(/_/g, ' ')}{meta.optional_fields.includes(f) && <span className="ml-1 font-normal normal-case text-slate-400">(optional)</span>}</label>
                  <input className="input" type={/token|secret|password/.test(f) ? 'password' : 'text'} value={form[f] ?? ''} onChange={(e) => setForm({ ...form, [f]: e.target.value })} placeholder={f === 'url' ? 'https://hooks.zapier.com/hooks/catch/…' : ''} />
                </div>
              ))}
              {err && <Alert kind="error">{err}</Alert>}
              <div className="flex justify-end gap-2">
                <button className="btn-secondary" onClick={() => setOpen(null)}>Cancel</button>
                <button className="btn-primary" disabled={save.isPending || !meta.fields.every((f) => (form[f] ?? '').trim())} onClick={() => save.mutate()}>{save.isPending && <Spinner />} Connect</button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

function ChannelCard({ platform, meta, row, onConnect, onTest, onRemove, testing }: { platform: string; meta: PlatformMeta; row?: Channel; onConnect: () => void; onTest: () => void; onRemove: () => void; testing: boolean }) {
  const live = meta.status === 'live'
  return (
    <div className={clsx('card p-4', row?.status === 'error' && 'border-red-200', !live && 'opacity-70')}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <PlatformIcon platform={platform} className="h-10 w-10 rounded-xl" />
          <div>
            <div className="font-semibold text-slate-900">{meta.label}</div>
            <div className="text-xs text-slate-500">{live ? `Up to ${meta.max_chars.toLocaleString()} characters` : 'Coming soon'}</div>
          </div>
        </div>
        {row ? (
          <span className={clsx('badge shrink-0', row.status === 'connected' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700')}>{row.status === 'connected' ? <><CheckCircle2 className="mr-1 h-3 w-3" /> Connected</> : 'Needs attention'}</span>
        ) : <span className="badge shrink-0 bg-slate-100 text-slate-500">Not connected</span>}
      </div>
      {row && (
        <div className="mt-3 space-y-1 text-xs text-slate-500">
          {Object.entries(row.config).filter(([k, v]) => v && !/token|secret|password|key/.test(k)).map(([k, v]) => <div key={k} className="truncate">{k.replace(/_/g, ' ')}: <span className="text-slate-700">{String(v)}</span></div>)}
          <div>{row.summary.published ? `${row.summary.published} post(s) published` : 'No posts yet'}{row.last_used_at ? ` · last ${timeAgo(row.last_used_at)}` : ''}</div>
          {row.status === 'error' && row.last_error && <div className="mt-1 flex gap-2 rounded-lg bg-red-50 p-2 text-red-700"><AlertTriangle className="h-4 w-4 shrink-0" /><span className="break-words">{row.last_error}</span></div>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!row ? <button className="btn-primary px-3 py-1.5 text-xs" disabled={!live} onClick={onConnect}>Connect</button> : (
          <>
            <button className="btn-secondary px-3 py-1.5 text-xs" onClick={onTest} disabled={testing}>{testing && <Spinner />} Test connection</button>
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={onConnect}>Update</button>
            <button className="btn-ghost px-2 py-1.5 text-xs text-red-600 hover:bg-red-50" onClick={onRemove}><Trash2 className="h-3.5 w-3.5" /></button>
          </>
        )}
      </div>
    </div>
  )
}
