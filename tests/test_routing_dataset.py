from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.schemas.routing_decision import ReasoningLevel, RoutingTier
from backend.services.routing_evaluation import (
    RoutingExample,
    assign_group_splits,
    load_dataset,
    review_example,
    validate_group_splits,
)
from scripts.generate_routing_dataset import generate_dataset


def _example(prompt_id: str, family: str, split: str = "unassigned") -> RoutingExample:
    return RoutingExample(
        prompt_id=prompt_id,
        prompt=f"Prompt {prompt_id}",
        expected_tier=RoutingTier.BASIC,
        task_type="factual",
        reasoning_level=ReasoningLevel.LOW,
        prompt_family=family,
        source="authored",
        review_status="pending_human_review",
        adjudication_status="not_required",
        dataset_split=split,
    )


def test_dataset_schema_requires_a_nonempty_expected_label():
    with pytest.raises(ValidationError):
        RoutingExample(
            prompt_id="missing-label",
            prompt="What is HTTP?",
            task_type="factual",
            reasoning_level="Low",
            prompt_family="protocol_facts",
            source="authored",
            review_status="unreviewed",
            adjudication_status="not_required",
            dataset_split="unassigned",
        )


def test_dataset_schema_rejects_invalid_tier():
    with pytest.raises(ValidationError):
        RoutingExample(
            **{
                **_example("bad-tier", "facts").model_dump(),
                "expected_tier": "PREMIUM",
            }
        )


def test_loader_rejects_duplicate_prompt_ids(tmp_path):
    path = tmp_path / "duplicates.jsonl"
    row = _example("duplicate", "facts").model_dump_json()
    path.write_text(f"{row}\n{row}\n")

    with pytest.raises(ValueError, match="Duplicate prompt_id"):
        load_dataset(path)


def test_group_aware_split_is_reproducible_and_keeps_families_together():
    examples = [
        _example(f"{family}-{variant}", f"family-{family}")
        for family in range(10)
        for variant in range(2)
    ]

    first = assign_group_splits(examples, seed=42)
    second = assign_group_splits(examples, seed=42)

    assert [row.dataset_split for row in first] == [row.dataset_split for row in second]
    validate_group_splits(first)
    family_splits = {
        family: {row.dataset_split for row in first if row.prompt_family == family}
        for family in {row.prompt_family for row in first}
    }
    assert all(len(splits) == 1 for splits in family_splits.values())
    assert {row.dataset_split for row in first} == {"train", "validation", "test"}


def test_group_leakage_is_rejected():
    rows = [_example("a", "same-family", "train"), _example("b", "same-family", "test")]

    with pytest.raises(ValueError, match="Group leakage"):
        validate_group_splits(rows)


def test_review_disagreement_requires_adjudication():
    reviewed = review_example(
        _example("review", "facts"),
        reviewer="reviewer-one",
        action="approve",
        timestamp=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    disputed = review_example(
        reviewed,
        reviewer="reviewer-two",
        action="change",
        expected_tier=RoutingTier.STANDARD,
        notes="Requires explanation",
        timestamp=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )

    assert disputed.review_status == "needs_adjudication"
    assert disputed.adjudication_status == "needs_adjudication"
    assert disputed.expected_tier is RoutingTier.BASIC
    assert len(disputed.reviews) == 2


def test_adjudication_records_explicit_final_label():
    disputed = review_example(
        review_example(_example("review", "facts"), reviewer="one", action="approve"),
        reviewer="two",
        action="change",
        expected_tier=RoutingTier.STANDARD,
    )

    final = review_example(
        disputed,
        reviewer="adjudicator",
        action="adjudicate",
        expected_tier=RoutingTier.BASIC,
        notes="Single-step factual lookup",
    )

    assert final.review_status == "human_adjudicated"
    assert final.adjudication_status == "adjudicated"
    assert final.expected_tier is RoutingTier.BASIC
    assert final.reviewer == "adjudicator"
    assert final.review_timestamp is not None


def test_repository_regression_corpus_keeps_france_case_pending_human_review():
    rows = load_dataset()
    france = next(row for row in rows if row.prompt == "What is the capital of France?")

    assert france.expected_tier is RoutingTier.BASIC
    assert france.source == "production_regression"
    assert france.review_status == "pending_human_review"
    assert france.reviewer is None
    assert france.critical is True


def test_generated_dataset_has_truthful_owner_review_metadata(tmp_path):
    rows = generate_dataset()

    assert len(rows) >= 1000
    generated = [row for row in rows if row.provenance == "AI_generated"]
    assert generated
    assert all(row.review_status == "pending_owner_review" for row in generated)
    assert all(row.reviewer is None and row.review_timestamp is None for row in generated)
    assert {row.expected_tier for row in rows} == set(RoutingTier)
    assert {row.dataset_split for row in rows} == {"train", "validation", "test"}
    validate_group_splits(rows)


def test_canonical_regression_stays_in_test_split():
    france = next(row for row in generate_dataset() if row.prompt_id == "reg-basic-france-capital")
    assert france.dataset_split == "test"
