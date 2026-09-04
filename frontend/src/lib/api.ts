import axios from 'axios'

export const TOKEN_KEY = 'rankpilot_token'

export const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error?.response?.status === 401 && !location.pathname.startsWith('/login') && !location.pathname.startsWith('/register')) {
      localStorage.removeItem(TOKEN_KEY)
      location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export function errorMessage(err: unknown, fallback = 'Something went wrong'): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(', ') || fallback
  return e?.message || fallback
}

// ---------------------------------------------------------------- types
export interface User { id: number; email: string; full_name: string; created_at: string }
export interface Workspace { id: number; name: string; created_at: string }
export interface Website {
  id: number; workspace_id: number; url: string; domain: string; name: string; industry: string; target_location: string
  description: string; verified: boolean; verified_at: string | null; verification_method: string; verification_token: string
  last_score: number | null; last_audit_at: string | null; auto_audit_enabled: boolean; created_at: string
}
export interface AuditSummary {
  id: number; website_id: number; status: 'queued' | 'running' | 'completed' | 'failed'; trigger: string; error: string
  started_at: string | null; finished_at: string | null; pages_crawled: number
  overall_score: number | null; seo_score: number | null; technical_score: number | null; content_score: number | null
  aeo_score: number | null; ai_readiness_score: number | null; performance_score: number | null; social_score: number | null
  created_at: string
}
export interface AuditIssue {
  id: number; code: string; category: string; severity: 'critical' | 'high' | 'medium' | 'low' | 'info'
  title: string; description: string; recommendation: string; page_url: string; impact: number
}
export interface AuditPage {
  id: number; url: string; status_code: number | null; response_ms: number | null; title: string; meta_description: string
  h1: string; word_count: number; canonical: string; data: Record<string, unknown>
}
export interface Insight { title: string; why?: string; how?: string }
export interface ContentIdea { title: string; type: string; target_query: string }
export interface AuditDetail extends AuditSummary {
  summary: Record<string, unknown>
  ai_insights: {
    provider?: string; executive_summary?: string; quick_wins?: Insight[]; strategic_priorities?: Insight[]
    aeo_recommendations?: string[]; content_ideas?: ContentIdea[]; keyword_themes?: string[]
  }
  issues: AuditIssue[]; pages: AuditPage[]
}
export interface Keyword {
  id: number; term: string; location: string; language: string; intent: string; source: string; created_at: string
  latest_position: number | null; previous_position: number | null; latest_url: string; last_checked_at: string | null
}
export interface KeywordRank { id: number; checked_at: string; position: number | null; url: string; engine: string; provider: string; features: Record<string, unknown> }
export interface KeywordDetail extends Keyword { ranks: KeywordRank[] }
export interface Task {
  id: number; website_id: number; title: string; description: string; category: string
  priority: 'low' | 'medium' | 'high' | 'critical'; status: 'todo' | 'in_progress' | 'done' | 'dismissed'
  source: string; source_issue_code: string; due_date: string | null; completed_at: string | null; page_url: string
  created_at: string; updated_at: string
}
export interface ReportSchedule {
  id: number; website_id: number; recipients: string[]; frequency: 'weekly' | 'monthly'; day_of_week: number; day_of_month: number
  hour: number; minute: number; timezone: string; enabled: boolean; run_fresh_audit: boolean
  next_run_at: string | null; last_run_at: string | null; created_at: string
}
export interface ReportRun {
  id: number; schedule_id: number | null; website_id: number; period_label: string; status: 'pending' | 'sent' | 'failed'
  recipients: string[]; subject: string; delivery_info: string; error: string; created_at: string
}
export interface Integration {
  id: number; provider: string; status: 'connected' | 'pending' | 'error' | 'disconnected' | string; connected_at: string | null
  config: Record<string, unknown>; last_synced_at: string | null; last_error: string; summary: Record<string, unknown>
}
export interface IntegrationMeta { label: string; fields: string[]; optional_fields: string[]; status: 'live' | 'planned'; help: string }
export interface SearchStat { key: string; clicks: number; impressions: number; ctr: number; position: number; prev_clicks: number | null; prev_position: number | null }
export interface SearchPerformance {
  connected: boolean; synced_at: string | null; error: string
  summary: { property?: string; period?: { start: string; end: string; days: number }; matched_keywords?: number
    totals?: { clicks: number; impressions: number; prev_clicks: number; prev_impressions: number; avg_position: number | null; ctr: number }
    daily?: { date: string; clicks: number; impressions: number; position: number }[] }
  queries: SearchStat[]; pages: SearchStat[]; opportunities: SearchStat[]
}
export interface AnalyticsData {
  connected: boolean; synced_at?: string | null; error?: string
  summary?: { property?: string; period?: { start: string; end: string; days: number }
    totals?: { sessions: number; users: number; engaged_sessions: number; conversions: number; avg_session_duration: number; prev_sessions: number; prev_users: number; prev_conversions: number; engagement_rate: number; organic_sessions: number; organic_share: number }
    daily?: { date: string; sessions: number; users: number; conversions: number }[]
    channels?: { channel: string; sessions: number; conversions: number }[]
    top_pages?: { path: string; views: number; sessions: number }[]
    countries?: { country: string; sessions: number }[]
    devices?: { device: string; sessions: number }[] }
}
export interface SystemStatus { app_name: string; environment: string; ai_provider: string; serp_provider: string; email_backend: string; scheduler_enabled: boolean; version: string }
export interface Dashboard {
  websites: number; verified_websites: number; audits_completed: number; open_tasks: number; tracked_keywords: number
  avg_score: number | null; reports_sent: number; recent_audits: AuditSummary[]; upcoming_reports: ReportSchedule[]
  open_issue_counts: Record<string, number>
}
export interface PlanResponse {
  provider: string; strategy_summary: string; created_tasks: number
  weeks: { week: number; theme: string; tasks: { title: string; description: string; category: string; priority: string }[] }[]
}

