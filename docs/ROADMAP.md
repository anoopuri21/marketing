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

## 🔜 Phase 2 — Data & distribution

1. **Google Search Console + GA4 sync** (service account / OAuth): real clicks, impressions, CTR, positions per query & page → replaces/complements SerpAPI; "pages ranking 5-20" opportunities in reports.
2. **Social publishing**: connect Facebook Page, Instagram Business, LinkedIn Page, X, Google Business Profile; content calendar; scheduled publishing from `social_posts`; AI captions + hashtags; **creative generation** (image templates + AI images) for posts.
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
