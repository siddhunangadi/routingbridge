# RoutingBridge — Backend Architecture

Reverse-engineered from the implementation (not the README). Every diagram
below reflects actual code paths in `backend/`, `frontend/`, `config/`,
`deploy/`, and `scripts/` as of this commit.

> **Note on scope**: this codebase has **no PDF ingestion, no chunking, no
> embeddings, and no vector DB** — there is no such feature anywhere in the
> repo (confirmed by reading every file under `backend/`). The requested
> "PDF Ingestion Flow" section is omitted rather than fabricated. What this
> system actually does is **LLM request routing**: classify a prompt, pick
> the cheapest capable model, call it, verify quality, and record every
> decision for audit/analytics/learning. All diagrams below reflect that.

---

## 1. Complete System Architecture

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        Browser["Browser"]
    end

    subgraph Frontend["frontend/ — Streamlit (single container process)"]
        ST["streamlit_app.py<br/>Chat / History / Analytics / Settings pages"]
        Theme["theme.py"]
    end

    subgraph Edge["deploy/ — nginx reverse proxy ($PORT)"]
        Nginx["nginx.conf.template<br/>routes /api/* -> FastAPI, /* -> Streamlit"]
    end

    subgraph API["backend/main.py — FastAPI app"]
        Lifespan["lifespan(): validate_startup_config()"]
        Routers["Routers"]
    end

    subgraph RoutersLayer["backend/routers/"]
        ChatR["chat.py — POST /chat"]
        HistR["history.py — GET /history"]
        StatsR["stats.py — GET /stats"]
        ModelsR["models.py — GET /models"]
        AnalyticsR["analytics.py — /analytics/*"]
        DecisionsR["decisions.py — GET /routing/decision/{id}"]
        AgentR["agent.py — /agent/*"]
    end

    subgraph Services["backend/services/"]
        Classifier["classifier_service.py"]
        Heuristic["heuristic_classifier.py"]
        Engine["routing_engine.py"]
        CostEst["cost_estimator.py"]
        QualityV["quality_verifier.py"]
        DecisionSvc["decision_service.py"]
        AnalyticsSvc["analytics_service.py"]
        Learning["routing_learning.py"]
        Agent["routing_agent.py"]
        HistorySvc["history_service.py"]
        StatsSvc["stats_service.py"]
        InvestigationSvc["investigation_service.py"]
        QueryHelpers["query_helpers.py"]
    end

    subgraph Providers["backend/services/providers/"]
        Factory["factory.py"]
        Base["base.py — LLMProvider ABC"]
        Gemini["gemini_provider.py"]
        OpenRouter["openrouter_provider.py"]
    end

    subgraph Config["config/ + backend/utils/"]
        RoutingYaml["routing.yaml"]
        PricingYaml["pricing.yaml"]
        YamlLoader["yaml_config.py"]
        Settings["utils/config.py — Settings (.env)"]
        StartupVal["utils/startup_validation.py"]
    end

    subgraph DB["backend/database/ — SQLAlchemy ORM"]
        DbEngine["db.py — engine/session"]
        Models["models.py — 9 tables"]
        Postgres[("Postgres/Supabase<br/>or SQLite (local)")]
    end

    subgraph External["External LLM Providers"]
        GoogleAPI["Google Generative AI API<br/>(Gemini)"]
        OpenRouterAPI["OpenRouter API<br/>(Mistral / DeepSeek / Qwen / Llama)"]
    end

    Browser -->|HTTP| Nginx
    Nginx -->|"/api/*"| API
    Nginx -->|"/*"| ST
    ST -->|httpx to /api/*| Nginx
    ST --- Theme

    API --> Lifespan
    Lifespan --> StartupVal
    API --> Routers --> RoutersLayer

    ChatR --> Classifier
    ChatR --> Engine
    ChatR --> Factory
    ChatR --> CostEst
    ChatR --> QualityV
    ChatR --> DecisionSvc

    HistR --> HistorySvc
    StatsR --> StatsSvc
    ModelsR --> YamlLoader
    AnalyticsR --> AnalyticsSvc
    AnalyticsR --> Learning
    DecisionsR --> DecisionSvc
    AgentR --> Agent
    AgentR --> InvestigationSvc

    Classifier --> Heuristic
    Classifier --> Factory
    Classifier --> CostEst
    QualityV --> Factory
    Engine --> YamlLoader
    Classifier --> YamlLoader
    QualityV --> YamlLoader
    CostEst --> YamlLoader
    Learning --> YamlLoader
    Agent --> YamlLoader

    Factory --> Base
    Factory --> Gemini
    Factory --> OpenRouter
    Gemini --> GoogleAPI
    OpenRouter --> OpenRouterAPI

    YamlLoader --> RoutingYaml
    YamlLoader --> PricingYaml
    StartupVal --> RoutingYaml
    StartupVal --> PricingYaml
    Settings -.env vars.-> Classifier
    Settings -.env vars.-> Factory
    Settings -.env vars.-> DbEngine

    DecisionSvc --> Models
    AnalyticsSvc --> Models
    Learning --> Models
    Agent --> Models
    HistorySvc --> Models
    StatsSvc --> Models
    InvestigationSvc --> Models
    QueryHelpers -.shared SQL expr.-> AnalyticsSvc
    QueryHelpers -.shared SQL expr.-> Learning
    QueryHelpers -.shared SQL expr.-> Agent

    Models --> DbEngine --> Postgres
```

---

## 2. Project Directory Architecture

```mermaid
flowchart LR
    Root["routingbridge/"]

    Root --> BE["backend/"]
    Root --> FE["frontend/"]
    Root --> CFG["config/"]
    Root --> Deploy["deploy/"]
    Root --> Scripts["scripts/"]
    Root --> Tests["tests/"]
    Root --> Docs["docs/"]
    Root --> Infra["Dockerfile, docker-compose.yml, render.yaml"]

    BE --> Main["main.py — FastAPI app + lifespan"]
    BE --> Routers["routers/ — HTTP surface, no business logic"]
    BE --> Services["services/ — business logic"]
    BE --> DBpkg["database/ — SQLAlchemy models + session"]
    BE --> Schemas["schemas/ — Pydantic request/response models"]
    BE --> Utils["utils/ — config, yaml loading, logging, startup checks"]

    Services --> ProvidersDir["providers/ — LLMProvider abstraction"]

    Routers -->|"calls"| Services
    Services -->|"reads/writes"| DBpkg
    Routers -->|"validates with"| Schemas
    Services -->|"returns"| Schemas
    Utils -->|"loaded by"| Services
    Utils -->|"loaded by"| Routers
    ProvidersDir -->|"used by"| Services

    CFG --> RoutingY["routing.yaml — tiers/thresholds/policy"]
    CFG --> PricingY["pricing.yaml — per-model $/1M tokens"]
    CFG -.read by.-> Utils

    FE --> StApp["streamlit_app.py — Chat/History/Analytics/Settings"]
    FE --> ThemeF["theme.py"]
    FE -.HTTP calls.-> Routers

    Deploy --> Nginx2["nginx.conf.template"]
    Deploy --> StartSh["start.sh — boots nginx + FastAPI + Streamlit"]

    Scripts --> Bootstrap["bootstrap_db.py — create_all() + seed RoutingPolicy"]
    Bootstrap -.writes.-> DBpkg

    Tests -.exercises.-> BE

    Docs --> ArchMd["architecture.md, pr1-4 write-ups, production-stabilization.md"]
```

---

## 3. Chat Request Flow (the core, and only, ingestion path)

```mermaid
flowchart TD
    U["User types a message"] --> FEUI["Streamlit chat page"]
    FEUI -->|"httpx POST /api/chat<br/>{prompt}"| Nginx["nginx"]
    Nginx --> Router["chat.py: POST /chat"]
    Router --> Validate["ChatRequest schema validation<br/>(pydantic)"]
    Validate --> ReqId["request_id = uuid4()"]

    ReqId --> Classify["classifier.classify(prompt)"]
    Classify --> LLMClassify{"OpenRouter classifier<br/>call succeeds & parses?"}
    LLMClassify -->|"yes"| Decision["RoutingDecision<br/>(tier, task_type, confidence, reason)"]
    LLMClassify -->|"no: API/JSON error"| Heuristic["heuristic_classifier<br/>word-count fallback"]
    Heuristic --> Decision

    Decision --> RouteSel["routing_engine.select(decision)"]
    RouteSel --> Escalate{"confidence < low<br/>threshold (0.6)?"}
    Escalate -->|"yes"| Bump["tier += 1 (escalated=true)"]
    Escalate -->|"no"| Keep["tier unchanged"]
    Bump --> TierMap
    Keep --> TierMap["map tier -> provider/model<br/>via routing.yaml"]

    TierMap --> ProviderSel["providers.factory.get_provider(name)"]
    ProviderSel --> Gen["provider.generate(prompt, model, max_tokens)"]
    Gen -->|"google"| GeminiCall["Gemini API"]
    Gen -->|"openrouter"| ORCall["OpenRouter API"]
    GeminiCall --> ProviderResp["ProviderResponse<br/>(text, input_tokens, output_tokens)"]
    ORCall --> ProviderResp

    ProviderResp -->|"exception"| FailProvider["decision_service.record_failure()<br/>stage=provider_call -> 502"]
    ProviderResp -->|"ok"| CostCalc["cost_estimator.estimate_cost()<br/>via pricing.yaml"]
    CostCalc -->|"exception"| FailCost["record_failure()<br/>stage=cost_estimation -> 502"]
    CostCalc -->|"ok"| TierCheck{"tier == ADVANCED?"}

    TierCheck -->|"yes: skip"| Persist
    TierCheck -->|"no"| QualityCheck["quality_verifier.verify(prompt, answer)<br/>LLM-judge pass/fail"]
    QualityCheck --> Persist["decision_service.record()<br/>ONE transaction"]

    Persist --> T1[("requests")]
    Persist --> T2[("routing_decisions")]
    Persist --> T3[("execution_results")]
    Persist --> T4[("quality_results (nullable)")]
    Persist -->|"exception"| FailPersist["record_failure()<br/>stage=persistence -> 500"]

    T1 & T2 & T3 & T4 --> Response["ChatResponse schema"]
    Response --> Nginx2["nginx"] --> FEUI2["Streamlit renders answer<br/>+ routing metadata"] --> U2["User sees answer"]
```

---

## 4. Routing Engine Internal Flow

```mermaid
flowchart TD
    In["RoutingDecision<br/>(from classifier or heuristic)"] --> ReadCfg["load_routing_config()<br/>routing.yaml, cached"]

    ReadCfg --> Thresh["confidence_thresholds:<br/>high=0.9, low=0.6,<br/>escalate_on_low_confidence=true"]
    Thresh --> Check{"escalate flag AND<br/>confidence < low?"}

    Check -->|"no"| NoEsc["tier = decision.routing_tier<br/>escalated=false"]
    Check -->|"yes"| NextTier{"_next_tier(tier)<br/>BASIC->STANDARD->ADVANCED"}
    NextTier -->|"tier exists"| Esc["tier = next tier<br/>escalated=true<br/>reason appended"]
    NextTier -->|"already ADVANCED"| NoEsc

    NoEsc --> TierCfg["tiers[tier] from routing.yaml<br/>{provider, model, max_output_tokens, reasons}"]
    Esc --> TierCfg

    TierCfg --> Pricing["pricing.yaml lookup<br/>(separate call, in cost_estimator)"]
    TierCfg --> Result["RoutingResult:<br/>provider, model, max_output_tokens,<br/>tier, original_tier, escalated, reasons[]"]

    Pricing -.consumed later by.-> CostFn["cost_estimator.estimate_cost()"]
    Result --> PolicyStamp["decision_service.record() stamps<br/>routing_policy_version from routing.yaml"]
    PolicyStamp --> DBWrite[("routing_decisions.routing_policy_version")]

    subgraph Note["Never applied automatically"]
      direction TB
      NoteText["optimization_recommendations from routing_learning.py\nare NEVER read by this engine.\nChanging what gets routed requires a human\nediting routing.yaml's tiers block."]
    end
    DBWrite -.-> Note
```

---

## 5. Database Architecture (ER Diagram)

```mermaid
erDiagram
    REQUESTS ||--|| ROUTING_DECISIONS : "1:1 by request_id"
    REQUESTS ||--|| EXECUTION_RESULTS : "1:1 by request_id"
    REQUESTS ||--o| QUALITY_RESULTS : "1:1 optional (skipped for ADVANCED tier)"
    ROUTING_POLICIES ||--o{ ROUTING_DECISIONS : "policy_version referenced (no FK)"
    ROUTING_PATTERNS ||--o{ OPTIMIZATION_RECOMMENDATIONS : "matched by (task_type,tier,provider,model,policy_version), no FK"
    OPTIMIZATION_RECOMMENDATIONS ||--o| ROUTING_DECISIONS : "looked up at read time by attribute match, no FK"

    REQUESTS {
        string request_id PK
        string prompt
        string response
        string normalized_prompt
        string prompt_hash "indexed"
        datetime created_at
    }
    ROUTING_DECISIONS {
        string request_id PK_FK
        string classifier_tier
        string final_tier
        float classifier_confidence
        string task_type
        string task_subcategory "nullable"
        string classifier_reasoning
        string routing_reasoning
        string selected_provider
        string selected_model
        string routing_policy_version
        string escalation_reason "nullable"
    }
    EXECUTION_RESULTS {
        string request_id PK_FK
        bool provider_success
        float latency_ms
        int input_tokens
        int output_tokens
        float estimated_cost
        string error_message "nullable"
    }
    QUALITY_RESULTS {
        string request_id PK_FK
        bool verdict
        float quality_score "nullable, unused"
        string verifier_reasoning
        datetime verified_at
    }
    FAILED_REQUESTS {
        string request_id PK
        string prompt
        string stage
        string provider "nullable"
        string model "nullable"
        string error_message
        string status
        datetime created_at
    }
    ROUTING_POLICIES {
        string version PK
        json config
        bool is_active
        datetime created_at
    }
    ROUTING_PATTERNS {
        int id PK
        string task_type
        string task_subcategory "nullable"
        string provider
        string model
        string tier
        string policy_version
        int sample_size
        float average_cost
        float average_latency
        float pass_rate "nullable"
        float failure_rate "nullable"
        datetime last_updated
    }
    OPTIMIZATION_RECOMMENDATIONS {
        string recommendation_id PK
        string task_type
        string task_subcategory "nullable"
        string policy_version
        string current_provider
        string recommended_provider
        string current_model
        string recommended_model
        float expected_cost_change
        float expected_quality_change
        float confidence
        string reason
        json evidence
        string status
        datetime created_at
    }
    INVESTIGATION_REPORTS {
        string report_id PK
        datetime created_at
        string policy_version
        string executive_summary
        string risk_level
        float confidence
        json findings
        json suggested_actions
        json investigation_steps
        json tools_used
    }
```

**Notes derived from the code, not assumed:**
- `requests → {routing_decisions, execution_results, quality_results}` are only *column-level* `ForeignKey`s — no ORM `relationship()`. `decision_service.record()` calls `db.flush()` after inserting `Request` specifically because Postgres enforces the FK and SQLite (dev) silently didn't (see comment in `decision_service.py`).
- `routing_patterns` and `optimization_recommendations` are **wholesale delete+reinsert** on every `routing_learning.refresh()` — no update-in-place, no history retained.
- `optimization_recommendations` is matched to a `routing_decisions` row at **read time** in `decision_service.get_decision_card()` by exact attribute equality (`policy_version`, `task_type`, `task_subcategory`, `current_provider`/`model`), not a foreign key.

---

## 6. Request Lifecycle (Sequence Diagram)

```mermaid
sequenceDiagram
    actor User
    participant FE as Streamlit
    participant NGINX as nginx
    participant API as FastAPI /chat
    participant CLS as ClassifierService
    participant HEUR as heuristic_classifier
    participant ENG as RoutingEngine
    participant PROV as LLMProvider (Gemini/OpenRouter)
    participant COST as cost_estimator
    participant QV as QualityVerifier
    participant DEC as decision_service
    participant DB as Database

    User->>FE: types prompt, hits send
    FE->>NGINX: POST /api/chat {prompt}
    NGINX->>API: POST /chat
    API->>CLS: classify(prompt)
    alt LLM classifier reachable & valid JSON
        CLS->>PROV: generate(classifier_prompt, response_format=json_object)
        PROV-->>CLS: ProviderResponse
        CLS-->>API: RoutingDecisionOutcome
    else classifier failure
        CLS->>HEUR: classify_heuristically(prompt)
        HEUR-->>CLS: RoutingDecision (fallback)
        CLS-->>API: RoutingDecisionOutcome (fallback_used=true)
    end

    API->>ENG: select(decision)
    ENG-->>API: RoutingResult (provider, model, tier, escalated)

    API->>PROV: generate(prompt, model, max_tokens)
    alt provider call fails
        PROV-->>API: exception
        API->>DEC: record_failure(stage=provider_call)
        DEC->>DB: INSERT failed_requests
        API-->>FE: 502
    else success
        PROV-->>API: ProviderResponse(text, tokens)
        API->>COST: estimate_cost(model, tokens)
        COST-->>API: model_cost
        opt tier != ADVANCED
            API->>QV: verify(prompt, answer)
            QV->>PROV: generate(verdict_prompt, response_format=json_object)
            PROV-->>QV: ProviderResponse
            QV-->>API: QualityVerdict | None
        end
        API->>DEC: record(all fields)
        DEC->>DB: INSERT requests, routing_decisions,<br/>execution_results, quality_results (1 txn)
        DB-->>DEC: commit
        DEC-->>API: ok
        API-->>NGINX: ChatResponse
        NGINX-->>FE: 200 JSON
        FE-->>User: renders answer + routing metadata
    end
```

---

## 7. Component Dependency Graph

```mermaid
flowchart LR
    chat.py --> classifier_service.py
    chat.py --> routing_engine.py
    chat.py --> providers/factory.py
    chat.py --> cost_estimator.py
    chat.py --> quality_verifier.py
    chat.py --> decision_service.py

    classifier_service.py --> heuristic_classifier.py
    classifier_service.py --> providers/factory.py
    classifier_service.py --> cost_estimator.py
    classifier_service.py --> yaml_config.py

    quality_verifier.py --> providers/factory.py
    quality_verifier.py --> classifier_service.py
    quality_verifier.py --> yaml_config.py

    routing_engine.py --> yaml_config.py
    cost_estimator.py --> yaml_config.py

    providers/factory.py --> providers/gemini_provider.py
    providers/factory.py --> providers/openrouter_provider.py
    providers/gemini_provider.py --> providers/base.py
    providers/openrouter_provider.py --> providers/base.py

    decision_service.py --> database/models.py
    decision_service.py --> yaml_config.py
    decision_service.py --> schemas/decision_card.py

    analytics.py --> analytics_service.py
    analytics.py --> routing_learning.py
    analytics_service.py --> database/models.py
    analytics_service.py --> query_helpers.py
    routing_learning.py --> database/models.py
    routing_learning.py --> query_helpers.py
    routing_learning.py --> yaml_config.py

    agent.py --> routing_agent.py
    agent.py --> investigation_service.py
    routing_agent.py --> database/models.py
    routing_agent.py --> query_helpers.py
    routing_agent.py --> yaml_config.py
    investigation_service.py --> database/models.py

    decisions.py --> decision_service.py
    history.py --> history_service.py
    history_service.py --> database/models.py
    stats.py --> stats_service.py
    stats_service.py --> database/models.py
    stats_service.py --> cost_estimator.py
    stats_service.py --> yaml_config.py
    models.py --> yaml_config.py

    main.py --> chat.py & history.py & stats.py & models.py & analytics.py & decisions.py & agent.py
    main.py --> startup_validation.py
    startup_validation.py --> yaml_config.py
```

---

## 8. Class Diagram

```mermaid
classDiagram
    class LLMProvider {
        <<abstract>>
        +generate(prompt, model, max_tokens, response_format) ProviderResponse
    }
    class GeminiProvider {
        -api_key
        +generate(...) ProviderResponse
    }
    class OpenRouterProvider {
        -api_key
        +generate(...) ProviderResponse
    }
    class ProviderResponse {
        +text: str
        +input_tokens: int
        +output_tokens: int
    }
    LLMProvider <|.. GeminiProvider
    LLMProvider <|.. OpenRouterProvider
    LLMProvider ..> ProviderResponse : returns

    class ClassifierService {
        -settings: Settings
        -provider: LLMProvider
        +classify(prompt) RoutingDecisionOutcome
        -_classify_with_llm(prompt)
    }
    class QualityVerifier {
        -provider: LLMProvider
        +verify(prompt, response) QualityVerdict
    }
    class RoutingEngine {
        -_config: dict
        +select(decision: RoutingDecision) RoutingResult
        -_next_tier(tier)
    }
    ClassifierService --> LLMProvider : uses
    QualityVerifier --> LLMProvider : uses
    ClassifierService ..> RoutingDecisionOutcome : returns

    class RoutingDecision {
        +routing_tier: RoutingTier
        +task_type: str
        +reasoning_level: ReasoningLevel
        +confidence: float
        +reason: str
    }
    class RoutingDecisionOutcome {
        +decision: RoutingDecision
        +classifier_model: str
        +latency_ms: float
        +input_tokens: int
        +output_tokens: int
        +cost: float
        +fallback_used: bool
    }
    class RoutingResult {
        +provider: str
        +model: str
        +max_output_tokens: int
        +tier: RoutingTier
        +original_tier: RoutingTier
        +escalated: bool
        +reasons: list~str~
    }
    class RoutingTier {
        <<enum>>
        BASIC
        STANDARD
        ADVANCED
    }
    RoutingDecisionOutcome --> RoutingDecision
    RoutingEngine ..> RoutingDecision : consumes
    RoutingEngine ..> RoutingResult : produces
    RoutingDecision --> RoutingTier

    class Request {
        +request_id: str
        +prompt: str
        +response: str
        +normalized_prompt: str
        +prompt_hash: str
        +created_at: datetime
    }
    class RoutingDecisionRow {
        +request_id: str
        +classifier_tier: str
        +final_tier: str
        +selected_provider: str
        +selected_model: str
        +routing_policy_version: str
    }
    class ExecutionResult {
        +request_id: str
        +latency_ms: float
        +input_tokens: int
        +output_tokens: int
        +estimated_cost: float
    }
    class QualityResult {
        +request_id: str
        +verdict: bool
        +verifier_reasoning: str
    }
    Request "1" --> "1" RoutingDecisionRow : request_id
    Request "1" --> "1" ExecutionResult : request_id
    Request "1" --> "0..1" QualityResult : request_id

    class DecisionCard {
        +request_id: str
        +selected_provider: str
        +selected_model: str
        +reasoning_steps: list~DecisionReason~
        +recommendation_available: bool
    }
    class decision_service {
        <<module>>
        +record(...)
        +record_failure(...)
        +get_decision_card(db, request_id) DecisionCard
    }
    decision_service ..> DecisionCard : builds
    decision_service ..> Request
    decision_service ..> RoutingDecisionRow
    decision_service ..> ExecutionResult
    decision_service ..> QualityResult
```

---

## 9. Provider Architecture

```mermaid
flowchart TD
    Caller["chat.py / classifier_service.py / quality_verifier.py"]
    Caller --> FactoryFn["factory.get_provider(name, settings)"]

    FactoryFn -->|"name == 'google'"| GP["GeminiProvider(api_key)"]
    FactoryFn -->|"name == 'openrouter'"| ORP["OpenRouterProvider(api_key)"]
    FactoryFn -->|"anything else"| Err["raise ValueError"]

    GP -.implements.-> Iface["LLMProvider (ABC)<br/>generate(prompt, model, max_tokens, response_format)"]
    ORP -.implements.-> Iface

    GP --> GSDK["google.generativeai SDK<br/>GenerativeModel.generate_content()"]
    GSDK --> GAPI["Google Generative AI API"]

    ORP --> HttpxCall["httpx.post(OPENROUTER_URL)<br/>OpenAI-compatible /chat/completions"]
    HttpxCall --> ORAPI["OpenRouter API<br/>(routes to Mistral / DeepSeek / Qwen / Llama)"]

    Iface --> Norm["ProviderResponse<br/>{text, input_tokens, output_tokens}<br/>identical shape regardless of SDK"]

    subgraph Future["Adding a third provider"]
      direction LR
      NewClass["Write one new class implementing LLMProvider"]
      NewClass -.no changes needed in.-> Caller
      NewClass -.no changes needed in.-> RoutingEngine2["routing_engine.py"]
    end
```

---

## 10. Configuration Flow

```mermaid
flowchart TD
    EnvFile[".env / environment variables"] --> SettingsCls["utils/config.py: Settings(BaseSettings)<br/>google_api_key, openrouter_api_key,<br/>database_url, log_level,<br/>easy_max_words, medium_max_words"]
    SettingsCls -->|"get_settings(), lru_cache"| SettingsSingleton(("Settings singleton<br/>(1 per process)"))

    RoutingYamlFile["config/routing.yaml"] --> YamlLoad["utils/yaml_config.py:<br/>load_routing_config() / load_pricing_config()"]
    PricingYamlFile["config/pricing.yaml"] --> YamlLoad
    YamlLoad -->|"cached"| YamlSingleton(("parsed config dicts"))

    SettingsSingleton --> DbEngineC["database/db.py: create_engine(database_url)"]
    SettingsSingleton --> ProviderKeys["providers/factory.py: reads *_api_key"]
    SettingsSingleton --> HeuristicCfg["heuristic_classifier.py: easy/medium_max_words"]

    YamlSingleton --> RoutingEngineC["routing_engine.py: tiers, confidence_thresholds"]
    YamlSingleton --> ClassifierCfgC["classifier_service.py: classifier provider/model"]
    YamlSingleton --> QualityCfgC["quality_verifier.py: judge model"]
    YamlSingleton --> CostCfgC["cost_estimator.py: per-model pricing"]
    YamlSingleton --> LearningCfgC["routing_learning.py: min_sample_size,<br/>learning.apply_recommendations"]
    YamlSingleton --> AgentCfgC["routing_agent.py: policy_version, min_sample_size"]
    YamlSingleton --> ModelsEndpointC["routers/models.py: exposes config read-only"]
    YamlSingleton --> DecisionSvcC["decision_service.py: stamps routing_policy_version"]

    RoutingYamlFile --> StartupValC["utils/startup_validation.py<br/>fails fast at boot on:<br/>unknown provider, unpriced model,<br/>inverted confidence thresholds"]
    PricingYamlFile --> StartupValC
    StartupValC -->|"blocks boot on failure"| MainApp["main.py lifespan()"]

    RoutingYamlFile -.snapshotted manually via.-> BootstrapScript["scripts/bootstrap_db.py"]
    BootstrapScript --> PolicyTable[("routing_policies table")]
```

`policy_version` inside `routing.yaml` is bumped by hand whenever tiers/thresholds change; it is the join key between a routing decision and the exact policy that produced it.

---

## 11. Analytics Pipeline

```mermaid
flowchart TD
    RawTables[("requests, routing_decisions,<br/>execution_results, quality_results")]

    RawTables --> AnalyticsSvc2["analytics_service.py<br/>(read-only aggregation)"]
    AnalyticsSvc2 --> Overview["GET /analytics/routing<br/>providers[], models[], task_types[],<br/>tier_distribution, daily_metrics"]
    AnalyticsSvc2 --> PatternsEP["GET /analytics/patterns<br/>-> routing_patterns table"]
    AnalyticsSvc2 --> RecsEP["GET /analytics/recommendations<br/>-> optimization_recommendations table"]

    RawTables --> StatsSvc2["stats_service.py"]
    StatsSvc2 --> StatsEP["GET /stats<br/>total_requests, total_cost, avg_latency,<br/>estimated_savings vs ADVANCED tier,<br/>quality_pass_rate"]

    RawTables --> HistorySvc2["history_service.py"]
    HistorySvc2 --> HistoryEP["GET /history<br/>joined per-request rows, paginated"]

    RawTables -->|"explicit POST trigger only"| RefreshEP["POST /analytics/refresh"]
    RefreshEP --> LearningModule["routing_learning.py<br/>(see Learning Pipeline)"]
    LearningModule --> PatternsTable[("routing_patterns")]
    LearningModule --> RecsTable[("optimization_recommendations")]
    PatternsTable -.feed.-> PatternsEP
    RecsTable -.feed.-> RecsEP

    QueryHelpers2["query_helpers.py: PASS_RATE<br/>(shared CASE/AVG expression)"] -.used by.-> AnalyticsSvc2
    QueryHelpers2 -.used by.-> LearningModule
    QueryHelpers2 -.used by.-> Agent2["routing_agent.py"]
```

---

## 12. Learning Pipeline (`routing_learning.refresh()`)

```mermaid
flowchart TD
    Trigger["POST /analytics/refresh<br/>(manual only — no schedule, no live-path write)"] --> Scan["Query: routing_decisions<br/>JOIN execution_results<br/>OUTER JOIN quality_results"]

    Scan --> Group["GROUP BY task_type, task_subcategory,<br/>provider, model, tier, policy_version"]
    Group --> Agg["Aggregate per group:<br/>sample_size = COUNT<br/>average_cost = AVG(estimated_cost)<br/>average_latency = AVG(latency_ms)<br/>pass_rate = PASS_RATE expr"]

    Agg --> WipePatterns["DELETE all routing_patterns"]
    WipePatterns --> InsertPatterns["INSERT recomputed rows"]
    InsertPatterns --> PatternsT[("routing_patterns")]

    PatternsT --> RecLoop["For each (task_type, tier)<br/>under CURRENT policy_version:"]
    RecLoop --> FindCurrent["find pattern matching<br/>routing.yaml's configured provider/model"]
    FindCurrent --> FindBest{"any candidate pattern with<br/>sample_size >= min_sample_size (20)<br/>AND pass_rate > current.pass_rate?"}
    FindBest -->|"no"| Skip["no recommendation for this group"]
    FindBest -->|"yes"| Best["pick candidate with max pass_rate"]
    Best --> BuildRec["build OptimizationRecommendation<br/>(expected_cost_change, expected_quality_change,<br/>confidence=best.pass_rate, evidence JSON)"]

    BuildRec --> WipeRecs["DELETE all optimization_recommendations"]
    WipeRecs --> InsertRecs["INSERT new recommendations"]
    InsertRecs --> RecsT[("optimization_recommendations")]

    RecsT -.never read by.-x RoutingEngineNote["routing_engine.py<br/>(advisory only — human must bump<br/>routing.yaml policy_version to act on it)"]
```

---

## 13. Decision Card Generation

```mermaid
flowchart TD
    Req["GET /routing/decision/{request_id}"] --> DecisionsRouter["decisions.py"]
    DecisionsRouter --> GetCard["decision_service.get_decision_card(db, request_id)"]

    GetCard --> JoinQuery["SELECT Request, RoutingDecision, ExecutionResult<br/>JOIN ON request_id<br/>WHERE request_id = :id"]
    JoinQuery -->|"no row"| NotFound["return None -> 404"]
    JoinQuery -->|"row found"| Unpack["request, decision, execution"]

    Unpack --> RecLookup["_find_matching_recommendation():<br/>optimization_recommendations WHERE<br/>policy_version, task_type, task_subcategory,<br/>current_provider, current_model all match"]

    Unpack --> Steps["_build_reasoning_steps(decision)<br/>deterministic, derived from stored columns:<br/>1. task classified as X<br/>2. confidence + initial tier<br/>3. escalated? or tier selected<br/>4. tier -> provider/model under policy<br/>5. final routing complete"]

    RecLookup --> CardBuild["assemble DecisionCard"]
    Steps --> CardBuild
    Unpack --> CardBuild

    CardBuild --> Response2["DecisionDetailResponse<br/>{decision_card, recommendation | null}"]
    Response2 --> DecisionsRouter --> ClientResp["JSON to caller"]

    NoteBox["No LLM call, no write.<br/>Pure read + join + deterministic text generation."]
    CardBuild -.-> NoteBox
```

---

## 14. Agent Pipeline (`routing_agent.investigate()`)

```mermaid
flowchart TD
    Trigger2["POST /agent/investigate<br/>(manual trigger, no LLM call anywhere in this module)"] --> LoadCfg["load routing.yaml:<br/>policy_version, min_sample_size"]

    LoadCfg --> LoadPatterns["query routing_patterns<br/>WHERE policy_version = current"]

    LoadPatterns --> F1["_find_degraded_task_types()<br/>pass_rate < 0.70 AND sample_size >= min_sample_size<br/>-> risk=high"]
    LoadPatterns --> F2["_find_expensive_task_type()<br/>max(average_cost) > 1.5x other-types average<br/>-> risk=medium"]
    LoadPatterns --> F3["_detect_cost_anomaly()<br/>query requests+execution_results grouped by day;<br/>latest day cost/request > 1.5x prior average<br/>-> risk=medium"]
    LoadPatterns --> F4["_compare_policy_versions()<br/>weighted avg cost/pass_rate per policy_version<br/>-> risk=low"]
    LoadPatterns --> F5["_validate_recommendations()<br/>re-query LIVE routing_decisions/execution_results/<br/>quality_results (not routing_patterns) for every<br/>pending optimization_recommendation;<br/>still holds? -> risk=low : risk=medium"]

    F1 & F2 & F3 & F4 & F5 --> Findings["findings: list[Finding]<br/>{category, summary, risk_level, confidence, evidence}"]

    Findings --> SuggestActions["_build_suggested_actions()<br/>degraded model -> 'investigate before next policy review'<br/>trustworthy recommendation -> 'review and consider approving'"]
    Findings --> OverallRisk["_overall_risk() = max risk across findings"]
    Findings --> OverallConf["_overall_confidence() = mean confidence"]
    Findings --> ExecSummary["_build_executive_summary()<br/>'{n} finding(s) ({breakdown}); overall risk: {risk}.'"]

    SuggestActions & OverallRisk & OverallConf & ExecSummary --> ReportBuild["InvestigationReport<br/>{report_id, policy_version, executive_summary,<br/>findings, suggested_actions, risk_level,<br/>confidence, investigation_steps, tools_used}"]

    ReportBuild --> PersistReport["INSERT investigation_reports"]
    PersistReport --> ReportsTable[("investigation_reports")]

    ReportsTable -.read by.-> AgentReportsEP["GET /agent/reports (list, paginated)"]
    ReportsTable -.read by.-> AgentReportEP["GET /agent/report/{id}"]

    ConstraintNote["Writes ONLY to investigation_reports.<br/>Never touches routing.yaml, routing_decisions,<br/>routing_patterns, or optimization_recommendations."]
    ReportBuild -.-> ConstraintNote
```

---

## 15. External Integrations

```mermaid
flowchart LR
    App["RoutingBridge backend"]

    App -->|"native SDK, API key from Settings.google_api_key"| Google["Google Generative AI API<br/>(Gemini 2.5 Flash — BASIC tier)"]
    App -->|"REST, Bearer token from Settings.openrouter_api_key"| OpenRouterExt["OpenRouter API<br/>(single gateway to:<br/>Mistral Small 3.2 — classifier + judge + STANDARD tier<br/>DeepSeek R1 — ADVANCED tier)"]
    App -->|"SQLAlchemy, DATABASE_URL"| DBExt[("Postgres / Supabase<br/>(prod) or SQLite (local dev)")]
    App -.reads at boot + per-request, no network.-> ConfigFiles["config/routing.yaml<br/>config/pricing.yaml<br/>(local filesystem, not a config service)"]
    App -.reads once at boot, lru_cache.-> EnvVars[".env / process environment"]

    Nginx3["nginx (deploy/nginx.conf.template)"] --> App
    Nginx3 --> StreamlitExt["Streamlit frontend (same container)"]

    RenderPlatform["Render.com<br/>(render.yaml: web service)"] -.hosts.-> Nginx3
```

No object storage, no vector DB, no message queue, no cache layer (Redis/etc.), and no external auth provider exist in this codebase — confirmed by the absence of any such client/import across `backend/` and `requirements.txt`.

---

## 16. End-to-End Master Flow

```mermaid
flowchart TB
    User3["User"] --> FE3["Streamlit Frontend"]
    FE3 -->|"HTTP via nginx"| FastAPI3["FastAPI (main.py)"]
    FastAPI3 --> ChatEndpoint["POST /chat"]

    ChatEndpoint --> Classify2["Classification<br/>(OpenRouter LLM, fallback: word-count heuristic)"]
    Classify2 --> RoutingLogic["Routing Engine<br/>(tier selection + confidence escalation via routing.yaml)"]
    RoutingLogic --> ProviderLayer2["Provider Layer<br/>(GeminiProvider / OpenRouterProvider)"]
    ProviderLayer2 --> LLMCall["External LLM<br/>(Gemini / Mistral / DeepSeek)"]
    LLMCall --> BizLogic["Business Logic<br/>(cost_estimator + quality_verifier)"]
    BizLogic --> Persistence["Persistence<br/>(decision_service.record() — 1 transaction,<br/>4 normalized tables)"]
    Persistence --> DB2[("Postgres/Supabase")]

    DB2 --> Analytics2["Analytics<br/>(GET /stats, /analytics/routing,<br/>/history — read-only aggregation)"]
    DB2 -->|"manual POST /analytics/refresh"| Learning2["Learning<br/>(routing_learning.py:<br/>routing_patterns + optimization_recommendations)"]
    DB2 --> DecisionCard2["Decision Card<br/>(GET /routing/decision/{id}:<br/>join + deterministic reasoning steps)"]
    Learning2 --> DB2
    DB2 -->|"manual POST /agent/investigate"| AgentPipeline["Agent<br/>(routing_agent.py: 5 deterministic checks<br/>-> InvestigationReport)"]
    AgentPipeline --> DB2

    Analytics2 --> FE3
    DecisionCard2 --> FE3
    AgentPipeline -->|"GET /agent/reports"| FE3
    Persistence --> ChatEndpoint --> FastAPI3 --> FE3 --> User3

    ConfigLayer2["Configuration<br/>(routing.yaml, pricing.yaml, .env)"] -.governs.-> Classify2
    ConfigLayer2 -.governs.-> RoutingLogic
    ConfigLayer2 -.governs.-> ProviderLayer2
    ConfigLayer2 -.governs.-> BizLogic
    ConfigLayer2 -.governs.-> Learning2
    ConfigLayer2 -.governs.-> AgentPipeline
    ConfigLayer2 -.validated at boot by.-> StartupGate["startup_validation.py<br/>(fails app boot on bad config)"]
```

---

## Appendix: things this document deliberately does NOT show

Because they don't exist in the code (verified by reading every file, not inferred):

- PDF/document ingestion, chunking, embeddings, or a vector database
- A message queue, background job worker, or cron/scheduler (refresh and investigate are both synchronous, manually-triggered HTTP endpoints)
- A cache layer (Redis, in-memory TTL cache, etc.) — only `functools.lru_cache` on singleton service instances
- User authentication/authorization — every endpoint is unauthenticated
- Multi-tenancy — there is exactly one routing policy active at a time, globally
