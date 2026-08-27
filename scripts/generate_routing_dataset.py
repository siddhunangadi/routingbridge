"""Create a diverse, explicitly unreviewed routing dataset."""

from backend.schemas.routing_decision import ReasoningLevel, RoutingTier
from backend.services.routing_evaluation import RoutingExample, assign_group_splits, write_dataset

TOPICS = [
    "France", "HTTP", "customer support", "product catalog", "Python", "PostgreSQL", "FastAPI",
    "Docker", "Kubernetes", "Kafka", "payment processing", "logistics", "health records", "education",
    "retail inventory", "mobile apps", "climate data", "sports results", "legal documents", "marketing copy",
    "user profiles", "email messages", "CSV files", "security alerts", "image metadata", "travel plans",
    "subscription billing", "database backups", "search results", "API documentation", "incident reports",
    "feature flags", "analytics dashboards", "team meetings", "service metrics",
]

FAMILIES = [
    (RoutingTier.BASIC, "factual", ReasoningLevel.LOW, "factual_lookup", "What is {topic}?"),
    (RoutingTier.BASIC, "definition", ReasoningLevel.LOW, "simple_definition", "Define {topic} in one sentence."),
    (RoutingTier.BASIC, "extraction", ReasoningLevel.LOW, "simple_extraction", "Extract the key name from this {topic} text."),
    (RoutingTier.BASIC, "transformation", ReasoningLevel.LOW, "simple_transformation", "Rewrite this {topic} sentence in uppercase."),
    (RoutingTier.BASIC, "arithmetic", ReasoningLevel.LOW, "simple_arithmetic", "Calculate 12 plus 7 for a {topic} example."),
    (RoutingTier.BASIC, "coding", ReasoningLevel.LOW, "simple_coding", "Write a Python function that prints {topic}."),
    (RoutingTier.BASIC, "formatting", ReasoningLevel.LOW, "simple_formatting", "Format these {topic} items as a bullet list."),
    (RoutingTier.BASIC, "classification", ReasoningLevel.LOW, "simple_classification", "Classify this {topic} request as urgent or normal."),
    (RoutingTier.BASIC, "qa", ReasoningLevel.LOW, "direct_qa", "Give a direct answer about {topic}."),
    (RoutingTier.BASIC, "conversion", ReasoningLevel.LOW, "unit_conversion", "Convert 5 units of {topic} into 5000 smaller units."),
    (RoutingTier.STANDARD, "summarization", ReasoningLevel.MEDIUM, "summarization", "Summarize this {topic} article into five action items."),
    (RoutingTier.STANDARD, "explanation", ReasoningLevel.MEDIUM, "technical_explanation", "Explain {topic} with a concrete example."),
    (RoutingTier.STANDARD, "comparison", ReasoningLevel.MEDIUM, "comparison", "Compare two approaches to {topic} for a small application."),
    (RoutingTier.STANDARD, "coding", ReasoningLevel.MEDIUM, "crud_coding", "Write a validated FastAPI CRUD endpoint for {topic}."),
    (RoutingTier.STANDARD, "debugging", ReasoningLevel.MEDIUM, "moderate_debugging", "Debug a {topic} request that returns an incorrect result."),
    (RoutingTier.STANDARD, "transformation", ReasoningLevel.MEDIUM, "structured_transformation", "Transform {topic} notes into a structured JSON summary."),
    (RoutingTier.STANDARD, "planning", ReasoningLevel.MEDIUM, "bounded_planning", "Create a three-step implementation plan for {topic} with constraints."),
    (RoutingTier.STANDARD, "reasoning", ReasoningLevel.MEDIUM, "moderate_reasoning", "Reason through the trade-offs in a {topic} decision."),
    (RoutingTier.STANDARD, "analysis", ReasoningLevel.MEDIUM, "moderate_analysis", "Analyze a {topic} report and identify two risks."),
    (RoutingTier.STANDARD, "integration", ReasoningLevel.MEDIUM, "api_integration", "Explain how to integrate a {topic} API with validation."),
    (RoutingTier.ADVANCED, "architecture", ReasoningLevel.HIGH, "system_architecture", "Design a multi-tenant {topic} architecture for millions of users."),
    (RoutingTier.ADVANCED, "distributed_systems", ReasoningLevel.HIGH, "distributed_design", "Design a fault-tolerant distributed {topic} system with failure isolation."),
    (RoutingTier.ADVANCED, "debugging", ReasoningLevel.HIGH, "complex_debugging", "Diagnose a distributed {topic} failure with stale data and duplicate events."),
    (RoutingTier.ADVANCED, "planning", ReasoningLevel.HIGH, "long_horizon_planning", "Plan a zero-downtime, multi-region {topic} migration with rollback."),
    (RoutingTier.ADVANCED, "analysis", ReasoningLevel.HIGH, "constraint_analysis", "Evaluate {topic} under conflicting reliability, cost, and compliance constraints."),
    (RoutingTier.ADVANCED, "security", ReasoningLevel.HIGH, "security_architecture", "Design secure {topic} access controls, audit trails, and incident response."),
    (RoutingTier.ADVANCED, "scalability", ReasoningLevel.HIGH, "scalability_design", "Design a globally scalable {topic} platform with capacity planning."),
    (RoutingTier.ADVANCED, "reasoning", ReasoningLevel.HIGH, "difficult_reasoning", "Develop a multi-stage {topic} decision with competing stakeholder constraints."),
    (RoutingTier.ADVANCED, "coding", ReasoningLevel.HIGH, "difficult_code_reasoning", "Review a complex concurrent {topic} implementation and propose a safe redesign."),
    (RoutingTier.ADVANCED, "tradeoff", ReasoningLevel.HIGH, "tradeoff_analysis", "Compare distributed {topic} designs across latency, recovery, and operating cost."),
]


def generate_dataset() -> list[RoutingExample]:
    regression = RoutingExample(
        prompt_id="reg-basic-france-capital", prompt="What is the capital of France?",
        expected_tier=RoutingTier.BASIC, task_type="factual", reasoning_level=ReasoningLevel.LOW,
        prompt_family="capital_facts", source="production_regression", provenance="production_regression",
        review_status="pending_human_review", reviewer=None, review_timestamp=None,
        review_notes="Canonical regression; owner review still required.", adjudication_status="not_required",
        dataset_version="routing-dataset-v2", dataset_split="test", critical=True,
    )
    rows = []
    for tier, task_type, reasoning_level, family, template in FAMILIES:
        for index, topic in enumerate(TOPICS):
            rows.append(RoutingExample(
                prompt_id=f"ai-{tier.value.lower()}-{family}-{index:02d}", prompt=template.format(topic=topic),
                expected_tier=tier, task_type=task_type, reasoning_level=reasoning_level, prompt_family=family,
                source="synthetic", provenance="AI_generated", review_status="pending_owner_review",
                reviewer=None, review_timestamp=None, review_notes="Generated routing candidate; owner review required.",
                adjudication_status="not_required", dataset_version="routing-dataset-v2", dataset_split="unassigned",
            ))
    return [regression, *assign_group_splits(rows)]


if __name__ == "__main__":
    write_dataset(generate_dataset())
