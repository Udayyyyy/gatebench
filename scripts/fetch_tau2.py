"""Fetch or unpack the hash-pinned, MIT-licensed τ-bench source slice."""

from __future__ import annotations

import argparse
from pathlib import Path

from gatebench.integrations.tau_retail import prepare_sources

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cache", type=Path)
parser.add_argument(
    "--network",
    action="store_true",
    help="fetch pinned original files instead of the offline bundle",
)
args = parser.parse_args()
print(prepare_sources(args.cache, fetch=args.network))
