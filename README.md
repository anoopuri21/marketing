# RankPilot — website growth autopilot

Connect any website by URL and RankPilot audits it for **SEO, AEO (answer-engine optimisation), AI-search
readiness, performance and social signals**, tracks Google rankings, turns findings into a week-by-week plan,
and emails clients a branded **weekly / monthly report** on schedule — fully automated.

> Business goal: make it easy for any website to grow online reach — especially Google ranking — from one
> platform, with everything on automation.

## What's in this milestone (v0.1 – foundation)

| Module | Status | Notes |
| --- | --- | --- |
| Accounts & workspaces | ✅ | JWT auth, workspace per client/agency |
| Connect website + ownership verification | ✅ | Meta tag / HTML file / DNS TXT |
| Audit engine (crawler + 60+ checks) | ✅ | 7 categories: on-page SEO, technical, content, AEO, AI-readiness, performance, social |
| AI insights, keyword ideas, action plans, social drafts | ✅ | Pluggable OpenAI / Anthropic; rule-based fallback works with **no key** |
| Keyword rank tracking | ✅ (provider-gated) | Live positions via SerpAPI when `SERPAPI_KEY` is set |
| Planning board (auto-tasks from audits) | ✅ | Tasks auto-resolve when the issue disappears in a later audit |
| Scheduled email reports (weekly / monthly, timezone aware) | ✅ | SMTP delivery; file outbox in dev |
| Automatic re-audits | ✅ | Every 7 days per site (configurable) |
| Integrations vault (GSC, GA4, GBP, FB, IG, LinkedIn, X) | 🟡 | Credentials stored, live sync in phase 2 |
| Social publishing, lead finder | 🔜 | Data model ready (`social_posts`, `leads`), see [ROADMAP](docs/ROADMAP.md) |

## Tech stack

- **Backend:** Python 3.11 · FastAPI · SQLAlchemy 2 (async) · SQLite (dev) / PostgreSQL (prod) · APScheduler · httpx + BeautifulSoup crawler · Jinja2 email templates
- **Frontend:** React 19 · TypeScript · Vite · Tailwind CSS v4 · TanStack Query · Recharts
- **AI:** provider-agnostic client (`backend/app/services/ai/provider.py`)

## Quick start

```bash
./scripts/setup.sh          # creates backend/.venv, installs deps, copies backend/.env.example → .env
./scripts/dev.sh            # API on :8000, web app on :5173 (Vite proxies /api → API)
./scripts/seed_demo.sh      # optional: demo account (demo@example.com / demo1234) + a connected site
```

Open <http://localhost:5173>, register, paste a URL — the first audit runs immediately.
API docs: <http://localhost:8000/docs>.

### Configuration (`backend/.env`)

Everything is optional. Without keys the platform still runs end-to-end using rule-based logic.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | AI-written executive summaries, quick wins, plans, keyword ideas, social copy |
| `SERPAPI_KEY` | Live Google positions for tracked keywords |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Deliver scheduled reports to client inboxes (otherwise saved to `backend/data/outbox/`) |
| `DATABASE_URL` | Default SQLite; use `postgresql+asyncpg://…` in production |
| `CRAWL_MAX_PAGES`, `AUTO_AUDIT_INTERVAL_DAYS`, `SCHEDULER_TICK_SECONDS` | Crawl depth and automation cadence |

See [`backend/.env.example`](backend/.env.example) for the full list.

## Project layout

```
backend/
  app/
    api/            # FastAPI routers: auth, websites, audits, keywords, tasks/plan, reports, misc
    core/           # config, database, security, shared HTTP/TLS helpers
    models/         # SQLAlchemy models (users, workspaces, websites, audits, keywords, tasks, reports, integrations, social_posts, leads)
    schemas/        # Pydantic request/response models
    services/
      audit/        # crawler.py (async BFS crawler) · analyzers.py (rules + scoring) · engine.py (orchestration)
      ai/           # provider.py (OpenAI/Anthropic) · insights.py (summaries, keywords, plans, social drafts + fallbacks)
      reports/      # generator.py (HTML report) · mailer.py (smtp | file | console)
      rank_tracker.py, scheduler.py, verification.py
    templates/      # report_email.html
  tests/            # pytest: analyzers, scheduler, full API flow (23 tests)
frontend/
  src/pages/        # Dashboard, connect website, website workspace (Overview · Issues & pages · Keywords · Plan · Content & social · Reports · Settings)
  src/lib/          # typed API client, auth context, helpers
scripts/            # setup.sh · dev.sh · seed_demo.sh
docs/               # ROADMAP.md · ARCHITECTURE.md
```

## How the audit scores work

Each crawled page (up to `CRAWL_MAX_PAGES`, discovered via links + sitemap) is parsed for titles, meta,
headings, canonicals, structured data, FAQ/HowTo markup, question-style headings, Open Graph, images/alt,
links, contact signals and rendering hints. Site-level checks cover HTTPS/redirects, robots.txt (incl. AI bot
rules), sitemap, `llms.txt`, security headers and TTFB.

Issues carry a severity (critical → info). Every category starts at 100 and loses points per issue with
diminishing penalties for the same issue repeating across pages. The overall score is a weighted blend of the
seven categories, **capped when critical issues remain** so a broken site can never look healthy.

## Testing

```bash
cd backend && .venv/bin/python -m pytest -q     # backend (no network needed)
cd frontend && npm run build                     # type-check + production build
```

## Production deployment

```bash
docker compose up -d --build     # API + built frontend served by the API on :8000
```

Or run `uvicorn app.main:app` behind any reverse proxy and serve `frontend/dist` (the API serves it
automatically when the folder exists). Use PostgreSQL + a persistent volume for `backend/data`.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) — next: Google Search Console / GA4 sync, social publishing &
creative generation, lead finder, PDF reports, white-label client portal.