// ---------------------------------------------------------------- endpoints
export const Auth = {
  login: (email: string, password: string) => api.post<{ access_token: string }>('/auth/login', { email, password }).then((r) => r.data),
  register: (payload: { email: string; password: string; full_name: string; workspace_name?: string }) =>
    api.post<{ access_token: string }>('/auth/register', payload).then((r) => r.data),
  me: () => api.get<{ user: User; workspaces: Workspace[] }>('/auth/me').then((r) => r.data),
}

export const System = {
  status: () => api.get<SystemStatus>('/system/status').then((r) => r.data),
  dashboard: () => api.get<Dashboard>('/dashboard').then((r) => r.data),
}

export const Websites = {
  list: () => api.get<Website[]>('/websites').then((r) => r.data),
  get: (id: number) => api.get<Website>(`/websites/${id}`).then((r) => r.data),
  create: (payload: { url: string; name?: string; industry?: string; target_location?: string; description?: string }) =>
    api.post<Website>('/websites', payload).then((r) => r.data),
  update: (id: number, payload: Partial<Pick<Website, 'name' | 'industry' | 'target_location' | 'description' | 'auto_audit_enabled'>>) =>
    api.patch<Website>(`/websites/${id}`, payload).then((r) => r.data),
  remove: (id: number) => api.delete(`/websites/${id}`),
  verification: (id: number) =>
    api.get<{ token: string; meta_tag: string; dns_record: string; html_file_name: string; html_file_content: string; html_file_url: string }>(`/websites/${id}/verification`).then((r) => r.data),
  verify: (id: number, method: 'auto' | 'meta' | 'dns' | 'file' = 'auto') =>
    api.post<{ verified: boolean; method: string; detail: string }>(`/websites/${id}/verify`, { method }).then((r) => r.data),
}

export const Audits = {
  list: (siteId: number) => api.get<AuditSummary[]>(`/websites/${siteId}/audits`).then((r) => r.data),
  latest: (siteId: number) => api.get<AuditDetail>(`/websites/${siteId}/audits/latest`).then((r) => r.data),
  get: (siteId: number, auditId: number) => api.get<AuditDetail>(`/websites/${siteId}/audits/${auditId}`).then((r) => r.data),
  start: (siteId: number) => api.post<{ audit: AuditSummary; message: string }>(`/websites/${siteId}/audits`).then((r) => r.data),
}

