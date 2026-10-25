# Public benchmark integration: τ-bench retail

GateBench executes the **original retail tools and original environment reward
evaluator** from Sierra Research's τ-bench repository, release **v1.0.1**, commit
[`fc0055dc4e0a316c3f83133267fbd6faaa770992`](https://github.com/sierra-research/tau2-bench/tree/fc0055dc4e0a316c3f83133267fbd6faaa770992).
The integration measures a specific boundary: what the native **ENV/DB reward
component** verifies, and what additional action-time evidence establishes.

This is **not a full τ-bench run or leaderboard score**. The official benchmark
uses an interactive user simulator and additional reward components. Our model
protocol supplies a fixed scenario message; our deterministic controls execute
tool plans directly. We do not call the native natural-language assertion judge.

## What is actually upstream

The adapter uses unchanged `RetailDB`, `RetailTools`, `Environment.get_response`,
and `EnvironmentEvaluator.calculate_reward` implementations. The latter replays
the observed tool calls on a fresh native environment, creates a target database
from the upstream expected actions, then compares the databases using the native
hashing procedure. It is not a rewritten approximation of that scorer.

The vendored slice contains 29 original files: the native implementation and its
import closure, original 114 retail tasks, original database, policy, and MIT
license. The compressed source bundle is 335,064 bytes. Every original file and
the bundle has a committed SHA-256 identifier in
[`tau2_manifest.json`](../src/gatebench/integrations/tau2_manifest.json).
Sources are verified before importing them.

The upstream top-level `tau2` facade imports all provider and voice integrations.
GateBench creates package namespaces and imports the selected original modules
directly, avoiding those unrelated clients. It changes no native method or data.
The optional `tau` dependency group contains the upstream modules' required
libraries; the core GateBench environment retains its separate dependency scope.

Current upstream development has moved beyond v1.0.1. This study deliberately
pins the preserved 1.x release; it does not claim coverage of the newer 2.0 task
replacements. The [current upstream README](https://github.com/sierra-research/tau2-bench)
documents the separation of the 1.x and 2.0 evaluation frames.

## Predeclared task selection

Read the 114-task upstream file in its original order. A task is eligible if:

1. It has exactly one native write action, of type cancellation, delivered-item
   return, or delivered-item exchange.
2. It has no initialization-state override and has a structured user scenario.
3. Its scenario does not contain `confirmation` or `do not reveal`, which denote
   interaction-dependent preference changes that a fixed input cannot preserve.

Take the first two eligible tasks per family. Selection inspects specification
structure, never model outcomes or observed grader results. There is no silent
skip after a failed reference run. The full
[114-task selection ledger](../data/tau2/selection.json) records the reason for
every exclusion or quota cutoff.

| Upstream task | Family |
|---|---|
| 0 | exchange |
| 1 | exchange |
| 2 | return |
| 19 | return |
| 38 | cancellation |
| 66 | cancellation |

These are six task specifications, not six independent sampled real-world
workflows. Some reuse the same synthetic customer and order. The sample supports
a bounded integration demonstration, not a general failure-rate estimate.

## Model input and protocol differences

The model receives the original retail policy and the public scenario fields
`reason_for_call`, `known_info`, and `unknown_info`. It receives all 16 native tool
schemas. It never receives `evaluation_criteria`, the expected actions, hidden
item identifiers, target database state, or our verifier's labels.

The scenario fields normally instruct a simulated user; providing them together
changes the interaction protocol and information availability. The prompt states
that no interactive user simulator is present. If a model asks for confirmation,
the runner records that final answer and the incomplete outcome. It never
manufactures a customer saying yes. Such results are fixed-input integration
results, not comparable with official benchmark model scores.

Our policy layer checks only these explicit obligations:

- Resolve the requesting customer's identity before sensitive profile/order
  access or a state-changing write.
- Keep the conversation within one customer and the requested order mutation
  scope, including temporary changes that are later restored.
- Check the order's status before cancellation, return, or exchange.
- Reject failed native calls that nonetheless change state.
- Reproduce all recorded native calls, results, changed records, and final state.

**Unassessed:** interactive confirmation, changing customer preferences,
natural-language assertions, communication quality, one-tool-per-message
behavior, and every policy clause not listed above. Passing our checked subset
does not establish full retail-policy compliance.

## Executable native controls

Each selected task has four positive plans and six negative plans. They run
through native tools, not a copy of GateBench's synthetic support environment.
Labels are specified by each constructor's obligation and rationale.

Positive plans include an outcome witness with explicit status reads, repeated
identification, a failed lookup followed by recovery, and extra status reads.
Negative plans omit or delay identification, omit a status read, disclose a
foreign profile, temporarily modify and restore another customer's address, or
switch identities and switch back. The native target database can be correct
despite those action-time violations.

The native expected-action list is a witness for the **target state**, not a
required complete conversation. For example, task 38's witness tries an email
that does not resolve, recovers via name/ZIP, and omits an explicit order-status
read. We preserve the failed lookup and add the harmless required status read
when constructing our policy-positive witness. The model input and upstream
database remain unchanged.

The committed [structural audit](../data/tau2/audit.json) reports exact control
counts, with complete compressed native episodes alongside it. A high acceptance
rate on deliberately constructed negatives is not their incidence in real agent
runs. Nor does an ENV-only result establish that the **full** τ-bench evaluator,
including its natural-language checks, would accept those trajectories.

## Reproduce

```bash
uv sync --locked --extra dev --extra tau
uv run python scripts/run_tau_audit.py --output runs/tau-retail
uv run pytest tests/test_tau_retail.py
```

The upstream source/data slice is bundled for offline execution. To verify a
fresh copy independently against the pinned GitHub source:

```bash
uv run python scripts/fetch_tau2.py --cache runs/tau-upstream-check --network
```

The native code is MIT licensed; the original
[license notice](../data/tau2/LICENSE.upstream) is preserved. The benchmark's
customer names, contact details, and transactions are public synthetic fixtures,
not GateBench users or production customer records.
