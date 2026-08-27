"""Machine-readable routing release gate; exits nonzero when blocked."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.routing_evaluation import benchmark, release_gate, run_regressions
from backend.services.classifier_service import ClassifierService
from backend.utils.config import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--state", default="PRODUCTION", choices=("EXPERIMENTAL", "VALIDATION", "PRODUCTION-CANDIDATE", "PRODUCTION"))
args = parser.parse_args()
try:
    regressions = run_regressions(ClassifierService(Settings(router_mode="local")))
    result = {"benchmark": benchmark(), "regressions": regressions}
    result["release_gate"] = release_gate(result["benchmark"], regressions, target_state=args.state)
except Exception as exc:
    result = {"release_gate": {"allowed": False, "error": str(exc)}}
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["release_gate"]["allowed"] else 1)