export const Keywords = {
  list: (siteId: number) => api.get<Keyword[]>(`/websites/${siteId}/keywords`).then((r) => r.data),
  add: (siteId: number, terms: string[], location = '', language = 'en') =>
    api.post<Keyword[]>(`/websites/${siteId}/keywords`, { terms, location, language }).then((r) => r.data),
  remove: (siteId: number, kwId: number) => api.delete(`/websites/${siteId}/keywords/${kwId}`),
  detail: (siteId: number, kwId: number) => api.get<KeywordDetail>(`/websites/${siteId}/keywords/${kwId}`).then((r) => r.data),
  checkAll: (siteId: number) => api.post<Keyword[]>(`/websites/${siteId}/keywords/check`).then((r) => r.data),
  suggest: (siteId: number) =>
    api.post<{ provider: string; suggestions: { term: string; intent: string; reason: string }[] }>(`/websites/${siteId}/keywords/suggest`).then((r) => r.data),
}

export const Tasks = {
  list: (siteId: number) => api.get<Task[]>(`/websites/${siteId}/tasks`).then((r) => r.data),
  create: (siteId: number, payload: { title: string; description?: string; category?: string; priority?: Task['priority']; due_date?: string | null }) =>
    api.post<Task>(`/websites/${siteId}/tasks`, payload).then((r) => r.data),
  update: (siteId: number, taskId: number, payload: Partial<Pick<Task, 'title' | 'description' | 'category' | 'priority' | 'status' | 'due_date'>>) =>
    api.patch<Task>(`/websites/${siteId}/tasks/${taskId}`, payload).then((r) => r.data),
  remove: (siteId: number, taskId: number) => api.delete(`/websites/${siteId}/tasks/${taskId}`),
  plan: (siteId: number, horizon_weeks: number, focus: string) => api.post<PlanResponse>(`/websites/${siteId}/plan`, { horizon_weeks, focus }).then((r) => r.data),
}

export const Reports = {
  schedules: (siteId: number) => api.get<ReportSchedule[]>(`/websites/${siteId}/reports/schedules`).then((r) => r.data),
  createSchedule: (siteId: number, payload: Omit<ReportSchedule, 'id' | 'website_id' | 'next_run_at' | 'last_run_at' | 'created_at'>) =>
    api.post<ReportSchedule>(`/websites/${siteId}/reports/schedules`, payload).then((r) => r.data),
  updateSchedule: (siteId: number, id: number, payload: Partial<ReportSchedule>) =>
    api.patch<ReportSchedule>(`/websites/${siteId}/reports/schedules/${id}`, payload).then((r) => r.data),
  deleteSchedule: (siteId: number, id: number) => api.delete(`/websites/${siteId}/reports/schedules/${id}`),
  runs: (siteId: number) => api.get<ReportRun[]>(`/websites/${siteId}/reports/runs`).then((r) => r.data),
  sendNow: (siteId: number, payload: { recipients?: string[]; run_fresh_audit?: boolean; period?: 'weekly' | 'monthly' }) =>
    api.post<ReportRun>(`/websites/${siteId}/reports/send-now`, payload).then((r) => r.data),
  previewUrl: (siteId: number, period: 'weekly' | 'monthly') => `/api/websites/${siteId}/reports/preview?period=${period}`,
  runHtmlUrl: (siteId: number, runId: number) => `/api/websites/${siteId}/reports/runs/${runId}/html`,
}

export const Integrations = {
  catalog: () => api.get<Record<string, IntegrationMeta>>('/integrations/catalog').then((r) => r.data),
  list: (siteId: number) => api.get<Integration[]>(`/websites/${siteId}/integrations`).then((r) => r.data),
  upsert: (siteId: number, provider: string, config: Record<string, string>) =>
    api.put<Integration>(`/websites/${siteId}/integrations`, { provider, config }).then((r) => r.data),
  sync: (siteId: number, provider: string) => api.post<Integration>(`/websites/${siteId}/integrations/${provider}/sync`).then((r) => r.data),
  remove: (siteId: number, provider: string) => api.delete(`/websites/${siteId}/integrations/${provider}`),
  searchPerformance: (siteId: number) => api.get<SearchPerformance>(`/websites/${siteId}/search-performance`).then((r) => r.data),
  analytics: (siteId: number) => api.get<AnalyticsData>(`/websites/${siteId}/analytics`).then((r) => r.data),
}

export const Social = {
  draft: (siteId: number, topic: string, platforms: string[], tone: string) =>
    api.post<{ provider: string; posts: { platform: string; content: string; hashtags?: string[]; image_idea?: string }[] }>(`/websites/${siteId}/social/draft`, { topic, platforms, tone }).then((r) => r.data),
}
