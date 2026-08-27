"""List or record explicit human reviews for routing-evaluation prompts."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.schemas.routing_decision import RoutingTier
from backend.services.routing_evaluation import (
    DATASET_PATH,
    load_dataset,
    review_example,
    write_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--prompt-id")
    parser.add_argument("--action", choices=("approve", "change", "ambiguous", "adjudicate"))
    parser.add_argument("--expected-tier", choices=tuple(tier.value for tier in RoutingTier))
    parser.add_argument("--reviewer")
    parser.add_argument("--notes")
    args = parser.parse_args()

    rows = load_dataset(args.dataset)
    if not args.prompt_id:
        pending = [
            {
                "prompt_id": row.prompt_id,
                "prompt": row.prompt,
                "current_predicted_tier": row.predicted_tier,
                "proposed_expected_tier": row.expected_tier.value,
                "task_type": row.task_type,
                "reasoning_level": row.reasoning_level.value,
                "prompt_family": row.prompt_family,
                "source": row.source,
                "review_status": row.review_status,
                "notes": row.review_notes,
            }
            for row in rows
            if row.review_status not in {"human_reviewed", "human_adjudicated"}
        ]
        print(json.dumps(pending, indent=2))
        return 0

    if not args.action or not args.reviewer:
        parser.error("--action and --reviewer are required when --prompt-id is used")
    try:
        index = next(i for i, row in enumerate(rows) if row.prompt_id == args.prompt_id)
    except StopIteration:
        parser.error(f"unknown prompt_id: {args.prompt_id}")
    tier = RoutingTier(args.expected_tier) if args.expected_tier else None
    rows[index] = review_example(
        rows[index],
        reviewer=args.reviewer,
        action=args.action,
        expected_tier=tier,
        notes=args.notes,
    )
    write_dataset(rows, args.dataset)
    print(rows[index].model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
