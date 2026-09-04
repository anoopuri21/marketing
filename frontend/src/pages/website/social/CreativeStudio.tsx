import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Download, ImagePlus, Palette, Sparkles, Trash2, Upload, Wand2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Alert, Spinner } from '../../../components/ui'
import { useToast } from '../../../hooks/useToast'
import { Creatives, errorMessage, type Creative, type CreativeSpec } from '../../../lib/api'

const DEFAULT_SPEC: CreativeSpec = { headline: '', subline: '', cta: '', template: 'bold', size: 'square', accent_words: [] }

export default function CreativeStudio({ siteId, onPick, initial }: { siteId: number; onPick?: (c: Creative) => void; initial?: Partial<CreativeSpec> }) {
  const qc = useQueryClient()
  const toast = useToast()
  const templates = useQuery({ queryKey: ['creative-templates', siteId], queryFn: () => Creatives.templates(siteId), staleTime: Infinity })
  const brand = useQuery({ queryKey: ['brand', siteId], queryFn: () => Creatives.brand(siteId) })
  const library = useQuery({ queryKey: ['creatives', siteId], queryFn: () => Creatives.list(siteId) })
  const [spec, setSpec] = useState<CreativeSpec>({ ...DEFAULT_SPEC, ...initial })
  const [preview, setPreview] = useState<string>('')
  const [previewing, setPreviewing] = useState(false)
  const [mode, setMode] = useState<'template' | 'ai'>('template')
  const [prompt, setPrompt] = useState('')
  const [brandForm, setBrandForm] = useState<{ primary: string; secondary: string; style: string } | null>(null)
  const timer = useRef<number | null>(null)
  const objectUrl = useRef<string | null>(null)
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['creatives', siteId] })
  useEffect(() => () => { if (objectUrl.current) URL.revokeObjectURL(objectUrl.current) }, [])
  // `initial` seeds the form once on mount (the studio modal remounts when reopened) – no effect needed.

  // live preview (debounced)
  useEffect(() => {
    if (mode !== 'template') return
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      setPreviewing(true)
      Creatives.previewBlob(siteId, spec).then((blob) => {
        // never do side effects inside a state updater – it runs during render
        const url = URL.createObjectURL(blob)
        if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
        objectUrl.current = url
        setPreview(url)
      }).catch(() => undefined).finally(() => setPreviewing(false))
    }, 350)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [spec, siteId, mode, brand.data?.primary, brand.data?.secondary, brand.data?.logo_url])

  const create = useMutation({
    mutationFn: () => Creatives.create(siteId, spec),
    onSuccess: (c) => { toast.push('success', 'Creative saved to the library'); invalidate(); onPick?.(c) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const createAI = useMutation({
    mutationFn: () => Creatives.createAI(siteId, prompt, spec.size ?? 'square'),
    onSuccess: (c) => { toast.push('success', 'AI image generated'); invalidate(); onPick?.(c) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const upload = useMutation({
    mutationFn: (f: File) => Creatives.upload(siteId, f),
    onSuccess: (c) => { toast.push('success', 'Image uploaded'); invalidate(); onPick?.(c) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const remove = useMutation({ mutationFn: (id: number) => Creatives.remove(siteId, id), onSuccess: invalidate })
  const saveBrand = useMutation({
    mutationFn: () => Creatives.updateBrand(siteId, brandForm!),
    onSuccess: () => { toast.push('success', 'Brand kit saved'); void qc.invalidateQueries({ queryKey: ['brand', siteId] }); setBrandForm(null) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const detect = useMutation({
    mutationFn: () => Creatives.detectBrand(siteId),
    onSuccess: (r) => { toast.push(r.detected ? 'success' : 'info', r.detected ? `Detected ${Object.values(r.colours ?? {}).join(' & ')} from your website` : 'No distinctive colours found on the homepage'); void qc.invalidateQueries({ queryKey: ['brand', siteId] }) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const uploadLogo = useMutation({
    mutationFn: (f: File) => Creatives.uploadLogo(siteId, f),
    onSuccess: () => { toast.push('success', 'Logo added'); void qc.invalidateQueries({ queryKey: ['brand', siteId] }) },
    onError: (e) => toast.push('error', errorMessage(e)),
  })
  const removeLogo = useMutation({ mutationFn: () => Creatives.removeLogo(siteId), onSuccess: () => void qc.invalidateQueries({ queryKey: ['brand', siteId] }) })

  const b = brand.data
  const aiOk = templates.data?.ai_images

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      {/* editor */}
      <div className="space-y-4 lg:col-span-3">
        <div className="card p-5">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2"><ImagePlus className="h-4 w-4 text-brand-600" /><h3 className="font-semibold text-slate-900">Create a post graphic</h3></div>
            <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs">
              <button className={clsx('rounded-md px-3 py-1', mode === 'template' ? 'bg-white shadow-sm' : 'text-slate-500')} onClick={() => setMode('template')}>Branded template</button>
              <button className={clsx('rounded-md px-3 py-1', mode === 'ai' ? 'bg-white shadow-sm' : 'text-slate-500')} onClick={() => setMode('ai')}><Sparkles className="mr-1 inline h-3 w-3" />AI image</button>
            </div>
          </div>
          {mode === 'template' ? (
            <div className="space-y-3">
              <div><label className="label">Headline</label><input className="input" placeholder="e.g. 5 things to check before hiring a web designer" value={spec.headline} onChange={(e) => setSpec({ ...spec, headline: e.target.value })} /></div>
              <div><label className="label">Subline / list (optional)</label><textarea className="input min-h-16" placeholder={'Short supporting line, or a list: 1. Portfolio 2. Speed 3. SEO basics'} value={spec.subline ?? ''} onChange={(e) => setSpec({ ...spec, subline: e.target.value })} /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Call to action (optional)</label><input className="input" placeholder="Read the guide" value={spec.cta ?? ''} onChange={(e) => setSpec({ ...spec, cta: e.target.value })} /></div>
                <div><label className="label">Highlight words</label><input className="input" placeholder="Delhi, free" value={(spec.accent_words ?? []).join(', ')} onChange={(e) => setSpec({ ...spec, accent_words: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} /></div>
              </div>
              <div>
                <label className="label">Template</label>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {(templates.data?.templates ?? []).map((t) => (
                    <button key={t.id} title={t.description} onClick={() => setSpec({ ...spec, template: t.id })} className={clsx('rounded-xl border px-2 py-2 text-xs font-medium transition', spec.template === t.id ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:border-slate-300')}>{t.label}</button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <label className="label">Size</label>
                  <div className="flex gap-1.5">{['square', 'landscape', 'story'].map((s) => <button key={s} onClick={() => setSpec({ ...spec, size: s })} className={clsx('badge px-3 py-1 text-xs capitalize', spec.size === s ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600')}>{s}{s === 'square' ? ' · 1080²' : s === 'landscape' ? ' · 1200×628' : ' · 1080×1920'}</button>)}</div>
                </div>
                <button className="btn-primary" disabled={!spec.headline.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending ? <Spinner /> : <Download className="h-4 w-4" />} Save to library</button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {!aiOk && <Alert kind="warning">AI image generation needs <code className="rounded bg-amber-100 px-1">OPENAI_API_KEY</code> in the backend <code className="rounded bg-amber-100 px-1">.env</code>. Branded templates work without any key.</Alert>}
              <div><label className="label">Describe the image</label><textarea className="input min-h-24" placeholder="Happy family receiving keys to their new apartment, warm evening light, modern Delhi high-rise in the background" value={prompt} onChange={(e) => setPrompt(e.target.value)} /></div>
              <p className="text-xs text-slate-500">We add your brand colours and style automatically and ask for no text in the image (add text with a template instead).</p>
              <div className="flex items-center justify-between">
                <div className="flex gap-1.5">{['square', 'landscape', 'story'].map((s) => <button key={s} onClick={() => setSpec({ ...spec, size: s })} className={clsx('badge px-3 py-1 text-xs capitalize', spec.size === s ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600')}>{s}</button>)}</div>
                <button className="btn-primary" disabled={!aiOk || !prompt.trim() || createAI.isPending} onClick={() => createAI.mutate()}>{createAI.isPending ? <Spinner /> : <Wand2 className="h-4 w-4" />} Generate</button>
              </div>
            </div>
          )}
        </div>

        {/* brand kit */}
        <div className="card p-5">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2"><Palette className="h-4 w-4 text-brand-600" /><h3 className="font-semibold text-slate-900">Brand kit</h3></div>
            <button className="btn-ghost px-2 py-1 text-xs" onClick={() => detect.mutate()} disabled={detect.isPending}>{detect.isPending ? <Spinner /> : <Sparkles className="h-3 w-3" />} Detect from website</button>
          </div>
          {b && (
            <div className="grid gap-3 sm:grid-cols-[auto_1fr]">
              <div className="flex items-center gap-3">
                <div className="flex h-16 w-28 items-center justify-center overflow-hidden rounded-xl border border-dashed border-slate-300 bg-slate-50">
                  {b.logo_url ? <img src={b.logo_url} alt="logo" className="max-h-14 max-w-24 object-contain" /> : <span className="text-[10px] text-slate-400">no logo</span>}
                </div>
                <div className="flex flex-col gap-1 text-xs">
                  <label className="btn-secondary cursor-pointer px-2 py-1"><Upload className="h-3 w-3" /> Logo<input type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadLogo.mutate(f) }} /></label>
                  {b.logo_url && <button className="btn-ghost px-2 py-1 text-red-600" onClick={() => removeLogo.mutate()}>Remove</button>}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <ColorField label="Primary" value={brandForm?.primary ?? b.primary} onChange={(v) => setBrandForm({ primary: v, secondary: brandForm?.secondary ?? b.secondary, style: brandForm?.style ?? b.style })} />
                <ColorField label="Secondary" value={brandForm?.secondary ?? b.secondary} onChange={(v) => setBrandForm({ primary: brandForm?.primary ?? b.primary, secondary: v, style: brandForm?.style ?? b.style })} />
                <div><label className="label">Style (for AI)</label><input className="input" value={brandForm?.style ?? b.style} onChange={(e) => setBrandForm({ primary: brandForm?.primary ?? b.primary, secondary: brandForm?.secondary ?? b.secondary, style: e.target.value })} /></div>
              </div>
            </div>
          )}
          {brandForm && <div className="mt-3 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setBrandForm(null)}>Cancel</button><button className="btn-primary" onClick={() => saveBrand.mutate()} disabled={saveBrand.isPending}>{saveBrand.isPending && <Spinner />} Save brand kit</button></div>}
        </div>
      </div>

      {/* preview + library */}
      <div className="space-y-4 lg:col-span-2">
        <div className="card p-4">
          <div className="mb-2 flex items-center justify-between text-xs text-slate-500"><span>Live preview</span>{previewing && <Spinner className="h-3 w-3" />}</div>
          <div className="flex items-center justify-center rounded-xl bg-slate-100 p-2">
            {preview ? <img src={preview} alt="preview" className={clsx('rounded-lg shadow', spec.size === 'story' ? 'max-h-96' : 'w-full')} /> : <div className="py-16 text-xs text-slate-400">Type a headline to see the preview</div>}
          </div>
        </div>
        <div className="card p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold text-slate-900">Library ({library.data?.length ?? 0})</span>
            <label className="btn-secondary cursor-pointer px-2 py-1 text-xs"><Upload className="h-3 w-3" /> Upload<input type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f) }} /></label>
          </div>
          {(library.data ?? []).length === 0 ? <p className="py-6 text-center text-xs text-slate-400">Saved creatives appear here and can be attached to any post.</p> : (
            <div className="grid max-h-[28rem] grid-cols-3 gap-2 overflow-y-auto pr-1">
              {(library.data ?? []).map((c) => (
                <div key={c.id} className="group relative overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
                  <img src={c.url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-slate-900/60 opacity-0 transition group-hover:opacity-100">
                    {onPick && <button className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-800" onClick={() => onPick(c)}>Use</button>}
                    <a className="rounded-md bg-white/90 px-2 py-0.5 text-[11px] text-slate-700" href={c.url} download target="_blank" rel="noreferrer">Download</a>
                    <button className="rounded-md bg-red-500 px-2 py-0.5 text-[11px] text-white" onClick={() => remove.mutate(c.id)}><Trash2 className="inline h-3 w-3" /></button>
                  </div>
                  <span className="absolute left-1 top-1 rounded bg-white/90 px-1 text-[9px] uppercase text-slate-600">{c.kind === 'template' ? c.template : c.kind}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex items-center gap-2">
        <input type="color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : '#4F46E5'} onChange={(e) => onChange(e.target.value.toUpperCase())} className="h-9 w-10 cursor-pointer rounded-lg border border-slate-200 bg-white p-0.5" />
        <input className="input font-mono text-xs uppercase" value={value} onChange={(e) => onChange(e.target.value)} />
      </div>
    </div>
  )
}
