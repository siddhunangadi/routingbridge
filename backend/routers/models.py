"""GET /models — the currently active routing tiers, providers, models,
pricing and thresholds, straight from routing.yaml/pricing.yaml.

Read-only by design: editing thresholds means editing the YAML file and
restarting, not a PUT endpoint that writes config at runtime. That would
mean detecting file writes, race conditions between concurrent edits, and
cache invalidation for a page whose entire job is "show me what's
configured" — real complexity with no corresponding benefit here.
"""

from fastapi import APIRouter

from backend.utils.yaml_config import load_pricing_config, load_routing_config

router = APIRouter()


@router.get("/models")
def get_models() -> dict:
    routing_cfg = load_routing_config()
    pricing_cfg = load_pricing_config()["models"]

    tiers = {}
    for tier_name, tier_cfg in routing_cfg["tiers"].items():
        pricing = pricing_cfg.get(tier_cfg["model"], {})
        tiers[tier_name] = {
            "provider": tier_cfg["provider"],
            "model": tier_cfg["model"],
            "max_output_tokens": tier_cfg["max_output_tokens"],
            "reasons": tier_cfg["reasons"],
            "input_per_million": pricing.get("input_per_million"),
            "output_per_million": pricing.get("output_per_million"),
        }

    return {
        "classifier": routing_cfg["classifier"],
        "confidence_thresholds": routing_cfg["confidence_thresholds"],
        "tiers": tiers,
    }
