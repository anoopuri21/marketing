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

- **Integration syncs** — connected Google Search Console / GA4 rows older than `INTEGRATION_SYNC_INTERVAL_HOURS` are refreshed (max 10 per tick; failures are recorded on the row and retried next interval).
- **Due social posts** — `social_posts` with `status=scheduled` and `scheduled_for <= now` (max 10 per tick) are flipped to `publishing` (so a second instance skips them), sent through `services/social/publishers.publish()` for their platform and end as `published` (with `external_id`/`external_url`) or `failed` (with the platform's error, retry from the UI). Posts whose channel was disconnected fail fast.
- **Reports** — `ReportSchedule.next_run_at <= now` → refresh Google integrations → optional fresh audit → render `report_email.html` → deliver via mailer backend → record `ReportRun` → compute the next run in the schedule's timezone.
- **Auto audits** — websites whose `last_audit_at` is older than `AUTO_AUDIT_INTERVAL_DAYS` (max 5 per tick).
- On startup, stale `queued/running` audits are re-run (or failed if older than 2h).

For multi-instance deployments run the scheduler on a single instance (`SCHEDULER_ENABLED=false` elsewhere) or move the tick to a worker.

## Social publishing & creatives

- **Channels** are `Integration` rows (`provider` = facebook | instagram | linkedin | x | webhook) whose `config` holds the credentials; `api/social.py` masks secrets on the way out and `POST …/channels/{platform}/test` performs a lightweight authenticated call.
- **Publishers** (`services/social/publishers.py`) are thin REST clients (Graph API v20, LinkedIn `rest/posts`, X v2, signed webhook) sharing `compose_text()` (content + hashtags + link, per-platform limits). Images are passed by URL, so `PUBLIC_BASE_URL` must be reachable by the networks in production.
- **Planner** (`services/social/planner.py`) builds `{strategy, posts[]}` from website context (industry, location, keyword themes, GSC queries, audit content ideas) — via the LLM when configured, otherwise a deterministic rotation of 10 post types — and `schedule_times()` maps each post to a best-practice local slot starting tomorrow.
- **Creatives** (`services/creatives/`) — `renderer.py` draws 6 template families with Pillow (word-wrapped, auto-fitted text; brand colours; optional logo) in square / landscape / story sizes; `studio.py` persists `Creative` rows and files under `MEDIA_DIR/creatives/<website_id>/`, handles uploads/logos and OpenAI image generation. Files are served at `/media/...` by the API (`main.py`).

## Extending

| Want to… | Touch |
| --- | --- |
| Add an audit check | `services/audit/analyzers.py` — append an `Issue` in the right category; scoring adapts automatically |
| Add an AI provider | `services/ai/provider.py` — implement `_<name>()` and map it in `complete_text` + `Settings.resolved_ai_provider` |
| Add a SERP / rank provider | `services/rank_tracker.py` — add a `_<name>_lookup()` and branch in `check_keyword` |
| Add an integration | `api/integrations.py::SUPPORTED_INTEGRATIONS` + a `sync_<provider>(db, website, integration)` in `services/<provider>/` wired into `_sync()` and `scheduler.process_integration_syncs` |
| Google API access | `services/google/auth.py` — service-account JWT → access token (cached); `search_console.py` / `analytics.py` are thin REST clients + sync functions |
| Change the email | `templates/report_email.html` (inline-CSS, email-client safe) |
| Add a social network | `services/social/publishers.py` — add a `publish_<name>()` + `PLATFORMS` entry (fields, limits, best times); the UI channel form is generated from `GET /api/social/platforms` |
| Add a creative template | `services/creatives/renderer.py` — add `_<name>(spec, size)` and register it in `TEMPLATES`; it appears in the studio automatically |

## Security notes

- Passwords hashed with bcrypt; JWT (HS256) with `SECRET_KEY` — set a long random value in production.
- Every website-scoped route resolves the site through the caller's workspace (`OwnedWebsite` dependency) → tenants are isolated.
- Integration secrets are stored in the DB (JSON) and masked in API responses. Encrypt at rest (KMS / Fernet) before going multi-tenant in production.
- The crawler identifies itself as `RankPilotBot`, follows redirects, times out per request, and never executes JavaScript.
