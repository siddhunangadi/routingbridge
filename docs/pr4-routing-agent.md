# PR 4: Routing Optimization Agent

Adds an offline "agent" that investigates routing history and produces a
structured, persisted `InvestigationReport`. It has no effect on live
routing whatsoever — it only reads PR1-PR3's tables and writes its own
findings to a new `investigation_reports` table.

## Architecture

```
POST /agent/investigate  ──▶ routing_agent.investigate(db)
                                  │
                                  ├─ load routing.yaml (policy_version, thresholds)
                                  ├─ query routing_patterns (current policy_version)
                                  ├─ query requests + execution_results (daily trend)
                                  ├─ query routing_patterns (distinct policy_version)
                                  ├─ query optimization_recommendations (pending)
                                  ├─ re-derive live stats from routing_decisions/
                                  │  execution_results/quality_results per recommendation
                                  └─ INSERT investigation_reports, commit
                                  ▼
GET /agent/report/{id}   ──▶ investigation_service.get_report(db, id)
GET /agent/reports       ──▶ investigation_service.list_reports(db, ...)
```

`routing_agent.py` is the write side (mirrors `routing_learning.py`'s
role from PR2); `investigation_service.py` is the read side (mirrors
`analytics_service.py`). Same split the PR2 review praised, applied
again here on purpose.

## Why the agent is offline, not part of live routing

Every PR so far has drawn the same line: routing is deterministic and
config-driven, and anything that learns from history is advisory,
running only when explicitly triggered (`POST /analytics/refresh` in
PR2, `POST /agent/investigate` here). The agent is invoked by a human (or
a script/cron a human sets up) calling an endpoint — never from inside
`chat.py`'s request path. `routing_engine.select()` doesn't import
anything from `routing_agent.py`, and there is no code path — anywhere in
this codebase — that lets an `InvestigationReport` or a `SuggestedAction`
change what `POST /chat` actually does. Applying a suggestion always
means a human reads the report, then edits `routing.yaml` and bumps
`policy_version`, same as every prior PR established.

## Why "agentic" here means a fixed pipeline, not an LLM call

The brief describes the agent as answering open-ended questions ("why is
cost increasing?", "which recommendations are trustworthy?") and
explicitly asks for an inspectable `investigation_steps`/`tools_used`
trace without chain-of-thought exposure. Those requirements are met by
five deterministic queries run in a fixed order — not by asking an LLM
to reason over the data:

1. `_find_degraded_task_types` — patterns below `DEGRADED_PASS_RATE_THRESHOLD` (0.7)
2. `_find_expensive_task_type` — the task type costing > `COST_ANOMALY_MULTIPLIER` (1.5x) the average of the rest
3. `_detect_cost_anomaly` — latest day's cost-per-request vs. the prior days' average
4. `_compare_policy_versions` — weighted average cost/pass-rate per `policy_version`, when more than one exists
5. `_validate_recommendations` — re-derives *live* stats straight from `routing_decisions`/`execution_results`/`quality_results` (not from `routing_patterns`, which is only as fresh as the last refresh) for each pending recommendation, and checks whether it's still supported

There's no ambiguity to resolve with a model here: "is this pass_rate
below 0.7?" doesn't need an LLM, and using one would add latency, cost,
and exactly the chain-of-thought-exposure risk the brief says to avoid,
for a job SQL already does exactly and reproducibly. If a future PR
wants the agent to *phrase* findings more richly (turn `Finding.summary`
into prose, say), that's a narrow, addable layer on top of this
pipeline — it doesn't change what the pipeline decides, only how it's
worded, and should only be built if that's a real, requested need.

`investigation_steps` and `tools_used` are exactly what the code
did — "Loaded 5 routing_patterns row(s)...", "database.query(...)" — not
a model's narrated reasoning. Two runs against identical data produce
byte-identical findings.

## Why recommendation validation queries live data, not routing_patterns

`optimization_recommendations` rows are generated once, at `refresh()`
time, from whatever `routing_patterns` looked like then. If more traffic
arrives afterward without another `refresh()` call, `routing_patterns`
— and the recommendations derived from it — can silently go stale
relative to what's actually been happening. Re-validating a
recommendation *against the same table it was generated from* would be
circular: it would always say "yes, still true," because nothing new was
considered. `_live_stats()` instead re-queries `routing_decisions` +
`execution_results` + `quality_results` directly for the exact
(`policy_version`, `task_type`, `task_subcategory`, `provider`, `model`)
groups the recommendation names, computing fresh numbers. If those fresh
numbers no longer show the recommended alternative outperforming the
current one, the finding says so explicitly ("should be re-reviewed") and
no `SuggestedAction` is generated for it — see
`test_validates_recommendation_as_stale_when_live_data_no_longer_supports_it`.

## Persistence: what's stored, what isn't

`investigation_reports` stores the agent's own output: scalar columns
(`policy_version`, `risk_level`, `confidence`, `executive_summary`) for
filtering, plus JSON columns for `findings`, `suggested_actions`,
`investigation_steps`, and `tools_used` — the same JSON-column precedent
`RoutingPolicy.config` and `OptimizationRecommendation.evidence` already
established. Nothing from `routing_decisions`, `execution_results`, or
`routing_patterns` is copied wholesale into it: each `Finding.evidence`
entry carries a `reference_type`/`reference_id` (e.g. an
`optimization_recommendations.recommendation_id`) plus the *derived*
numbers that specific finding is based on — a pointer and a conclusion,
not a duplicate of the row.

## Extension points for future autonomous optimization

- **Scheduling**: nothing here runs on a timer. Wiring
  `POST /agent/investigate` to a cron job (or Render's cron-job feature)
  is a deploy-level decision, not a code change — the endpoint is already
  side-effect-contained (writes only to `investigation_reports`), so it's
  safe to call repeatedly.
- **Consuming DecisionCards**: `GET /routing/decision/{request_id}` (PR3)
  gives per-request explanations; this agent currently only reads the
  aggregate tables. A future investigation step could join specific
  `DecisionCard`s into a finding (e.g. "these 3 requests illustrate the
  degraded pattern") without changing the read-only contract.
- **Acting on `SuggestedAction`s**: still always a human decision. If a
  future PR wants a lower-friction approval flow, the natural shape is a
  `status` transition on `optimization_recommendations` (already has a
  `status` column, currently always `"pending"`) driven by an explicit
  human action — never automatically from an investigation run.
