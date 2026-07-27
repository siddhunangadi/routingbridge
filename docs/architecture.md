# RouteIQ Architecture

This is the single reference for how the system fits together. The
`docs/pr{1,2,3,4}-*.md` files remain as the detailed *why* behind each
layer's design decisions and trade-offs; this document is the *what* and
*how they connect*, current as of PR5.

## Overall architecture

```mermaid
flowchart TB
    subgraph Client
        UI[Streamlit UI]
        API_CLIENT[Direct API caller]
    end

    subgraph Backend[FastAPI Backend]
        CHAT["/chat"]
        HIST["/history"]
        STATS["/stats"]
        MODELS["/models"]
        ANALYTICS["/analytics/*"]
        DECISIONS["/routing/decision/{id}"]
        AGENT["/agent/*"]
    end

    subgraph Services
        CLASSIFIER[ClassifierService]
        ROUTER[RoutingEngine]
        PROVIDERS[Provider adapters]
        QUALITY[QualityVerifier]
        DECISION_SVC[decision_service]
        HIST_SVC[history_service]
        STATS_SVC[stats_service]
        ANALYTICS_SVC[analytics_service]
        LEARNING[routing_learning]
        AGENT_SVC[routing_agent]
        INVEST_SVC[investigation_service]
    end

    subgraph DB[(SQLite / Postgres)]
        REQ[(requests)]
        RD[(routing_decisions)]
        ER[(execution_results)]
        QR[(quality_results)]
        RP[(routing_patterns)]
        OR[(optimization_recommendations)]
        POL[(routing_policies)]
        IR[(investigation_reports)]
    end

    UI --> CHAT & HIST & STATS & MODELS
    API_CLIENT --> CHAT & ANALYTICS & DECISIONS & AGENT

    CHAT --> CLASSIFIER --> ROUTER --> PROVIDERS
    CHAT --> QUALITY
    CHAT --> DECISION_SVC --> REQ & RD & ER & QR

    HIST --> HIST_SVC --> REQ & RD & ER & QR
    STATS --> STATS_SVC --> RD & ER & QR

    ANALYTICS -->|POST refresh| LEARNING --> RD & ER & QR
    LEARNING --> RP & OR
    ANALYTICS -->|GET routing/patterns/recommendations| ANALYTICS_SVC --> RD & ER & QR & RP & OR

    DECISIONS --> DECISION_SVC

    AGENT -->|POST investigate| AGENT_SVC --> RP & OR & RD & ER & QR
    AGENT_SVC --> IR
    AGENT -->|GET report/reports| INVEST_SVC --> IR

    ROUTER -.reads.-> POL
```

## Request lifecycle (`POST /chat`)

```mermaid
sequenceDiagram
    participant User
    participant Chat as chat.py
    participant Classifier as ClassifierService
    participant Engine as RoutingEngine
    participant Provider as LLMProvider
    participant Verifier as QualityVerifier
    participant Decision as decision_service

    User->>Chat: POST /chat {prompt}
    Chat->>Classifier: classify(prompt)
    Classifier-->>Chat: RoutingDecisionOutcome (tier, task_type, confidence)
    Chat->>Engine: select(decision)
    Engine-->>Chat: RoutingResult (provider, model, escalated?)
    Chat->>Provider: generate(prompt, model)
    Provider-->>Chat: text, input/output tokens
    Chat->>Chat: estimate_cost()
    alt tier != ADVANCED
        Chat->>Verifier: verify(prompt, response)
        Verifier-->>Chat: passed/failed + reason
    end
    Chat->>Decision: record(...) [single transaction]
    Decision-->>Chat: (writes requests, routing_decisions,<br/>execution_results, quality_results)
    Chat-->>User: ChatResponse
```

## Routing flow

```mermaid
flowchart LR
    A[Prompt] --> B{Classifier LLM call<br/>succeeds?}
    B -->|yes| C[Structured decision:<br/>tier, task_type, confidence]
    B -->|no| D[Heuristic fallback<br/>word-count based]
    C --> E{confidence < low<br/>threshold?}
    D --> E
    E -->|yes| F[Escalate one tier up]
    E -->|no| G[Keep classifier's tier]
    F --> H[routing.yaml: tier -> provider/model]
    G --> H
    H --> I[Call provider]
```

