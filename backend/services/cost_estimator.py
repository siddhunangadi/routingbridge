"""Cost estimation from pricing.yaml.

Pulled out as a standalone function (not a class) because it's stateless
and used from two places — the classifier's own cost, and the final
model's cost. A shared function beats duplicating the same three lines
of math twice.
"""

from backend.utils.yaml_config import load_pricing_config


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = load_pricing_config()["models"][model]
    input_cost = (input_tokens / 1_000_000) * pricing["input_per_million"]
    output_cost = (output_tokens / 1_000_000) * pricing["output_per_million"]
    return round(input_cost + output_cost, 8)
