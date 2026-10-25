"""Run the actual pinned retail tools and native environment evaluator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gatebench.integrations.tau_retail import run_audit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path("runs/tau-retail"))
parser.add_argument("--per-family", type=int, default=2)
args = parser.parse_args()
result = run_audit(args.output, per_family=args.per_family)
print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
