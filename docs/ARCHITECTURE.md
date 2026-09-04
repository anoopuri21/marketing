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

## Layers & conventions

```
app/api/*        HTTP only: auth deps (`DB`, `CurrentUser`, `OwnedWebsite`), pydantic I/O, calls one service, commits.
app/services/*   Business rules. No FastAPI imports. Raise `app.core.errors` (NotFoundError 404, ValidationError 400,
                 ConflictError 409, UpstreamError 502) – `main.py` maps them to JSON `{detail, request_id}`.
app/models       SQLAlchemy entities.            app/schemas   Pydantic response/request models.
app/core         config (+ production guard), database (`session_scope` for background work), security,
                 time (`utcnow()`, `aware()`, `is_past()`), errors, logging (request-id middleware).
```

- **Time**: everything is UTC. SQLite returns naive datetimes → always wrap DB values with `aware()` before comparing.
- **Errors**: services never raise `HTTPException`; unexpected exceptions become a 500 with a `request_id` (full trace in logs, message hidden in production).
- **Request ids**: every response carries `X-Request-ID` (incoming header honoured); log lines include it. Requests slower than 2s are logged.
- **Background work**: use FastAPI `BackgroundTasks` with a service function that opens its own `session_scope()` (e.g. `leads.service.qualify_leads_in_background`), never the request session.
- **Config safety**: `ENVIRONMENT=production` refuses to boot with the default `SECRET_KEY` (or < 32 chars) or `CORS_ORIGINS=*`.
- **Quality gates**: `ruff` + `mypy` (backend, `pyproject.toml`), `oxlint` + `tsc` (frontend). All at zero; keep them there.

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
- **Lead qualification** — `leads` without `qualified_at` (and no previous error) get a mini audit + pitch, `LEAD_QUALIFY_PER_TICK` per tick. The API also queues freshly discovered / imported leads as FastAPI background tasks so scores appear within seconds; the tick is the safety net.
- On startup, stale `queued/running` audits are re-run (or failed if older than 2h).

For multi-instance deployments run the scheduler on a single instance (`SCHEDULER_ENABLED=false` elsewhere) or move the tick to a worker.

## Social publishing & creatives

- **Channels** are `Integration` rows (`provider` = facebook | instagram | linkedin | x | webhook) whose `config` holds the credentials; `services/social/service.py` (channel upsert/masking, post state machine, calendar persistence) does the work and `api/social.py` is a thin router. `POST …/channels/{platform}/test` calls `publishers.verify_channel()` for a lightweight authenticated call.
- **Publishers** (`services/social/publishers.py`) are thin REST clients (Graph API v20, LinkedIn `rest/posts`, X v2, signed webhook) sharing `compose_text()` (content + hashtags + link, per-platform limits). Images are passed by URL, so `PUBLIC_BASE_URL` must be reachable by the networks in production.
- **Planner** (`services/social/planner.py`) builds `{strategy, posts[]}` from website context (industry, location, keyword themes, GSC queries, audit content ideas) — via the LLM when configured, otherwise a deterministic rotation of 10 post types — and `schedule_times()` maps each post to a best-practice local slot starting tomorrow.
- **Creatives** (`services/creatives/`) — `renderer.py` draws 6 template families with Pillow (word-wrapped, auto-fitted text; brand colours; optional logo) in square / landscape / story sizes; `studio.py` persists `Creative` rows and files under `MEDIA_DIR/creatives/<website_id>/`, handles uploads/logos and OpenAI image generation. Files are served at `/media/...` by the API (`main.py`).

## Lead finder

- **Sources** (`services/leads/sources.py`) — `discover(query, location, mode)` fans out to SerpAPI `google_maps` (local businesses, paginated) and/or `google` organic results (companies ranking for the service), filters directories / social networks (`EXCLUDED_HOSTS`) and collapses duplicate hosts. `LEAD_PROVIDER=demo` (default without a key) returns deterministic sample prospects on RFC 2606 `example.*` domains, which the qualifier recognises and scores with a deterministic pseudo-audit instead of crawling.
- **Qualifier** (`services/leads/qualifier.py`) — re-uses `crawl_site` + `analyze` with a 3-page budget, maps audit facts/issues onto a **gap catalogue** (label, what to pitch, weight) and computes the opportunity score: `0.5 × (100 − website_score)` + gap weights (capped) + listing signals; no website / unreachable site ⇒ top of the list.
- **Pitch** (`services/leads/pitch.py`) — `write_pitch()` builds the angle from the top gaps, then asks the LLM for JSON (email, WhatsApp, follow-ups) or falls back to the rule-based writer. Regenerable per tone.
- **Service / API** (`services/leads/service.py`, `api/leads.py`) — dedupe keys (place_id, host, company+location), campaign id per search (`find-YYYYMMDD-HHMMSS`), status transitions with an activity timeline, follow-up scheduling (first follow-up day comes from the pitch cadence), bulk actions, CSV import/export. Everything is scoped to the owning workspace via `OwnedWebsite`.

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
| Add a lead source | `services/leads/sources.py` — return `Prospect` dicts from a new `async def <name>_search()` and branch in `discover()`; add the provider name to `Settings.lead_provider` |
| Add a sellable gap | `services/leads/qualifier.py` — add to `GAP_CATALOGUE` (+ map the analyzer issue code in `ISSUE_TO_GAP` or detect it from facts in `gaps_from_analysis`) |

## Security notes

- Passwords hashed with bcrypt; JWT (HS256) with `SECRET_KEY` — set a long random value in production (enforced: the app refuses to start in `ENVIRONMENT=production` with the default key or `CORS_ORIGINS=*`).
- Every website-scoped route resolves the site through the caller's workspace (`OwnedWebsite` dependency) → tenants are isolated.
- Integration secrets are stored in the DB (JSON) and masked in API responses. Encrypt at rest (KMS / Fernet) before going multi-tenant in production.
- The crawler identifies itself as `RankPilotBot`, follows redirects, times out per request, and never executes JavaScript.
