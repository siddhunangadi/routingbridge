# Interview Guide

This is prep material for talking about RouteIQ in an interview — the
questions worth anticipating and a confident answer to each. It doesn't
duplicate the architecture doc; it's the *reasoning* behind it.

## Why this project exists

Most demo apps that call an LLM pick one model and use it for every
request. That's simple but wasteful: a huge fraction of real prompts
("what's 15% of 80?", "summarize this paragraph") don't need a
frontier model, and a smaller fraction genuinely do. RouteIQ is built
around one idea: **classify difficulty first, then route to the
cheapest model that can actually do the job** — and treat every routing
decision as data worth learning from, not a one-off log line.

## Why routing instead of one LLM

The alternative — always call the best model — is simpler to build but
means paying frontier-model prices for arithmetic questions. The
alternative-alternative — hardcoded keyword rules ("if the prompt
contains 'code', use model X") — is cheap but brittle and doesn't
generalize. RouteIQ's classifier is itself a cheap LLM call
(Gemini 2.5 Flash) making a structured judgment (tier, task type,
confidence) about a prompt it never answers — the same pattern a
production system uses a small model as a gate in front of expensive
ones. If you're asked "why not just use one model," the honest answer is
cost: the `estimated_savings` figure in `/stats` is the concrete number
this design earns.

## Why DecisionCards

A routing decision without an explanation is a black box — "the system
picked Gemini for some reason." `DecisionCard` (PR3) makes that
reasoning inspectable per-request: which tier, why (escalated or not),
what the classifier's confidence was, and whether a learned alternative
exists for this same (task_type, provider, model) combination. It's
built entirely from what's already persisted — no LLM call reconstructs
it, so two requests with identical `routing_decisions` rows always
produce byte-identical explanations. That determinism is the whole
point: "explainable" has to mean reproducible, not "an LLM's best guess
at why it did what it did."

## Why recommendations are advisory, never auto-applied

The learning layer (PR2) can notice, for example, that DeepSeek
outperforms Gemini Flash on a task type at the same cost tier. The
tempting next step is "just switch it automatically." RouteIQ
deliberately doesn't: `routing_learning.py` writes recommendations to
their own table; `routing_engine.py` never reads that table. A human
reviews `GET /analytics/recommendations` (or an agent-generated
`InvestigationReport`) and, if convinced, edits `routing.yaml` and bumps
`policy_version` themselves. This is a governance choice, not a
technical limitation — a routing system whose behavior can silently
drift based on noisy historical data is a production incident waiting to
happen. Determinism and auditability were valued over "fully autonomous"
from PR1 onward.

## Why the optimization agent is offline

PR4's "agent" investigates routing history and produces
`InvestigationReport`s — findings like "this task type is degraded" or
"this recommendation is no longer supported by live data." It is
explicitly *not* an LLM reasoning loop: every finding is a deterministic
SQL query or comparison (a pass_rate threshold, a cost-ratio check), run
in a fixed, inspectable sequence (`investigation_steps`/`tools_used`).
Two motivations: first, none of these questions ("is pass_rate below
70%?") need an LLM to answer correctly and reproducibly. Second, keeping
it offline and read-only (it only ever writes to its own
`investigation_reports` table) means there is no path — accidental or
adversarial — from "the agent noticed something" to "production routing
changed." If asked "could this use an LLM to write better summaries,"
the honest answer is yes, that's a legitimate future layer on top — but
it would only change *how findings are phrased*, never what they
conclude.

## Trade-offs made along the way

- **SQLite in dev, one flat table → four normalized tables (PR1)**:
  traded a bit of query complexity (joins instead of one row) for the
  ability to aggregate independently by task type/provider/tier, which
  a flat table can't do without scanning everything.
- **DELETE + INSERT for `routing_patterns` (PR2)**, not incremental
  upsert: simpler and provably correct (it's always a full recompute),
  at the cost of an O(n) scan on every `/analytics/refresh`. Documented
  in `docs/pr2-analytics.md` exactly when to revisit (hundreds of
  thousands of rows).
- **No caching anywhere in the analytics/decision/agent layers**: these
  are point lookups or infrequent explicit triggers, not hot-path
  reads — caching would be complexity with no measured problem to solve.
- **`policy_version` as a manual YAML edit, not a UI**: keeps the
  "who changed routing and when" question answerable by `git blame` and
  `routing_policies`, rather than needing a settings UI + audit log for
  what's currently a single-operator system.

## Scaling considerations

- **Database**: the current schema is Postgres-ready (SQLAlchemy models
  with no SQLite-specific types); switching `DATABASE_URL` and adding
  `psycopg` is the extent of the migration for real concurrent load.
- **`/analytics/refresh` cost**: documented in `docs/pr2-analytics.md` —
  fine through tens of thousands of requests; an incremental upsert
  keyed by the same tuple the unique constraint uses is the documented
  next step if that stops being true.
- **Classifier/quality-verifier latency**: both are synchronous calls in
  the request path today. An async provider interface would let
  concurrent requests overlap their classifier/generation calls, but
  that's a real architecture change, not a tweak — noted here, not built
  speculatively.
- **Provider list**: adding a third provider is one new `LLMProvider`
  subclass and one `routing.yaml` entry — the factory function and
  routing engine don't need to change.

## Future improvements (roadmap-shaped, not commitments)

- Wire the Streamlit UI to the analytics/decision/agent endpoints (they
  are currently API-only; the UI still only covers chat/history/stats).
- Let `routing_agent.py` optionally join specific `DecisionCard`s into a
  finding as concrete examples, not just aggregate numbers.
- A lightweight approval flow for `optimization_recommendations.status`
  (still human-driven, just less manual than editing YAML directly).
- Multi-tenant/organization scoping, if this ever needs to serve more
  than one team's traffic — deliberately not built now; see the note in
  the repo history about why that's a separably-scoped, much larger
  effort than anything above.
