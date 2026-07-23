# RoutingBridge — Intelligent Multi-LLM Routing & Cost Optimization Platform

Routes every prompt to the cheapest model capable of handling it well,
instead of always calling the most expensive one. A small router model
judges each prompt's difficulty; a config-driven routing engine picks the
provider and model; the app tracks cost, latency, and savings over time.

## Problem Statement

Teams that call LLMs in production tend to send every request to one
model — usually the most capable (and most expensive) one available,
because routing logic is extra work nobody gets around to building. Most
prompts don't need that model. "What's 2+2" and "design a distributed
consensus protocol" cost the same if you always call GPT-4-class models,
even though the first could be answered by a model 10-50x cheaper.

RoutingBridge is a small, focused system that solves exactly this: classify
prompt difficulty, route to the right tier, and prove the savings with
real numbers.

## Motivation

Built as a portfolio project to demonstrate practical GenAI engineering:
prompt engineering for structured outputs, multi-provider integration,
config-driven architecture, and enough production-mindedness (defensive
fallbacks, error boundaries, observability) to be believable without
being over-engineered.

## Architecture

```
                     ┌─────────────────┐
                     │  Streamlit UI    │
                     │ Chat / History / │
                     │ Analytics /      │
                     │ Settings         │
                     └────────┬─────────┘
                              │ HTTP
                     ┌────────▼─────────┐
                     │   FastAPI app    │
                     │   POST /chat     │
                     └────────┬─────────┘
                              │
              ┌───────────────┼────────────────┐
              ▼                                 ▼
     ┌────────────────┐               ┌──────────────────┐
     │ ClassifierService│              │  RoutingEngine    │
     │ (Gemini 2.5 Flash)│─decision──▶ │ (routing.yaml)    │
     │ + heuristic       │              └─────────┬─────────┘
     │   fallback         │                        │ provider+model
     └────────────────┘                        ┌────▼─────┐
                                                │ Provider  │
                                                │ Gemini /  │
                                                │ OpenRouter│
                                                └────┬─────┘
                                                     │ response + tokens
                                          ┌──────────▼──────────┐
                                          │  Cost Estimator      │
                                          │  (pricing.yaml)      │
                                          └──────────┬──────────┘
                                                     │
                                          ┌──────────▼──────────┐
                                          │  SQLite (request_logs)│
                                          └──────────────────────┘
```

**Request flow**: a prompt hits `POST /chat` → the classifier (a cheap
Gemini call, JSON-mode, Pydantic-validated) decides a routing tier
(BASIC/STANDARD/ADVANCED) with a confidence score → the routing engine
reads `routing.yaml` to pick a provider+model for that tier, escalating
one tier up if confidence is low → the selected provider generates the
actual response → cost is computed from `pricing.yaml` and real token
counts → everything is logged to SQLite → the full decision (model,
reasons, cost, latency) is returned to the caller.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI | typed, async-capable, automatic OpenAPI docs |
| Frontend | Streamlit | fast to build, standard for ML/GenAI demos |
| Validation | Pydantic v2 | structured-output validation for LLM responses |
| Database | SQLite + SQLAlchemy | zero-ops persistence appropriate for this scale |
| LLM Providers | Google Gemini (native SDK), OpenRouter (REST) | the two providers I actually hold keys for — every model in the UI is genuinely callable |
| Config | YAML (`routing.yaml`, `pricing.yaml`) | routing policy and pricing change without a code deploy |
| Packaging | Docker + docker-compose | two services (backend, frontend), one command to run both |

## Folder Structure

```
backend/
  main.py                      FastAPI app, router registration, DB init
  routers/
    chat.py                    POST /chat — the core request flow
    history.py                 GET /history
    stats.py                   GET /stats
    models.py                  GET /models — current routing config
  services/
    classifier_service.py      LLM-based routing classifier
    heuristic_classifier.py    word-count fallback (exception path)
    routing_engine.py          tier -> provider/model, confidence escalation
    cost_estimator.py          pricing.yaml -> $ cost
    providers/
      base.py                  LLMProvider interface
      gemini_provider.py       native Google SDK
      openrouter_provider.py   REST gateway to Mistral/DeepSeek/Qwen/Llama
      factory.py                provider name -> instance
  schemas/                     Pydantic request/response/domain models
  database/                    SQLAlchemy engine, session, RequestLog model
  utils/                       Settings, logging, YAML config loaders
config/
  routing.yaml                 classifier + tier -> provider/model + reasons
  pricing.yaml                 $/1M tokens per model
frontend/
  streamlit_app.py             Chat / History / Analytics / Settings pages
```

## Setup

Requires Python 3.11+ (managed here via `pyenv`).

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GOOGLE_API_KEY and OPENROUTER_API_KEY

# terminal 1
uvicorn backend.main:app --reload

# terminal 2
streamlit run frontend/streamlit_app.py
```

Visit `http://localhost:8501` for the UI, `http://localhost:8000/docs`
for the interactive API docs.

## Docker

```bash
docker compose up --build
```

Starts both services: backend on `:8000`, frontend on `:8501`. SQLite
data persists in `./data/modelpilot.db` via a bind-mounted volume, so
`docker compose down && docker compose up` doesn't lose history.

## Future Improvements

Deliberately not built, to keep this project fresher-scoped and
explainable end-to-end — listed here to show they were considered, not
missed:

- **Streaming responses** — `/chat` currently returns a complete response; token streaming would need SSE/websockets, real UX value but a second I/O model to explain.
- **Editable routing config via UI** — Settings page is read-only by design; writing YAML at runtime risks race conditions between concurrent edits.
- **Per-user auth / multi-tenant cost tracking** — no auth today; would matter for a real product, not for demonstrating routing logic.
- **A/B testing routing policies** — comparing two routing.yaml configs against the same traffic; interesting but genuinely a second project.

## Interview Questions This Project Prepares You For

- Why classify with a small LLM instead of pure heuristics, and how do you keep that classification call cheap?
- Walk through what happens when the classifier's confidence is low.
- What happens if OpenRouter is down mid-request? Is anything left in a bad state?
- Why is pricing/routing config in YAML instead of Python?
- Why does the provider abstraction exist, and why doesn't the classifier use it?
- How would `estimated_savings` be computed, and what does it actually mean?
- Why SQLite instead of Postgres here, and when would that choice change?
