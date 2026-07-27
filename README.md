<div align="center">

# 🧭 RouteIQ (RoutingBridge)

### An explainable, self-auditing multi-LLM routing platform.

**Classifies every prompt, routes it to the cheapest capable model, records a full decision audit trail, learns from historical outcomes, and offline-investigates its own routing history for optimization opportunities — all advisory, all human-approved.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](requirements.txt)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)
[![Tests](https://img.shields.io/badge/tests-57%20passing-brightgreen)](#testing)

[Overview](#overview) • [Architecture](#architecture) • [Features](#features) • [API](#api-overview) • [Running locally](#running-locally) • [Deployment](#deployment) • [Design decisions](#design-decisions) • [Roadmap](#future-roadmap)

</div>

---

## Overview

### Problem statement

Most applications that call an LLM pick one model and use it for every
request — a one-line arithmetic question and a multi-step architecture
discussion both hit the same (usually expensive) model. That's simple to
build but wastes money on the majority of prompts that don't need a
frontier model, and it gives you no record of *why* a particular answer
came from a particular model, no way to tell if routing decisions are
actually any good over time, and no mechanism to improve them beyond
manually re-reading logs.

### What RouteIQ does about it

1. **Routes intelligently** — a cheap classifier judges each prompt's
   difficulty and hands it to the cheapest model that can do it justice,
   escalating automatically when its own confidence is low.
2. **Explains every decision** — every routed request produces a
   `DecisionCard`: which tier, which provider/model, why, and whether a
   better alternative has been observed historically.
3. **Persists decision intelligence, not just logs** — a normalized
   schema (not one flat log table) makes "how does provider X perform on
   task type Y" a direct query, not a log-scraping exercise.
4. **Learns, but never routes on its own** — a learning layer aggregates
   historical outcomes into patterns and recommendations. Nothing it
   produces is ever applied automatically; a human reviews and, if
   convinced, edits config and bumps a policy version.
5. **Audits itself offline** — a deterministic (no-LLM) investigation
   pipeline periodically reviews routing history for degraded models,
   cost anomalies, and whether existing recommendations still hold up
   against live data — producing a structured, persisted report.

## Architecture

Full diagrams (request lifecycle, routing flow, decision flow, analytics
flow, learning flow, agent flow) live in **[`docs/architecture.md`](docs/architecture.md)**.
The short version:

```
Prompt → Classifier → Routing Engine → Provider → Cost Estimator
       → Quality Verifier → decision_service.record() (one transaction)
       → { requests, routing_decisions, execution_results, quality_results }
                                │
                                ▼
       routing_learning.refresh()  →  routing_patterns, optimization_recommendations
                                │                         │
                                ▼                         ▼
       routing_agent.investigate() ←──────────────────────┘
                                │
                                ▼
                     investigation_reports
```

One rule holds across every layer above the first line: **nothing
downstream of a routing decision can change how future decisions are
made, except a human editing `routing.yaml`.** See
[Design decisions](#design-decisions).

## Features

- 💸 **Cuts model spend automatically** — simple prompts go to a fast,
  cheap model; hard prompts escalate to a stronger one, with the
  escalation reason attached to the response.
- 🧠 **LLM-judged difficulty, not keyword rules** — a lightweight
  classifier returns a structured verdict (tier, task type, reasoning
  level, confidence), with a heuristic fallback if the classifier call
  itself fails.
- 🧭 **Explainable by construction** — `GET /routing/decision/{id}`
  returns a deterministic, reproducible `DecisionCard`: reasoning steps,
  candidate models, and whether a learned recommendation applies.
- 📊 **Real analytics, not a dashboard over a log table** — provider,
  model, and task-type performance, tier distribution, and daily
  cost/latency trends, computed over a normalized schema.
- 🧪 **Quality verification** — an LLM judge grades BASIC/STANDARD-tier
  answers, feeding pass-rate metrics into every layer above.
- 🔁 **Learns without auto-applying** — `POST /analytics/refresh`
  recomputes patterns and generates advisory-only recommendations,
  explicitly triggered, never on the request path.
- 🕵️ **Offline optimization agent** — `POST /agent/investigate` runs a
  deterministic, no-LLM pipeline that finds degraded models, cost
  anomalies, and re-validates recommendations against live data.
- 🔌 **Provider-agnostic** — native Google Gemini plus OpenRouter
  (Mistral, DeepSeek, Qwen, Llama, and more through one gateway); adding
  a provider is one class and one config entry.
- ⚙️ **Config-driven routing policy** — which model serves which tier,
  and learning thresholds, live in `config/routing.yaml`; no redeploy to
  change routing behavior.

## Screenshots

> _Streamlit UI: chat, history, and stats. (Analytics/decision/agent
> endpoints are currently API-only — see [Roadmap](#future-roadmap).)_

`docs/screenshots/chat.png` · `docs/screenshots/history.png` · `docs/screenshots/stats.png`
*(placeholders — add real screenshots here)*

## API overview

| Endpoint | Method | Purpose |
|---|---|---|
| `/chat` | POST | Classify, route, generate, and persist one request |
| `/history` | GET | Paginated past requests |
| `/stats` | GET | Aggregate cost/latency/quality dashboard numbers |
| `/models` | GET | Current routing.yaml/pricing.yaml configuration |
| `/analytics/refresh` | POST | Recompute `routing_patterns` + `optimization_recommendations` |
| `/analytics/routing` | GET | Provider/model/task-type performance, tier distribution, daily trend |
| `/analytics/patterns` | GET | Learned routing patterns |
| `/analytics/recommendations` | GET | Advisory optimization recommendations |
| `/routing/decision/{request_id}` | GET | `DecisionCard` + matching recommendation for one past request |
| `/agent/investigate` | POST | Run the offline investigation pipeline, persist a report |
| `/agent/reports` | GET | List investigation report summaries |
| `/agent/report/{report_id}` | GET | Full investigation report |
| `/health` | GET | Liveness check |

Full request/response schemas are in `backend/schemas/*.py` and served
as OpenAPI docs at `/docs` when the server is running.

## Folder structure

```
backend/
  main.py                  # FastAPI app, lifespan, router registration
  database/
    db.py                  # engine/session setup
    models.py               # SQLAlchemy models (all 9 tables, incl. failed_requests)
  routers/                 # thin: validate → call service → return
  schemas/                 # Pydantic request/response contracts
  services/
    classifier_service.py   # LLM-based routing classifier (+ heuristic fallback)
    routing_engine.py        # tier → provider/model, confidence escalation
    quality_verifier.py      # LLM judge for BASIC/STANDARD answers
    decision_service.py       # transactional persistence + DecisionCard reads
    history_service.py / stats_service.py / analytics_service.py  # read-side queries
    routing_learning.py       # pattern/recommendation compute (write-side)
    routing_agent.py          # offline investigation pipeline (write-side)
    investigation_service.py  # investigation report reads
    providers/                # LLMProvider interface + Gemini/OpenRouter adapters
  utils/                    # settings, YAML config loaders, logging
config/
  routing.yaml              # tiers, thresholds, learning config, policy_version
  pricing.yaml               # per-model token pricing
scripts/
  bootstrap_db.py            # explicit table creation + routing_policies seed (not on app startup)
frontend/
  streamlit_app.py            # chat / history / stats UI
deploy/
  start.sh                     # launches uvicorn + streamlit + nginx in one container
  nginx.conf.template          # /api/* -> FastAPI, /* -> Streamlit
Dockerfile                    # single image for local Docker and Render
render.yaml                    # Render Blueprint: one web service
tests/                       # 57 tests, no network calls required
docs/
  architecture.md             # diagrams + data model, current state
  interview-guide.md           # why each design decision was made
  pr1-4 *.md                   # per-PR design rationale, written as each was built
```

## Running locally

```bash
# 1. Get the project
git clone <this-repo>
cd modelpilot

# 2. Install dependencies
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Add your provider keys and database URL
cp .env.example .env
# open .env and paste in GOOGLE_API_KEY, OPENROUTER_API_KEY, and DATABASE_URL
# (see "Database: Postgres/Supabase" below — SQLite also still works for a
# quick local run, no setup required)

# 4. Create tables + seed the active routing policy (once, or after
#    changing routing.yaml's policy_version)
python -m scripts.bootstrap_db

# 5. Start both services
uvicorn backend.main:app --reload &
streamlit run frontend/streamlit_app.py
```

Open **http://localhost:8501** for the UI, or call the API directly:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain why the sky is blue."}'
```

```bash
# after a few /chat calls:
curl -X POST http://localhost:8000/analytics/refresh
curl http://localhost:8000/analytics/recommendations
curl -X POST http://localhost:8000/agent/investigate
```

### Database: Postgres/Supabase (or SQLite for a zero-setup local run)

The app runs on Postgres/Supabase by default in production and works
against SQLite for local dev with zero setup — every model uses plain
SQLAlchemy types, so nothing else in the codebase is database-specific.

**Supabase/Postgres:**

```bash
# .env
DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Get the connection details from your Supabase project's **Settings →
Database → Connection string** (use the **Session pooler** entry, not
the direct `db.<ref>.supabase.co` host — that one is IPv6-only and won't
resolve on IPv4-only networks/containers). The password is shown once at
project creation and isn't retrievable afterward; reset it there if lost.

Schema is managed by SQLAlchemy's `Base.metadata.create_all()` —
idempotent `CREATE TABLE IF NOT EXISTS` DDL, run explicitly by
`scripts/bootstrap_db.py` only, never automatically on app startup (see
`backend/main.py`'s `lifespan` for why: seeding is business data an app
boot shouldn't silently write, and even idempotent DDL is a real DB
round-trip against a remote Postgres on every boot for a schema that
almost never changes). There's no separate migration framework: every
table lives in `backend/database/models.py`, and that file is the single
source of truth for the schema. Adding a column or table is a plain model
change — the next `bootstrap_db` run picks it up.

Row Level Security is enabled on every table, denying all access to the
`anon`/`authenticated` Supabase roles by default (no permissive policies
are defined, deliberately — see "Security" below for why that's correct
for this app, not a placeholder for future policies).

```bash
python -m scripts.bootstrap_db    # create tables + seed the active routing_policies row
```

**SQLite (local dev, no setup):**

```bash
# .env
DATABASE_URL=sqlite:///./modelpilot.db
```

Works identically — `scripts/bootstrap_db.py` creates the schema and
seeds the policy the same way regardless of which database is behind
`DATABASE_URL`.

### Run with Docker

```bash
docker compose up --build
```

One container, one port (`:8080`): FastAPI and Streamlit both run
inside it, with nginx reverse-proxying `/api/*` to FastAPI and
everything else to Streamlit — the same image `render.yaml` deploys.
`DATABASE_URL` comes from `.env` either way; point it at Supabase, or set
it to `sqlite:////app/data/modelpilot.db` to use the mounted `./data`
volume for a local SQLite file instead.

## Deployment

RouteIQ runs as a **single Render Web Service** — one container, one
public URL, one Dockerfile (`./Dockerfile`) — rather than separate
frontend/backend services. That matters specifically on Render's free
tier: each service sleeps independently after inactivity, so two
services meant the frontend often sat waiting on a sleeping backend to
wake up. One service sleeps and wakes as one unit.

```
Public URL
    │
    ▼
  nginx (listens on $PORT, set by Render)
    ├── /api/*  → strip prefix → http://127.0.0.1:8000  (FastAPI)
    └── /*                     → http://127.0.0.1:8501  (Streamlit)
```

- `Dockerfile` — installs both the Python deps and nginx, copies
  `backend/`, `frontend/`, `config/`, and `deploy/`, and runs
  `deploy/start.sh` as its command.
- `deploy/start.sh` — starts `uvicorn` (port 8000) and `streamlit`
  (port 8501) in the background, renders `deploy/nginx.conf.template`
  with the runtime `$PORT` via `envsubst`, then execs `nginx` in the
  foreground.
- `deploy/nginx.conf.template` — the two routing rules above, plus
  WebSocket upgrade headers on the Streamlit route (its UI needs them
  to stay responsive) and `X-Real-IP`/`Host` forwarding on the API route.
- `render.yaml` — the Render Blueprint: one `docker` runtime web
  service, `healthCheckPath: /api/health`.

Backend routes themselves are **completely unchanged** — `/chat`,
`/health`, `/analytics/*`, `/agent/*`, `/routing/decision/*`, `/history`,
`/stats`, `/models` are exactly what they were; nginx's `/api/` location
strips the prefix before proxying, so the backend never sees `/api/` at
all. The Streamlit UI is unchanged too: `BACKEND_URL` already defaulted
to `http://localhost:8000`, which is correct as-is now that both
processes share one container.

## Testing

```bash
pytest tests/ -v
```

57 tests, all offline — LLM/provider calls are faked via dependency
overrides and monkeypatching, so the suite needs no API keys and no
network access. Coverage includes transactional persistence and
rollback, pattern/recommendation generation and policy-version
isolation, DecisionCard reconstruction and recommendation matching, the
full investigation pipeline (degradation/anomaly/policy-comparison/
recommendation-validation), every public endpoint's response contract,
and (added in the PR5 hardening pass, `tests/test_failure_paths.py`)
provider exceptions, a missing pricing.yaml entry, the heuristic
fallback's confidence, and startup configuration validation — both the
passing case and every failure case; plus (added in the production
stabilization pass, `tests/test_classifier_json_format.py`) that the
OpenRouter provider actually requests `response_format="json_object"`
for the classifier/quality verifier and omits it for regular chat calls,
and that markdown-fence stripping survives a provider that doesn't
honor it.

## Failure handling, audit guarantees, and startup validation

Full detail lives in `docs/architecture.md` ("Failure handling & audit
guarantees" and "Startup configuration validation"); short version:

- **Every request gets an audit record, including failures.** A provider
  exception, a model missing from `pricing.yaml`, or a persistence error
  each write a `failed_requests` row (`request_id`, `stage`,
  `provider`/`model` if known, `error_message`, `status`, `created_at`)
  before the error response goes out — a failed request used to simply
  vanish with no trace anywhere.
- **Configuration is validated at startup, not discovered at request
  time.** `validate_startup_config()` runs before the app serves traffic
  and fails fast with every problem listed at once if `routing.yaml`
  references a provider `providers/factory.py` doesn't implement, or a
  model `pricing.yaml` doesn't price, or thresholds that don't make sense.
- **The heuristic fallback no longer force-escalates.** Its confidence
  used to be a hardcoded value that sat below the default escalation
  threshold, silently bumping every fallback decision one tier past what
  its own word-count logic picked. Fixed to derive from the configured
  threshold instead.

## Production stabilization notes

A live verification pass against the real deployed Supabase database
surfaced issues that only show up when the app actually runs against a
real API and a real database, not just against mocked tests. All of the
following are fixed and re-verified live, not just covered by unit tests:

- **The OpenRouter classifier and quality verifier were silently dead in
  production.** Mistral (via OpenRouter) wraps its JSON reply in a
  ```` ```json ```` markdown fence unless explicitly told not to;
  `OpenRouterProvider.generate()` never requested `response_format:
  json_object` (the Gemini path did, before the OpenRouter migration, and
  that request was lost in the move). Every real classifier call failed
  to parse and silently fell back to the word-count heuristic —
  `classify_heuristically`'s graceful degradation worked exactly as
  designed, which is precisely why nobody noticed the primary path was
  never running. Fixed: `LLMProvider.generate()` now takes an optional
  `response_format` parameter, requested by the classifier and quality
  verifier only (never for regular chat answers); a defensive markdown-
  fence strip was also added as a second line of defense. Verified live
  against the real OpenRouter API: `task_type` is now populated with real
  labels (`"Math"`, `"CodeGen"`, `"Q&A"`, ...), `classifier_model` no
  longer reads `"heuristic"` on a healthy request, and `quality_results`
  now receives real rows with real pass/fail verdicts.
- **The History page crashed the entire Streamlit process (SIGSEGV) on
  a clean install.** Root-caused with `PYTHONFAULTHANDLER=1` (not
  assumed): a fresh `pip install -r requirements.txt` resolved
  `numpy==2.4.6` against the pinned `pandas==2.2.3`, and that combination
  segfaults inside pyarrow's internal `pandas_compat.convert_column` —
  the exact path `st.dataframe()` uses, not the public `pa.Table.from_pandas()`
  API (which does *not* crash, which is why an initial pandas/pyarrow
  smoke test looked fine). Fixed by pinning `numpy==1.26.4` and
  `pyarrow==17.0.0` — versions actually exercised together at
  `streamlit==1.39.0`'s release. Verified on a from-scratch venv: History
  renders correctly and survives repeated navigation.
- **The Streamlit chat request timeout (30s) was incompatible with the
  ADVANCED tier's real latency (~140s for DeepSeek R1).** A slow-but-alive
  backend response was indistinguishable from a Render cold start, so the
  UI's retry logic would silently resubmit the same prompt — a real
  duplicate-billing risk on a paid LLM call. Fixed: the `/chat` request
  now uses a configurable timeout (`CHAT_TIMEOUT_SECONDS`, default 180s)
  and does not retry on a genuine timeout (cold-start placeholder pages
  return near-instantly; a real timeout at 180s is never a cold start).
  A spinner now covers the wait. Verified live: an ADVANCED-tier prompt
  completes through the actual UI with exactly one upstream request, no
  duplicate.
- **Row Level Security was disabled on every table** in the live Supabase
  project, exposing all prompts/responses/audit data to the `anon` role.
  The app never uses Supabase's client SDK or the anon key anywhere — it
  connects directly to Postgres via a `postgresql+psycopg://` URL as the
  `postgres` role, which bypasses RLS entirely regardless of policy — so
  RLS is now enabled on all 9 tables with **zero permissive policies**,
  denying `anon`/`authenticated` access completely. This is the correct
  end state for this app, not a placeholder: nothing should ever read or
  write these tables except the backend's own direct connection. Verified
  live: full `/chat` (write) and `/history` (read) functionality intact
  after enabling RLS.
- **An orphaned `alembic_version` table existed in the live database**
  despite zero Alembic files anywhere in this repo, directly contradicting
  this README's "no separate migration framework" claim above. Dropped —
  it was leftover cruft from an earlier experiment, never read or written
  by any code here.

## Design decisions

The short version of decisions explained at length in `docs/pr*.md` and
`docs/interview-guide.md`:

- **Normalized schema over one flat log table** — lets analytics/agent
  queries aggregate by any dimension (task type, provider, tier)
  independently, instead of scanning a denormalized blob.
- **Transactional persistence, no BackgroundTasks** — a request's full
  decision record (all four tables) either exists completely or not at
  all; audit integrity is a correctness requirement, not best-effort.
- **Failures are audited too, in a separate table** — a provider
  exception, a pricing-config gap, or a persistence error each write a
  `failed_requests` row instead of vanishing with no trace; see "Failure
  handling, audit guarantees, and startup validation" above.
- **DecisionCard reconstructed on read, not stored as JSON** — the
  relational columns are the single source of truth; storing a JSON copy
  alongside them would duplicate the same facts with no independent
  value.
- **Recommendations are advisory only, forever** — the routing engine
  has never once read from `routing_patterns` or
  `optimization_recommendations`. Applying a recommendation always means
  a human edits `routing.yaml` and bumps `policy_version`.
- **The optimization agent is deterministic, not an LLM loop** — every
  finding is a reproducible SQL query or threshold comparison; two runs
  against identical data always produce identical findings.
- **`policy_version` on every learned artifact** — patterns and
  recommendations are scoped to the policy that produced them, so a
  routing.yaml change can never silently blend old and new behavior into
  one average.

## Future roadmap

- Wire the Streamlit UI to the analytics/decision/agent endpoints
  (currently API-only).
- Let the optimization agent cite specific `DecisionCard`s as concrete
  examples inside a finding, not just aggregate numbers.
- A lighter-weight approval flow for `optimization_recommendations.status`.
- Multi-tenant/organization scoping — deliberately not built yet; it's a
  large, separately-scoped effort (auth, data isolation, quotas) rather
  than an incremental addition to the routing platform.

## License

MIT — use it, fork it, ship it.
