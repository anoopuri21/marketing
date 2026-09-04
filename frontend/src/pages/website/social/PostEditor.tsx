import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarClock, Copy, ImagePlus, Send, Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, Modal, Spinner, useToast } from '../../../components/ui'
import { Creatives, Social, errorMessage, type Creative, type SocialPost } from '../../../lib/api'
import CreativeStudio from './CreativeStudio'
import { PLATFORM_LABELS, PlatformIcon, fromLocalInput, toLocalInput } from './shared'

export interface EditorState {
  id?: number; platform: string; content: string; topic: string; hashtags: string; link_url: string; creative_id: number | null; creative_url: string; scheduled_for: string
}

export const emptyEditor = (platform = 'instagram', siteUrl = ''): EditorState => ({ platform, content: '', topic: '', hashtags: '', link_url: siteUrl, creative_id: null, creative_url: '', scheduled_for: '' })

export function fromPost(p: SocialPost): EditorState {
  return { id: p.id, platform: p.platform, content: p.content, topic: p.topic, hashtags: p.hashtags.join(' '), link_url: p.link_url, creative_id: p.creative_id, creative_url: p.creative_url, scheduled_for: toLocalInput(p.scheduled_for) }
}

export default function PostEditor({ siteId, siteUrl, state, connected, onClose }: { siteId: number; siteUrl: string; state: EditorState | null; connected: string[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState<EditorState>(state ?? emptyEditor())
  const [studio, setStudio] = useState(false)
  const [tone, setTone] = useState('friendly')
  const platforms = useQuery({ queryKey: ['social-platforms'], queryFn: Social.platforms, staleTime: Infinity })
  const library = useQuery({ queryKey: ['creatives', siteId], queryFn: () => Creatives.list(siteId), enabled: !!state })
  useEffect(() => { if (state) setForm(state) }, [state])

  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['social-posts', siteId] }); void qc.invalidateQueries({ queryKey: ['social-summary', siteId] }) }
  const payload = (status?: 'draft' | 'scheduled') => ({
    platform: form.platform, content: form.content, topic: form.topic, link_url: form.link_url, creative_id: form.creative_id,
    hashtags: form.hashtags.split(/[\s,]+/).map((h) => h.trim()).filter(Boolean).map((h) => (h.startsWith('#') ? h : `#${h}`)),
    scheduled_for: fromLocalInput(form.scheduled_for), ...(status ? { status } : {}),
  })
  const save = useMutation({
    mutationFn: async (status: 'draft' | 'scheduled') => (form.id ? Social.updatePost(siteId, form.id, payload(status)) : Social.createPost(siteId, payload(status))),
    onSuccess: (_, status) => { toast.push('success', status === 'scheduled' ? 'Post scheduled' : 'Draft saved'); invalidate(); onClose() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const publish = useMutation({
    mutationFn: async () => {
      const saved = form.id ? await Social.updatePost(siteId, form.id, payload()) : await Social.createPost(siteId, payload('draft'))
      return Social.publishNow(siteId, saved.id)
    },
    onSuccess: (p) => { toast.push(p.status === 'published' ? 'success' : 'error', p.status === 'published' ? `Published to ${PLATFORM_LABELS[p.platform] ?? p.platform}` : p.error); invalidate(); onClose() },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const draftAI = useMutation({
    mutationFn: () => Social.draft(siteId, form.topic || form.content.slice(0, 120), [form.platform], tone),
    onSuccess: (r) => { const p = r.posts[0]; if (p) setForm((f) => ({ ...f, content: p.content, hashtags: (p.hashtags ?? []).join(' ') })); toast.push('info', `Draft written (${r.provider})`) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })

  const meta = platforms.data?.[form.platform]
  const fullText = [form.content.trim(), form.platform !== 'instagram' ? form.link_url : '', form.hashtags.split(/[\s,]+/).filter(Boolean).map((h) => (h.startsWith('#') ? h : `#${h}`)).join(' ')].filter(Boolean).join('\n\n')
  const over = meta ? fullText.length > meta.max_chars : false
  const isConnected = connected.includes(form.platform)
  const needsImage = form.platform === 'instagram' && !form.creative_id

  return (
    <Modal open={!!state} onClose={onClose} title={form.id ? 'Edit post' : 'New post'} wide>
      <div className="grid gap-5 md:grid-cols-5">
        <div className="space-y-3 md:col-span-3">
          <div>
            <label className="label">Platform</label>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(platforms.data ?? {}).filter(([, m]) => m.status === 'live').map(([k]) => (
                <button key={k} onClick={() => setForm({ ...form, platform: k })} className={clsx('flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', form.platform === k ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600')}>
                  <PlatformIcon platform={k} className="h-5 w-5 rounded-md" />{PLATFORM_LABELS[k]}{connected.includes(k) && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-end gap-2">
            <div className="flex-1"><label className="label">Topic (for AI)</label><input className="input" placeholder="e.g. Monsoon-proofing tips for homeowners" value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value })} /></div>
            <select className="input w-32" value={tone} onChange={(e) => setTone(e.target.value)}>{['friendly', 'professional', 'bold', 'educational', 'witty'].map((t) => <option key={t}>{t}</option>)}</select>
            <button className="btn-secondary whitespace-nowrap" disabled={draftAI.isPending || !(form.topic || form.content)} onClick={() => draftAI.mutate()}>{draftAI.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />} Write</button>
          </div>
          <div>
            <div className="flex items-center justify-between"><label className="label">Post text</label><span className={clsx('text-[11px]', over ? 'font-semibold text-red-600' : 'text-slate-400')}>{fullText.length}{meta ? ` / ${meta.max_chars.toLocaleString()}` : ''}</span></div>
            <textarea className="input min-h-40" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">Hashtags</label><input className="input" placeholder="#webdesign #delhi" value={form.hashtags} onChange={(e) => setForm({ ...form, hashtags: e.target.value })} /></div>
            <div><label className="label">Link</label><input className="input" placeholder={siteUrl} value={form.link_url} onChange={(e) => setForm({ ...form, link_url: e.target.value })} /></div>
          </div>
          <div>
            <label className="label">Schedule (your local time)</label>
            <div className="flex items-center gap-2">
              <input type="datetime-local" className="input" value={form.scheduled_for} onChange={(e) => setForm({ ...form, scheduled_for: e.target.value })} />
              {form.scheduled_for && <button className="btn-ghost px-2" onClick={() => setForm({ ...form, scheduled_for: '' })}><X className="h-4 w-4" /></button>}
            </div>
          </div>
          {!isConnected && <Alert kind="warning">{PLATFORM_LABELS[form.platform]} isn't connected yet – you can save/schedule now and connect the channel before the publish time, or copy the text and post manually.</Alert>}
          {needsImage && <Alert kind="info">Instagram requires an image – attach a creative.</Alert>}
        </div>

        <div className="space-y-3 md:col-span-2">
          <label className="label">Image</label>
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
            {form.creative_url ? <img src={form.creative_url} alt="" className="w-full object-contain" /> : <div className="flex h-40 items-center justify-center text-xs text-slate-400">No image attached</div>}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary px-3 py-1.5 text-xs" onClick={() => setStudio(true)}><ImagePlus className="h-3.5 w-3.5" /> Create / pick</button>
            {form.creative_url && <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setForm({ ...form, creative_id: null, creative_url: '' })}>Remove</button>}
          </div>
          {(library.data ?? []).length > 0 && (
            <div className="grid grid-cols-4 gap-1.5">
              {(library.data ?? []).slice(0, 8).map((c) => (
                <button key={c.id} onClick={() => setForm({ ...form, creative_id: c.id, creative_url: c.url })} className={clsx('overflow-hidden rounded-md border', form.creative_id === c.id ? 'border-brand-500 ring-2 ring-brand-200' : 'border-slate-200')}><img src={c.url} alt="" className="aspect-square w-full object-cover" /></button>
              ))}
            </div>
          )}
          <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
            <div className="mb-1 flex items-center justify-between font-semibold text-slate-700">Preview <button className="btn-ghost px-1.5 py-0.5" onClick={() => { void navigator.clipboard.writeText(fullText); toast.push('success', 'Copied') }}><Copy className="h-3 w-3" /></button></div>
            <p className="whitespace-pre-line">{fullText || '…'}</p>
          </div>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" disabled={!form.content.trim() || save.isPending} onClick={() => save.mutate('draft')}>{save.isPending && <Spinner />} Save draft</button>
          <button className="btn-secondary" disabled={!form.content.trim() || !form.scheduled_for || save.isPending || over} onClick={() => save.mutate('scheduled')}><CalendarClock className="h-4 w-4" /> Schedule</button>
          <button className="btn-primary" disabled={!form.content.trim() || !isConnected || publish.isPending || over || needsImage} onClick={() => publish.mutate()}>{publish.isPending ? <Spinner /> : <Send className="h-4 w-4" />} Publish now</button>
        </div>
      </div>

      <Modal open={studio} onClose={() => setStudio(false)} title="Creative studio" wide>
        <CreativeStudio siteId={siteId} initial={{ headline: form.topic || form.content.split('\n')[0].slice(0, 80) }} onPick={(c: Creative) => { setForm((f) => ({ ...f, creative_id: c.id, creative_url: c.url })); setStudio(false) }} />
      </Modal>
    </Modal>
  )
}
