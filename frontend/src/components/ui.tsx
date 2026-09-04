import clsx from 'clsx'
import { AlertCircle, CheckCircle2, Loader2, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { scoreColor, scoreHex } from '../lib/utils'
import { ToastContext, type ToastKind } from '../hooks/useToast'

// ------------------------------------------------------------ Score ring
export function ScoreRing({ value, size = 96, stroke = 8, label }: { value: number | null | undefined; size?: number; stroke?: number; label?: string }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, value ?? 0))
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={r} stroke="#e2e8f0" strokeWidth={stroke} fill="none" />
          <circle
            cx={size / 2} cy={size / 2} r={r} stroke={scoreHex(value)} strokeWidth={stroke} fill="none" strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c - (pct / 100) * c} style={{ transition: 'stroke-dashoffset .6s ease' }}
          />
        </svg>
        <div className={clsx('absolute inset-0 flex items-center justify-center font-bold', scoreColor(value))} style={{ fontSize: size / 3.6 }}>
          {value === null || value === undefined ? '–' : Math.round(value)}
        </div>
      </div>
      {label && <div className="text-xs font-medium text-slate-500">{label}</div>}
    </div>
  )
}

export function ScoreBar({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-medium text-slate-600">{label}</span>
        <span className={clsx('font-bold', scoreColor(value))}>{value === null || value === undefined ? '–' : Math.round(value)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-2 rounded-full transition-all" style={{ width: `${value ?? 0}%`, background: scoreHex(value) }} />
      </div>
    </div>
  )
}

// ------------------------------------------------------------ Misc
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('h-4 w-4 animate-spin', className)} />
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-3 rounded-2xl bg-brand-50 p-3 text-brand-600">{icon}</div>}
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      {description && <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Stat({ label, value, hint, accent }: { label: string; value: ReactNode; hint?: ReactNode; accent?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={clsx('mt-1 text-2xl font-bold text-slate-900', accent)}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onMouseDown={onClose}>
      <div className={clsx('card max-h-[90vh] w-full overflow-y-auto p-6', wide ? 'max-w-3xl' : 'max-w-lg')} onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Alert({ kind = 'info', children }: { kind?: 'info' | 'error' | 'success' | 'warning'; children: ReactNode }) {
  const styles = {
    info: 'border-sky-200 bg-sky-50 text-sky-800',
    error: 'border-red-200 bg-red-50 text-red-700',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    warning: 'border-amber-200 bg-amber-50 text-amber-800',
  }[kind]
  return <div className={clsx('rounded-xl border px-3 py-2 text-sm', styles)}>{children}</div>
}

// ------------------------------------------------------------ Toasts
interface Toast { id: number; kind: ToastKind; message: string }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, kind, message }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])
  const value = useMemo(() => ({ push }), [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={clsx(
              'pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2 text-sm shadow-lg',
              t.kind === 'success' && 'border-emerald-200 bg-white text-emerald-800',
              t.kind === 'error' && 'border-red-200 bg-white text-red-700',
              t.kind === 'info' && 'border-slate-200 bg-white text-slate-700',
            )}
          >
            {t.kind === 'success' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx('badge', className)}>{children}</span>
}
