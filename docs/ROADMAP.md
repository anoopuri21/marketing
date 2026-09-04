# Roadmap

The vision: **one platform, one URL** — everything a business needs to grow online reach (Google ranking,
AI search, social, digital marketing, lead generation) on automation, with scheduled client reporting.

## ✅ Phase 1 — Foundation (this milestone)

- Accounts, workspaces, connect website (URL) + ownership verification
- Audit engine: crawler + 60+ checks in 7 categories (SEO, technical, content, AEO, AI-readiness, performance, social)
- Pluggable AI (OpenAI / Anthropic / rule-based fallback): executive summary, quick wins, 90-day priorities, AEO tips, content ideas, keyword themes
- Keyword tracking (SerpAPI provider) + keyword suggestions
- Planning board: audit → tasks (auto-resolve), AI week-by-week action plan
- Reports: branded HTML email, weekly/monthly schedules per client (timezone aware), send-now, preview, history
- Automation: scheduler ticks every minute; automatic re-audit every N days; fresh audit before each report
- Integrations vault (credentials stored, masked in API)
- **Google Search Console + GA4 sync** (service account JSON, no Google SDK): queries/pages/daily totals with period-over-period deltas, quick-win opportunities (positions 5-20), real positions fed into keyword tracking, GA4 sessions/users/conversions/channels/pages/devices/countries; daily auto-sync + pre-report refresh; Google section in the email report; *Google data* tab + overview snapshot

- **Social publishing autopilot**: channels per website (Facebook Page, Instagram Business, LinkedIn Page, X, generic signed webhook), connection test, drafts → scheduled → published by the scheduler, publish-now / retry / bulk actions, list + calendar views, platform previews
- **AI content planner**: multi-week calendars per platform from audit insights + tracked keywords + Search Console queries (AI or rule-based), best-time scheduling in the site's timezone, one branded graphic per post
- **Creative studio**: brand kit (auto-detected colours, logo), 6 template families × 3 sizes rendered with Pillow (no key needed), AI images (`gpt-image-1`) when configured, uploads; `/media` served by the API

## 🔜 Phase 2 — Data & distribution

1. ~~Google Search Console + GA4 sync~~ ✅ shipped (see above). Follow-ups: OAuth "Sign in with Google" flow as an alternative to service accounts, GSC URL-inspection (index status) per page, Bing Webmaster Tools.
2. ~~Social publishing + creative generation~~ ✅ shipped (see above). Follow-ups: Google Business Profile posts (API access is invite-only), OAuth connect buttons instead of pasting tokens, long-lived token refresh, carousel / video posts, engagement metrics pulled back into reports, comment inbox.
3. **Lead finder**: discover prospects (Google Places / directories / LinkedIn-style sources) by industry + location, score them, outreach templates, pipeline stages (`leads` table already exists).
4. **PDF reports + white-label**: agency logo/colours, custom sender domain, client portal (read-only login per client).
5. **Backlink & competitor module**: competitor audit side-by-side, keyword gap, backlink provider integration.

## Phase 3 — Autopilot

- Auto-fix suggestions as ready-to-paste code (JSON-LD, meta tags, robots, llms.txt) and CMS connectors (WordPress plugin / Shopify app) to apply fixes with one click.
- Content generation pipeline: brief → draft → review → publish to CMS, with internal-link recommendations.
- AI-search visibility tracking: monitor whether ChatGPT / Perplexity / Google AI Overviews cite the domain for tracked queries.
- Alerts (email/WhatsApp/Slack) on ranking drops, site down, score regressions.
- Multi-user workspaces with roles, billing plans (Stripe / Razorpay).

## Engineering follow-ups

- PostgreSQL migrations with Alembic (currently `create_all` for dev)
- Background worker (Celery/RQ/arq) for large crawls; per-tenant crawl limits
- Headless-browser performance checks (Lighthouse / Core Web Vitals via PageSpeed Insights API)
- i18n (Hindi + English UI)
