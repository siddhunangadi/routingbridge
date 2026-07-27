# PR 2: AnalyticsService & APIs

Builds the read/learn layer on top of PR1's normalized schema. Scoped to
analytics only — no changes to the routing engine, no policy simulator, no
agent. Those come in PR3/PR4.

## What was added

- **`routing_patterns`** and **`optimization_recommendations`** tables
  (`backend/database/models.py`), matching the columns specified for
  RouteIQ's persistence design.
- **`routing.yaml`'s `learning` block** — `apply_recommendations`,
  `min_sample_size`, `min_confidence` — the thresholds `routing_learning.py`
  uses to decide when an alternative is trustworthy enough to recommend.
- **`services/analytics_service.py`** — read-only aggregation for
  `GET /analytics/routing` (provider/model/task-type stats, tier
  distribution, daily cost/latency trend), `GET /analytics/patterns`, and
  `GET /analytics/recommendations`. Writes nothing.
- **`services/routing_learning.py`** — `refresh()`, the only thing that
  writes `routing_patterns`/`optimization_recommendations`. Runs only when
  `POST /analytics/refresh` is called.
- **`backend/routers/analytics.py`** — four thin endpoints, same pattern
  PR1's review established for `history.py`/`stats.py`: validate, call a
  service, return.

## Why routing_patterns is a wholesale recompute, not an incremental upsert

`refresh()` deletes all rows in `routing_patterns` (and
`optimization_recommendations`) and reinserts from scratch every time it
runs. An incremental upsert-per-request would need to maintain running
averages correctly as new requests arrive — more state, more room for a
subtle bug (e.g. an average silently drifting from the true value after
enough updates) — for a table whose entire purpose is "what does the
history currently look like," which a full recompute answers exactly and
simply. `refresh()` is explicit and infrequent (called manually, not on
the request path), so its cost is a non-issue at this project's scale.

**When to revisit this**: `refresh()` does a full scan/group-by over
`routing_decisions` every call — O(n) in total request count. That's
fine through the low tens of thousands of rows a demo or small deployment
will ever see. If `routing_decisions` grows into the hundreds of
thousands, switch to an incremental upsert keyed by `(task_type,
task_subcategory, provider, model, tier, policy_version)` — the same key
`routing_patterns`' unique constraint already uses — that updates
`sample_size`/`average_cost`/`average_latency`/`pass_rate` with a running
mean instead of recomputing from every row. Don't build that ahead of
needing it: it trades simplicity (today's real advantage) for a
performance headroom this project doesn't need yet.

## Why recommendations are advisory-only, with no code path to apply them

`_generate_recommendations()` in `routing_learning.py` compares each
tier's `routing.yaml`-configured provider/model against the
best-performing alternative for the same `task_type` at that tier. A
recommendation is only generated when:

1. The alternative has at least `learning.min_sample_size` samples
   (default 20) — small samples are noise, not signal.
2. Its `pass_rate` is strictly better than the currently configured
   model's.

Nothing here writes to `routing.yaml`, and the routing engine (unchanged
in this PR) never reads `optimization_recommendations`. This is
deliberate, not an oversight: a recommendation is a hypothesis about
future behavior based on past data, and applying it automatically would
mean the system's routing could change without a human ever reviewing the
evidence. PR3 will make recommendations visible in the `DecisionCard` as
"Recommendation Available" — still never auto-applied; a human still has
to bump `policy_version` in `routing.yaml` for anything to change.

Each recommendation carries a structured `evidence` field (current vs.
recommended provider/model, sample size, average cost, pass rate) rather
than just the deltas — the `reason` string is a prose summary of exactly
those numbers, not a separate source of truth. A dashboard or the future
Routing Optimization Agent can quote `evidence` directly instead of
re-parsing `reason`'s sentence.

### `learning.enabled` → `learning.apply_recommendations`

The first draft of this block had a single `enabled: false` flag, and
`routing_learning.py` never actually read it — `refresh()` always
computed patterns and recommendations regardless of its value. That's
exactly backwards from what the name implies. The flag now has an
honest name and a single, precise job it doesn't have yet: from PR3 on,
`apply_recommendations` gates whether an existing recommendation is
surfaced as "Recommendation Available" on a live request's
`DecisionCard`. It has never gated — and will never gate — generation,
and it will never let a recommendation change what a tier actually
routes to; that's still only ever a human bumping `policy_version`.

### `routing_patterns`/`optimization_recommendations` carry `policy_version`

Both tables are now grouped/filtered by `policy_version` (from
`routing_decisions.routing_policy_version`, which PR1 already stamps on
every request). Two consequences:

- A `routing_pattern` row is scoped to one policy version's requests —
  if `routing.yaml`'s tiers change and `policy_version` bumps, old and
  new behavior for the same provider/model never silently blend into one
  average.
- `_generate_recommendations()` only compares patterns whose
  `policy_version` matches the *currently active* one. A pattern left
  over from a superseded policy can never produce a recommendation
  against the policy in effect now — see
  `test_refresh_ignores_patterns_from_a_different_policy_version` in
  `tests/test_routing_learning.py`.

## Why pass_rate is computed with AVG + a NULL-preserving CASE

`quality_results` only has a row for BASIC/STANDARD-tier requests (see
`chat.py` — ADVANCED tier is never verified, on purpose). Both
`analytics_service.py` and `routing_learning.py` outer-join
`quality_results` and compute pass_rate as:

```python
func.avg(case((verdict.is_(True), 1.0), (verdict.is_(False), 0.0), else_=None))
```

`AVG()` ignores `NULL`s in SQL. Without the explicit `else_=None`, a
request with no quality row (`NULL` verdict from the outer join) would
fall into a default branch and get counted as a failure, silently
dragging every pass_rate down for any group that mixes verified and
unverified requests (e.g. a task_type that spans BASIC and ADVANCED
tiers). `else_=None` makes "never verified" invisible to the average
instead of miscounted as "failed" — the same semantics `/stats`'
`quality_pass_rate` already uses.

## What PR2 deliberately does not do

- No caching or scheduling for `/analytics/refresh` — it's a manual
  trigger, matching the "explicit trigger only" decision made during
  design.
- No pagination on `/analytics/patterns` or `/analytics/recommendations`
  — at current scale (thousands, not millions, of rows) an unpaginated
  list is the honest, simple choice; add it if a deployment's row count
  ever makes it necessary.
- `task_subcategory` is carried through every query and table but stays
  `None` everywhere — the classifier doesn't populate it yet. Extending
  the classifier is a separate, explicit concern for whenever it's
  requested.
