"""Print the reproducible multi-router benchmark as JSON."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.routing_evaluation import benchmark


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2))
