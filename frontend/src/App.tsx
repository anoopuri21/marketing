import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { Spinner, ToastProvider } from './components/ui'
import { AuthProvider, useAuth } from './lib/auth'
import { LoginPage, RegisterPage } from './pages/AuthPages'
import DashboardPage from './pages/DashboardPage'
import NewWebsitePage from './pages/NewWebsitePage'
import SettingsPage from './pages/SettingsPage'
import ContentTab from './pages/website/ContentTab'
import LeadsTab from './pages/website/LeadsTab'
import IssuesTab from './pages/website/IssuesTab'
import KeywordsTab from './pages/website/KeywordsTab'
import GoogleTab from './pages/website/GoogleTab'
import OverviewTab from './pages/website/OverviewTab'
import PlanTab from './pages/website/PlanTab'
import ReportsTab from './pages/website/ReportsTab'
import SettingsTab from './pages/website/SettingsTab'
import WebsiteLayout from './pages/website/WebsiteLayout'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
})

function RequireAuth() {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="flex h-full items-center justify-center"><Spinner className="h-6 w-6 text-brand-600" /></div>
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return <Outlet />
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
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}
