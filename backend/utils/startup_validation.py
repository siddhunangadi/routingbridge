"""Startup-time validation of routing.yaml / pricing.yaml consistency.

Every check here answers one question: "if this config is wrong, would a
request only find out at request time, in a way that costs money or
silently misroutes traffic?" A model in routing.yaml with no pricing.yaml
entry, an unknown provider name, or an inverted confidence threshold are
all mistakes that today only surface the first time a request happens to
hit that code path. Failing fast at boot turns that into an immediate,
readable startup error instead.

`validate_startup_config()` collects every problem it finds and raises
once with the full list — hitting one broken tier out of three shouldn't
require a fix-and-restart cycle per issue to see the other two.
"""

from backend.utils.yaml_config import load_pricing_config, load_routing_config

VALID_PROVIDERS = {"google", "openrouter"}
REQUIRED_TIERS = ("basic", "standard", "advanced")


class StartupConfigError(RuntimeError):
    """Raised when routing.yaml/pricing.yaml fail validation at startup."""


def validate_startup_config() -> None:
    routing_cfg = load_routing_config()
    pricing_cfg = load_pricing_config()
    errors: list[str] = []

    priced_models = (pricing_cfg or {}).get("models", {}) or {}

    classifier_cfg = (routing_cfg or {}).get("classifier", {}) or {}
    _check_provider_and_model(
        errors, "classifier", classifier_cfg.get("provider"), classifier_cfg.get("model"), priced_models
    )
    if not isinstance(classifier_cfg.get("max_output_tokens"), int) or classifier_cfg.get("max_output_tokens", 0) <= 0:
        errors.append("classifier.max_output_tokens must be a positive integer")

    tiers_cfg = (routing_cfg or {}).get("tiers", {}) or {}
    for tier in REQUIRED_TIERS:
        tier_cfg = tiers_cfg.get(tier)
        if tier_cfg is None:
            errors.append(f"tiers.{tier} is missing from routing.yaml")
            continue
        _check_provider_and_model(errors, f"tiers.{tier}", tier_cfg.get("provider"), tier_cfg.get("model"), priced_models)
        if not isinstance(tier_cfg.get("max_output_tokens"), int) or tier_cfg.get("max_output_tokens", 0) <= 0:
            errors.append(f"tiers.{tier}.max_output_tokens must be a positive integer")

    thresholds = (routing_cfg or {}).get("confidence_thresholds", {}) or {}
    low, high = thresholds.get("low"), thresholds.get("high")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        errors.append("confidence_thresholds.low/high must both be numbers")
    elif not (0.0 <= low < high <= 1.0):
        errors.append(
            f"confidence_thresholds must satisfy 0 <= low < high <= 1 (got low={low}, high={high})"
        )

    learning = (routing_cfg or {}).get("learning", {}) or {}
    min_sample_size = learning.get("min_sample_size")
    if not isinstance(min_sample_size, int) or min_sample_size <= 0:
        errors.append("learning.min_sample_size must be a positive integer")
    min_confidence = learning.get("min_confidence")
    if not isinstance(min_confidence, (int, float)) or not (0.0 <= min_confidence <= 1.0):
        errors.append("learning.min_confidence must be a number between 0 and 1")

    if not routing_cfg.get("policy_version"):
        errors.append("policy_version is missing from routing.yaml")

    if errors:
        raise StartupConfigError(
            "Invalid routing/pricing configuration (" + str(len(errors)) + " issue(s)):\n- "
            + "\n- ".join(errors)
        )


def _check_provider_and_model(
    errors: list[str], label: str, provider: str | None, model: str | None, priced_models: dict
) -> None:
    if provider not in VALID_PROVIDERS:
        errors.append(f"{label}.provider '{provider}' is not one of {sorted(VALID_PROVIDERS)}")
    if not model:
        errors.append(f"{label}.model is missing")
    elif model not in priced_models:
        errors.append(f"{label}.model '{model}' has no pricing.yaml entry — cost estimation will fail at request time")
