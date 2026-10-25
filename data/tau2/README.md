# Pinned public retail integration

This directory records the deterministic selection ledger and measured native
control audit for the integration described in
[docs/public-benchmark.md](../../docs/public-benchmark.md).

The original source/data files are in the hash-verified compressed bundle
`src/gatebench/integrations/tau2_sources.tar.gz`, with original upstream paths and
MIT attribution. No upstream tools, tasks, database records, or evaluator logic
are modified. `selection.json` accounts for all 114 original task specifications.

`audit.json` contains the 60 executed control outcomes and independently specified
rationales. `episodes.jsonl.gz` contains their complete normalized tool evidence.
Reproduce with `uv run python scripts/run_tau_audit.py --output runs/tau-retail`.

Only the native ENV/DB reward component is evaluated. No official benchmark
leaderboard or whole-policy compliance result is claimed.
