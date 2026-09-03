import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bot, Globe, LayoutDashboard, LogOut, Menu, Plus, Settings2, X } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { System, Websites } from '../lib/api'
import { useAuth } from '../lib/auth'
import { scoreBg } from '../lib/utils'

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
        <svg viewBox="0 0 64 64" className="h-5 w-5"><path d="M14 44 L26 30 L34 38 L50 18" fill="none" stroke="currentColor" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" /><circle cx="50" cy="18" r="6" fill="#a5b4fc" /></svg>
      </div>
      {!compact && <span className="text-lg font-bold tracking-tight text-slate-900">RankPilot</span>}
    </div>
  )
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const websites = useQuery({ queryKey: ['websites'], queryFn: Websites.list })
  const status = useQuery({ queryKey: ['system'], queryFn: System.status, staleTime: 60_000 })

  const nav = (
    <nav className="flex flex-1 flex-col gap-1">
      <NavLink to="/" end className={({ isActive }) => clsx('nav-link', isActive && 'active')} onClick={() => setOpen(false)}>
        <LayoutDashboard className="h-4 w-4" /> Dashboard
      </NavLink>
      <div className="mt-4 mb-1 flex items-center justify-between px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Websites</span>
        <button onClick={() => { setOpen(false); navigate('/websites/new') }} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-brand-600" title="Connect website">
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {websites.data?.map((w) => (
        <NavLink key={w.id} to={`/websites/${w.id}`} className={({ isActive }) => clsx('nav-link', isActive && 'active')} onClick={() => setOpen(false)}>
          <span className={clsx('h-2 w-2 shrink-0 rounded-full', scoreBg(w.last_score))} />
          <span className="truncate">{w.name || w.domain}</span>
          {w.last_score !== null && <span className="ml-auto text-xs font-semibold text-slate-400">{Math.round(w.last_score)}</span>}
        </NavLink>
      ))}
      {websites.data?.length === 0 && (
        <button onClick={() => { setOpen(false); navigate('/websites/new') }} className="nav-link border border-dashed border-slate-200 text-slate-500">
          <Globe className="h-4 w-4" /> Connect your first site
        </button>
      )}
      <div className="mt-auto pt-4">
        <NavLink to="/settings" className={({ isActive }) => clsx('nav-link', isActive && 'active')} onClick={() => setOpen(false)}>
          <Settings2 className="h-4 w-4" /> Settings & status
        </NavLink>
        {status.data && (
          <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-[11px] leading-5 text-slate-500">
            <div className="flex items-center gap-1.5"><Bot className="h-3 w-3" /> AI: <b className={status.data.ai_provider === 'none' ? 'text-amber-600' : 'text-emerald-600'}>{status.data.ai_provider}</b></div>
            <div>SERP: <b className={status.data.serp_provider === 'none' ? 'text-amber-600' : 'text-emerald-600'}>{status.data.serp_provider}</b> · Email: <b>{status.data.email_backend}</b></div>
          </div>
        )}
      </div>
    </nav>
  )

  return (
    <div className="flex min-h-full">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-5 lg:flex">
        <div className="mb-6 px-2"><Logo /></div>
        {nav}
        <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-slate-800">{user?.full_name || user?.email}</div>
            <div className="truncate text-xs text-slate-400">{user?.email}</div>
          </div>
          <button onClick={logout} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" title="Log out"><LogOut className="h-4 w-4" /></button>
        </div>
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-white px-4 py-5 shadow-xl">
            <div className="mb-6 flex items-center justify-between px-2"><Logo /><button onClick={() => setOpen(false)}><X className="h-5 w-5 text-slate-500" /></button></div>
            {nav}
            <button onClick={logout} className="btn-ghost mt-4 justify-start"><LogOut className="h-4 w-4" /> Log out</button>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-slate-600 hover:bg-slate-100"><Menu className="h-5 w-5" /></button>
          <Logo />
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
