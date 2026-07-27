# PR 1: Foundation & Transactional Persistence

This document explains the architectural decisions behind PR1 — the
foundation the rest of the RouteIQ evolution (analytics, policy
simulation, the Routing Optimization Agent) builds on. It is scoped to
PR1 only; it does not describe features later PRs add.

## Why schema normalization was introduced

The old schema was one table, `RequestLog`, with every fact about a
request — the prompt, the classifier's judgment, the provider call, the
quality verdict — flattened into a single row. That was the right shape
for "log every chat request" (its original job), but it can't support
what comes next:

- **Historical analytics** (PR2) needs to group and aggregate by
  dimensions like task type, provider, and tier independently. A flat
  table forces every query to scan the same wide row regardless of which
  dimension it cares about.
- **Policy simulation** (PR3) needs to replay `routing_decisions` and
  `execution_results` as if a different policy had been in effect,
  without touching quality data.
- Each stage of the request lifecycle (request → routing decision →
  execution → quality) has a different lifecycle and, for quality
  results, an optional one — not every request gets verified. Modeling
  that as one required column (`quality_passed: bool | None`) versus an
  optional related row (`quality_results` present or absent) is the same
  fact, but the normalized form is what a join-based analytics query
  expects.

Four tables — `requests`, `routing_decisions`, `execution_results`,
`quality_results` — keyed by `request_id`, plus `routing_policies` as the
seed of a versioned policy registry.

## Why transactional persistence was chosen (and BackgroundTasks removed)

An earlier draft of this PR briefly considered writing the four rows via
FastAPI `BackgroundTasks`, deferring persistence until after the response
was sent. That's wrong for this system: the entire point of RouteIQ is
that every routing decision is auditable. A `BackgroundTasks` write can
silently fail (the task runs after the response, so no request-time error
handling covers it) or run only partially before a crash. That would mean
some requests exist in the API response the user saw but not in the audit
trail — a broken guarantee for a system whose value proposition is "we
can explain every decision we made."

Instead, `DecisionService.record()` writes all four rows in one
SQLAlchemy transaction, in the same request/response cycle the router
already runs in. It commits once, after all four `db.add()` calls. This
gives one concrete guarantee: **either a request's full decision record
exists (all four — or three, when quality wasn't verified — rows
present), or none of it does.** There's no partial-write state to reason
about, and if the commit fails, the exception propagates to FastAPI,
which returns a 500 — the caller is told the request didn't complete
cleanly, rather than getting a 200 with data an audit view can never see.

## Why DecisionCard exists — and why it isn't stored as JSON

`DecisionCard` is the structured explanation of one routing decision:
what the classifier saw, what confidence it had, which models were
candidates, which one was picked, and why. It's the object a future "why
did the system choose this?" API response or audit view will return.

PR1's first draft stored `DecisionCard` as a JSON blob on
`routing_decisions`, alongside the relational columns that carried the
same facts (`classifier_reasoning`, `selected_provider`,
`selected_model`, `routing_reasoning`, `routing_policy_version`, ...).
Code review correctly flagged this as duplication with no independent
value — every field in the JSON was either already a column or trivially
derivable from one (`candidate_models` comes straight from
`routing.yaml`, not from anything request-specific).

The fix: `routing_decisions`'s columns are the single source of truth.
`reconstruct_decision_card()` in `decision_service.py` rebuilds a
`DecisionCard` from a persisted row on demand. Two consequences of this
choice worth calling out:

- `recommendation_used`/`recommendation_reason` are always `False`/`None`
  on a reconstructed card in PR1, because the learning layer that
  populates them doesn't exist yet (PR2/PR4). The field contract doesn't
  change later — only what fills it does.
- If a future PR needs point-in-time provenance that a live
  reconstruction can't give (e.g. "what did `routing.yaml`'s tier list
  look like at the moment this decision was made, if it's since
  changed") that's a real, separable argument for re-introducing a stored
  snapshot — but it should be added when that need is concrete, not
  speculatively now.

## Why routing_policies is seeded by an explicit script, not app startup

The first draft of PR1 called `Base.metadata.create_all()` *and* seeded
`routing_policies` from `routing.yaml` inside FastAPI's `startup` event —
every time the process booted. `Base.metadata.create_all()` is safe to
run unconditionally (idempotent schema DDL: it only creates tables that
don't exist). Seeding `routing_policies` is not the same kind of
operation — it's writing business data (a row that becomes part of the
policy audit trail) as a side effect of the process starting, which means
a routine restart, a scaled-out second instance, or a CI health check
could all silently write to it.

`scripts/bootstrap_db.py` moves that seed to something a developer or a
deploy step runs deliberately: `python -m scripts.bootstrap_db`. It's
idempotent (skips seeding if the current `policy_version` already has a
row), so running it twice is harmless, but running it *is* now always a
choice, not an automatic consequence of `uvicorn` starting.

## What the transaction guarantees, precisely

- All four inserts (`requests`, `routing_decisions`, `execution_results`,
  and `quality_results` when a quality verdict exists) commit together or
  not at all.
- A failure surfaces as an uncaught exception from `db.commit()`, which
  FastAPI turns into a 500 — the router does not swallow or retry it.
- The transaction covers persistence only. The provider call itself
  (`provider.generate()`) happens before `DecisionService.record()` and
  is not part of the same transaction — a provider failure is handled
  separately (a 502, before any row is written), which is unchanged
  behavior from before this PR.
