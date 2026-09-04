import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useOutletContext } from 'react-router-dom'
import Layout from './components/Layout'
import { Spinner, ToastProvider } from './components/ui'
import { AuthProvider } from './lib/auth'
import { useAuth } from './lib/authContext'
import { LoginPage, RegisterPage } from './pages/AuthPages'
import DashboardPage from './pages/DashboardPage'
import NewWebsitePage from './pages/NewWebsitePage'
import SettingsPage from './pages/SettingsPage'
import WebsiteLayout from './pages/website/WebsiteLayout'

// Website tabs are code-split: each is its own chunk (recharts lives only in the tabs that chart).
const OverviewTab = lazy(() => import('./pages/website/OverviewTab'))
const IssuesTab = lazy(() => import('./pages/website/IssuesTab'))
const KeywordsTab = lazy(() => import('./pages/website/KeywordsTab'))
const GoogleTab = lazy(() => import('./pages/website/GoogleTab'))
const PlanTab = lazy(() => import('./pages/website/PlanTab'))
const ContentTab = lazy(() => import('./pages/website/ContentTab'))
const LeadsTab = lazy(() => import('./pages/website/LeadsTab'))
const ReportsTab = lazy(() => import('./pages/website/ReportsTab'))
const SettingsTab = lazy(() => import('./pages/website/SettingsTab'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
})

const Loading = () => <div className="flex h-full items-center justify-center py-16"><Spinner className="h-6 w-6 text-brand-600" /></div>

function RequireAuth() {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loading />
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return <Outlet />
}

function LazyOutlet() {
  const ctx = useOutletContext() // forward WebsiteLayout's SiteCtx through the pathless route
  return <Suspense fallback={<Loading />}><Outlet context={ctx} /></Suspense>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route element={<RequireAuth />}>
                <Route element={<Layout />}>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/websites/new" element={<NewWebsitePage />} />
                  <Route path="/websites/:id" element={<WebsiteLayout />}>
                    <Route element={<LazyOutlet />}>
                      <Route index element={<OverviewTab />} />
                      <Route path="issues" element={<IssuesTab />} />
                      <Route path="audits/:auditId" element={<IssuesTab />} />
                      <Route path="keywords" element={<KeywordsTab />} />
                      <Route path="google" element={<GoogleTab />} />
                      <Route path="plan" element={<PlanTab />} />
                      <Route path="content" element={<ContentTab />} />
                      <Route path="leads" element={<LeadsTab />} />
                      <Route path="reports" element={<ReportsTab />} />
                      <Route path="settings" element={<SettingsTab />} />
                    </Route>
                  </Route>
                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}
