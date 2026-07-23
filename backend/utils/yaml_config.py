"""Loaders for the config-driven routing and pricing YAML files.

Routing policy and pricing are business rules, not code — they change when
a provider updates prices or we want to try a different routing tier, and
neither should require a Python deploy. Both loaders are cached with
`lru_cache` since the files don't change while the process is running.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _load_yaml(filename: str) -> dict[str, Any]:
    path = CONFIG_DIR / filename
    with path.open("r") as f:
        return yaml.safe_load(f)


@lru_cache
def load_routing_config() -> dict[str, Any]:
    """Load routing.yaml: classifier settings, confidence thresholds, tier->model map."""
    return _load_yaml("routing.yaml")


@lru_cache
def load_pricing_config() -> dict[str, Any]:
    """Load pricing.yaml: per-model input/output token pricing."""
    return _load_yaml("pricing.yaml")