Routing is entirely deterministic and config-driven — `routing.yaml`'s
`tiers` mapping is the only place a tier resolves to a concrete
provider/model. Nothing from the analytics or agent layers below can
change this at request time (see "Governance" in the README).

## Decision flow (PR3)

```mermaid
flowchart TB
    A[GET /routing/decision/request_id] --> B[decision_service.get_decision_card]
    B --> C[Join requests + routing_decisions + execution_results]
    C --> D[Build reasoning_steps<br/>deterministic, from persisted columns]
    C --> E[Look up optimization_recommendations<br/>matching policy_version + task_type +<br/>task_subcategory + provider + model]
    D --> F[DecisionCard]
    E --> G{Match found?}
    G -->|yes| H[RecommendationSummary]
    G -->|no| I[recommendation_available = false]
    F --> J[DecisionDetailResponse]
    H --> J
    I --> J
```

## Analytics & learning flow (PR2)

```mermaid
flowchart TB
    A[POST /analytics/refresh] --> B[routing_learning.refresh]
    B --> C[Group routing_decisions + execution_results<br/>+ quality_results by task_type, task_subcategory,<br/>provider, model, tier, policy_version]
    C --> D[DELETE + INSERT routing_patterns]
    D --> E[Compare each tier's configured<br/>provider/model against best alternative]
    E --> F{Alternative clears<br/>min_sample_size and<br/>beats pass_rate?}
    F -->|yes| G[DELETE + INSERT optimization_recommendations<br/>with evidence JSON]
    F -->|no| H[No recommendation for this group]

    I[GET /analytics/routing] --> J[analytics_service:<br/>provider/model/task_type stats,<br/>tier distribution, daily trend]
    K[GET /analytics/patterns] --> L[routing_patterns, as-is]
    M[GET /analytics/recommendations] --> N[optimization_recommendations, as-is]
```

## Optimization Agent flow (PR4)

```mermaid
flowchart TB
    A[POST /agent/investigate] --> B[routing_agent.investigate]
    B --> C1[Load policy_version + routing_patterns]
    C1 --> C2[Find degraded task types<br/>pass_rate < 70%]
    C1 --> C3[Find the most expensive task type]
    C1 --> C4[Detect cost anomaly<br/>latest day vs. prior average]
    C1 --> C5[Compare policy_versions<br/>if more than one exists]
    C1 --> C6[Re-validate pending recommendations<br/>against LIVE routing_decisions data]
    C2 & C3 & C4 & C5 & C6 --> D[Findings list]
    D --> E[Derive suggested_actions]
    D --> F[Compute overall risk_level + confidence]
    E & F --> G[INSERT investigation_reports]
    G --> H[InvestigationReport response]
```

No LLM call happens in this pipeline — every step is a deterministic SQL
query or comparison. See `docs/pr4-routing-agent.md` for why.

## Governance model (cuts across every flow above)

One rule holds everywhere a "smarter" layer sits on top of routing:

> **Nothing downstream of a routing decision can change how future
> decisions are made, except a human editing `routing.yaml` and bumping
> `policy_version`.**

- `routing_patterns`/`optimization_recommendations` (PR2): generated by
  an explicit `POST /analytics/refresh`, never read by `routing_engine.py`.
- `DecisionCard.recommendation_available` (PR3): surfaces a match, never
  applies it.
- `InvestigationReport.suggested_actions` (PR4): advisory text a human
  reads, never executed.

This is why the routing engine (`backend/services/routing_engine.py`)
has not changed since PR1 — every subsequent PR was additive around it,
never through it.

## Data model summary

| Table | Written by | Read by |
|---|---|---|
| `requests` | `decision_service.record()` | `history_service`, `analytics_service`, `decision_service` |
| `routing_decisions` | `decision_service.record()` | all analytics/agent/decision services |
| `execution_results` | `decision_service.record()` | all analytics/agent/decision services |
| `quality_results` | `decision_service.record()` | `stats_service`, `analytics_service`, `routing_learning`, `routing_agent` |
| `routing_policies` | `scripts/bootstrap_db.py` (explicit, never on app startup) | (audit reference; not yet queried by any endpoint) |
| `routing_patterns` | `routing_learning.refresh()` only | `analytics_service`, `routing_agent` |
| `optimization_recommendations` | `routing_learning.refresh()` only | `analytics_service`, `decision_service`, `routing_agent` |
| `investigation_reports` | `routing_agent.investigate()` only | `investigation_service` |
