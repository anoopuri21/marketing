# Architecture

```
┌──────────────┐   /api (proxy in dev, same origin in prod)   ┌──────────────────────────────┐
│ React SPA    │ ───────────────────────────────────────────▶ │ FastAPI (uvicorn)            │
│ Vite + TS    │ ◀─────────────────────────────────────────── │  routers → services → models │
└──────────────┘                                              │  APScheduler tick (60s)      │
                                                              └──────┬──────────┬────────────┘
                                                                     │          │
                                       ┌─────────────────────────────┘          └─────────────────┐
                                       ▼                                                          ▼
                              SQLite / PostgreSQL                                   External providers (all optional)
                              (SQLAlchemy async)                                    · OpenAI / Anthropic (AI)
                                                                                    · SerpAPI (Google ranks)
                                                                                    · SMTP (reports)
                                                                                    · target websites (crawler)
```

## Request flow: "connect a website"

1. `POST /api/websites` normalises the URL, creates the `Website` (with a verification token) and an `Audit(status=queued)`, then schedules `run_audit` as a background task.
2. `run_audit` → `crawl_site` (async BFS crawler, sitemap + robots + llms.txt + protocol variants, bounded by `CRAWL_MAX_PAGES` and a concurrency semaphore).
3. `analyze` runs the rule packs (`analyzers.py`) → issues + category scores + overall score.
4. `generate_audit_insights` asks the configured LLM for an executive summary, quick wins, priorities, AEO tips, content ideas and keyword themes; falls back to deterministic templates when no provider is configured or the call fails.
5. Results are persisted (`audits`, `audit_pages`, `audit_issues`), the website's denormalised `last_score` updated, and `_sync_tasks` creates/auto-resolves tasks on the planning board.

## Scheduler

`services/scheduler.py` runs one `tick` every `SCHEDULER_TICK_SECONDS`:

- **Reports** — `ReportSchedule.next_run_at <= now` → optional fresh audit → render `report_email.html` → deliver via mailer backend → record `ReportRun` → compute the next run in the schedule's timezone.
- **Auto audits** — websites whose `last_audit_at` is older than `AUTO_AUDIT_INTERVAL_DAYS` (max 5 per tick).
- On startup, stale `queued/running` audits are re-run (or failed if older than 2h).

For multi-instance deployments run the scheduler on a single instance (`SCHEDULER_ENABLED=false` elsewhere) or move the tick to a worker.

## Extending

| Want to… | Touch |
| --- | --- |
| Add an audit check | `services/audit/analyzers.py` — append an `Issue` in the right category; scoring adapts automatically |
| Add an AI provider | `services/ai/provider.py` — implement `_<name>()` and map it in `complete_text` + `Settings.resolved_ai_provider` |
| Add a SERP / rank provider | `services/rank_tracker.py` — add a `_<name>_lookup()` and branch in `check_keyword` |
| Add an integration | `api/misc.py::SUPPORTED_INTEGRATIONS` (+ a sync service in phase 2) |
| Change the email | `templates/report_email.html` (inline-CSS, email-client safe) |

## Security notes

- Passwords hashed with bcrypt; JWT (HS256) with `SECRET_KEY` — set a long random value in production.
- Every website-scoped route resolves the site through the caller's workspace (`OwnedWebsite` dependency) → tenants are isolated.
- Integration secrets are stored in the DB (JSON) and masked in API responses. Encrypt at rest (KMS / Fernet) before going multi-tenant in production.
- The crawler identifies itself as `RankPilotBot`, follows redirects, times out per request, and never executes JavaScript.
