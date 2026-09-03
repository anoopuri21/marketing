import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Logo } from '../components/Layout'
import { Alert, Spinner } from '../components/ui'
import { errorMessage } from '../lib/api'
import { useAuth } from '../lib/auth'

function Shell({ title, subtitle, children, footer }: { title: string; subtitle: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="flex min-h-full">
      <div className="hidden w-1/2 flex-col justify-between bg-gradient-to-br from-brand-700 via-brand-600 to-violet-600 p-12 text-white lg:flex">
        <Logo />
        <div>
          <h2 className="text-4xl font-bold leading-tight">Put your website's growth on autopilot.</h2>
          <p className="mt-4 max-w-md text-brand-100">
            Connect a URL and RankPilot audits SEO, answer-engine (AEO) and AI-search readiness, tracks Google rankings,
            plans the work week by week, and emails your clients a report on schedule.
          </p>
          <ul className="mt-8 space-y-2 text-sm text-brand-100">
            <li>✓ 60+ automated checks across 7 categories</li>
            <li>✓ AI-generated action plans & content ideas</li>
            <li>✓ Weekly / monthly branded email reports</li>
          </ul>
        </div>
        <div className="text-xs text-brand-200">RankPilot · Website growth platform</div>
      </div>
      <div className="flex w-full items-center justify-center p-6 lg:w-1/2">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
          <div className="mt-6">{children}</div>
          <div className="mt-6 text-sm text-slate-500">{footer}</div>
        </div>
      </div>
    </div>
  )
}

export function LoginPage() {
  const { user, login, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: string } }
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!loading && user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password)
      navigate(location.state?.from || '/', { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Login failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell title="Welcome back" subtitle="Sign in to your RankPilot workspace." footer={<>New here? <Link to="/register" className="font-semibold text-brand-600">Create an account</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert kind="error">{error}</Alert>}
        <div><label className="label">Email</label><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></div>
        <div><label className="label">Password</label><input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
        <button className="btn-primary w-full" disabled={busy}>{busy && <Spinner />} Sign in</button>
      </form>
    </Shell>
  )
}

export function RegisterPage() {
  const { user, register, loading } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', email: '', password: '', workspace_name: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!loading && user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await register(form)
      navigate('/websites/new', { replace: true })
    } catch (err) {
      setError(errorMessage(err, 'Registration failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell title="Create your account" subtitle="Free to start. Connect your first website in under a minute." footer={<>Already have an account? <Link to="/login" className="font-semibold text-brand-600">Sign in</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert kind="error">{error}</Alert>}
        <div><label className="label">Your name</label><input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required autoFocus /></div>
        <div><label className="label">Email</label><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></div>
        <div><label className="label">Password</label><input className="input" type="password" minLength={6} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></div>
        <div><label className="label">Workspace / agency name <span className="font-normal normal-case text-slate-400">(optional)</span></label><input className="input" value={form.workspace_name} onChange={(e) => setForm({ ...form, workspace_name: e.target.value })} placeholder="e.g. Acme Digital" /></div>
        <button className="btn-primary w-full" disabled={busy}>{busy && <Spinner />} Create account</button>
      </form>
    </Shell>
  )
}
