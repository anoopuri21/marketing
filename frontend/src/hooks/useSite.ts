import { useOutletContext } from 'react-router-dom'
import type { AuditSummary, Website } from '../lib/api'

/** Data shared by `WebsiteLayout` with every website tab through the router outlet. */
export interface SiteCtx { site: Website; audits: AuditSummary[]; latestCompleted: AuditSummary | undefined; running: boolean }

export function useSite(): SiteCtx {
  return useOutletContext<SiteCtx>()
}
