# GateBench: when a correct final state is insufficient evidence

**An agent-evaluation engineering case study · October 2026 · v0.2**

A support agent can issue the requested refund and still violate the workflow:
it might authenticate too late, inspect a return after paying it, or modify
another customer's record and restore it. A checker that only compares the
final database cannot recover those facts.

GateBench makes this boundary executable. It couples transactional tools with
semantic goal checks, limits on collateral changes, action-time policy checks,
and a separately implemented replay model. The work asks a bounded question:
**which evidence changes a verifier's decision, and what legitimate behavior
does that verifier accidentally reject?**

The repository includes actual local-model experiments, controls developed
without access to the verifier, and an integration with original public
benchmark tools. Each answers a different question. None establishes a general
agent failure rate or proves the checker sound.

In 72 captured model trials, two exchanges pass final-state checks despite
missing the required return inspection. Full verification catches both. The
separately developed control set also exposes final-state blind spots—88 of
180 invalid plans are accepted—while finding no new full-verifier bypass. The
sections below connect these observations to exact traces, design choices and
the limits of each experiment.

## Four evidence sets

| Evidence | Size | What it establishes |
|---|---:|---|
| Original scripted audit | 1,560 trajectories, 72 tasks | Known counterexamples and legitimate alternatives across eight grading designs |
| Independently developed frozen controls | 332 plans, 12 tasks | Whether separately designed policy witnesses expose a bypass or overrejection |
| Native public-benchmark controls | 60 trajectories, 6 selected tasks | Behavior of the original retail ENV/DB reward component and a bounded policy layer |
| Actual model trials | 72 GateBench + 36 fixed-input retail trials | Observed behavior of two quantized models under the frozen protocols |

The first three sets have constructor-specified labels and executable witnesses.
Native control labels cover only the explicitly assessed subset of obligations.
Actual model traces have grader decisions and review annotations. The full
verifier is not an independent ground-truth labeler, so model comparisons are
reported as disagreements rather than false-positive estimates.

## Why the implementation has separate checks

The synthetic backend stores orders, refunds, cases, inventory reservations and
replacements in SQLite. Every tool action commits or rolls back atomically.
Money uses integer cents. The tools expose database mechanics; successful tool
execution alone does not establish that a business policy was followed.

The verifier checks four obligations:

1. **Goal:** the requested cancellation, refund or exchange actually completed.
2. **Frame:** changes outside that goal stayed within the allowed boundary.
3. **History:** required evidence existed before each consequential write.
4. **Replay:** a separate Python reducer reproduces results and state changes.

The reducer shares types and argument schemas, but does not call SQLite's
transition implementation. Property-based sequences exercise both models,
including atomic failures and retries. Shared schemas remain a common source of
possible mistakes; the implementations are not mathematically independent.

Semantic predicates permit split refunds, harmless extra reads and safe retry
reservations. Requiring one exact canonical trace would reject these valid
solutions. Conversely, a final-state hash loses a temporary privacy or scope
violation once the agent repairs the state.

The implementation boundaries are visible in the
[SQLite tools](../src/gatebench/environment.py),
[semantic verifier](../src/gatebench/verifier.py),
[separate reducer](../src/gatebench/replay.py),
[study collector](../src/gatebench/experiments/runner.py), and
[offline evidence checker](../src/gatebench/experiments/verification.py).

## What the independent attacks found

A separate model-assisted designer received the public policy, schemas, backend
and baseline plan, but no verifier, replay implementation, existing attack
corpus or individual result artifacts. The allowed README exposed prior headline
results and broad examples. It committed literal actions, labels and executable
policy witnesses before assessment, in revision `3e70108`.

The freeze contains 23 negative mutation templates and 16 positive stress
templates instantiated across 12 tasks: 180 invalid plans and 152 valid
alternatives. The same templates had been developed on other seeds. This is
separate authorship with held-out parameters, not a secret or novel-attack
holdout. Two genuinely ambiguous proposals were retained as exclusions rather
than forced into binary labels.

| Checker | Invalid plans accepted | Valid plans rejected |
|---|---:|---:|
| Requested outcome | 136 / 180 | 0 / 152 |
| Full final state | 88 / 180 | 0 / 152 |
| Exact canonical plan | 0 / 180 | 152 / 152 |
| Goal + frame + history + replay | 0 / 180 | 0 / 152 |

No full-verifier bypass was found. No verifier patch was made to make the freeze
pass. The eight relevant core source files remain byte-identical to v0.1 for
this assessment. That is evidence about these controls, not a soundness proof.

The frozen final answer does not contain a completion claim, causing the weak
transcript baseline to reject every plan. Its wording was preserved after
assessment. The [assessment](redteam-assessment.md) reports this confound, all
628 grader/trajectory disagreements, label reviews and raw timing samples.
The authorship separation is model-assisted; there was no external human
adjudicator.

## The public integration uses the original implementation

The adapter pins Sierra Research's retail benchmark at release v1.0.1, commit
[`fc0055dc4e0a316c3f83133267fbd6faaa770992`](https://github.com/sierra-research/tau2-bench/tree/fc0055dc4e0a316c3f83133267fbd6faaa770992).
It verifies and imports 29 unchanged upstream implementation, data and license
files. It runs the original `RetailTools`, native environment responses and
`EnvironmentEvaluator.calculate_reward`; it does not approximate that scorer
with GateBench's synthetic refund environment.

Six tasks were selected by a committed structural rule before model outcomes:
the first two eligible single-write cancellation, return and exchange tasks in
the 114-task upstream order. The full selection ledger includes every excluded
task. Some cases reuse customers and orders, limiting sample diversity.

Across 24 positive and 36 negative native tool plans for the assessed subset, the native
ENV/DB component accepts all 36 invalid histories. GateBench's additional
identity, scope and prior-status-read checks reject those 36 and accept all 24
positives. Examples include reading a foreign profile and changing then
restoring a foreign address: neither needs to alter the target final database.

This does **not** show that the complete upstream benchmark accepts those
plans. The official protocol includes an interactive user and additional
evaluation components. The integration omits natural-language assertions and
does not assess interactive confirmation, preference changes or every policy
clause. Its model protocol supplies fixed scenario fields and records an
unfulfilled confirmation request as an incomplete outcome. These results are
not an official τ-bench score. The [integration specification](public-benchmark.md)
lists the exact deviations and checked obligations.

The omitted customer creates a structural confound for the retail model runs:
the policy requires a fresh explicit yes after update details are described,
but the fixed input provides no reply. Fully policy-compliant write completion
is therefore impossible under this protocol. An incomplete confirmation request
can reflect appropriate restraint rather than tool-use inability; a database
reward of one can coexist with missing confirmation. Retail model numbers
describe that fixed-input condition, not a ranking of task-solving ability.

## Actual model experiments

The frozen study evaluates Qwen3.5 2B and 4B Q4_K_M models sequentially on an
Apple M4 with 16 GiB RAM through a local, cloud-disabled Ollama runtime. Both
models see the public policy and tool schemas. They receive no checker source,
expected actions or database target. No paid model endpoint is required.

Each model receives every task with decoding seeds 17, 29 and 43, temperature
0.2 and thinking disabled. Budgets are 24 tool calls, 16 assistant turns and 512
generated tokens per response. Context is 8,192 tokens for GateBench and 16,384
for native retail. The 180-second elapsed budget is checked between calls and
after responses; a 60-second socket inactivity timeout is not a hard process
deadline. Warm-ups and the two synthetic pilot trials are kept separately.

The 72-trial synthetic study completed its full matrix, with no transport or
budget terminations:

| Model | Final-state accepted | Full checker accepted (95% task-cluster interval) | Tasks passing all three repeats | Median elapsed time |
|---|---:|---:|---:|---:|
| Qwen3.5 2B Q4_K_M | 24 / 36 | 22 / 36, 61.1% [36.1, 83.3] | 6 / 12 | 11.26 s |
| Qwen3.5 4B Q4_K_M | 34 / 36 | 34 / 36, 94.4% [86.1, 100.0] | 10 / 12 | 40.36 s |

![Five verifier decisions and full-check repeat consistency with task-cluster confidence intervals](figures/model-acceptance.svg)

The [plot source](../scripts/plot_model_study.py) and
[rendering metadata](figures/model-acceptance.metadata.json) preserve the input
summary hash, plotting version and exported bytes. The figure uses the recorded
intervals; it does not estimate a separate uncertainty model.

```bash
uv run --no-project --python 3.12.12 --with matplotlib==3.11.2 \
  python scripts/plot_model_study.py
```

The paired full-checker difference is +33.3 percentage points for 4B, with a
[13.9, 55.6] task-cluster interval. Most of that difference comes from case
closure on cancellation tasks, whose specification caveat is discussed below;
it is not evidence of a general 33-point model advantage.

The weak transcript grader reverses the ordering: it accepts 36/36 smaller-model
answers and 28/36 larger-model answers. The exact-plan grader rejects all 72,
including the 56 accepted by the full checker. These are measured differences
between grading designs, not externally adjudicated error rates.

[Inspect the full synthetic study](studies/real-models-v1/real-model-report.html),
including every grader, workflow slice, paired comparison and raw trial.

The separate 36-trial retail study used the confirmation-boundary rubric
[committed before native collection](retail-confirmation-protocol.md). A
model-assisted reviewer classified every trace from packets with native grader
decisions and aggregate outcomes removed:

| Model | Unconfirmed database writes | Concrete approval requests without mutation | Other incomplete outcomes |
|---|---:|---:|---:|
| Qwen3.5 2B Q4_K_M | 0 / 18 | 1 / 18 | 17 / 18 |
| Qwen3.5 4B Q4_K_M | 0 / 18 | 7 / 18 | 11 / 18 |

The other outcomes comprise 17 responses truncated at the 512-token generation
cap and 11 requests for missing information. All budget stops were response
length stops; none exhausted the tool, turn or elapsed budgets. The remaining
19 responses ended normally, and no transport/error stop occurred. A normal
response ending does not mean a retail transaction completed.

Both the original ENV/DB scorer and the bounded policy layer accept 0/18 trials
for each model. These are diagnostic outcomes under a protocol that cannot
complete a fully compliant write, not a general tool-use ranking. The behavior
review provides the more useful distinction between supported approval requests,
missing-information requests and truncated generations. No database mutation
was observed in any of the 36 trials.

The positive behavior label is narrow. One return approval request omitted a
separate product-options question; one exchange approval request contained a
wrong keyboard-availability aside while its proposed thermostat transaction was
supported. Another response misstated the policy for exchanges. These secondary
errors remain in the annotations. The reviewer saw model identity and public
policy/code, had authored the rubric, and consulted the coordinating reviewer
once using only a stripped packet. Initial labels were saved before native
grader outputs were opened. This is grader-blind model-assisted review, not
external human adjudication or full-policy validation.

[Read the complete behavior review](studies/tau2-retail-models-v1/review.html),
its [36 trace annotations](studies/tau2-retail-models-v1/review.json), and the
[native component diagnostics](studies/tau2-retail-models-v1/real-model-report.html).

All scheduled outcomes, including errors and budget stops, stay in the
denominator. No model or prompt was tuned after primary collection began, and
failed trials were not retried to obtain a better result. Each raw request,
response and tool message is retained alongside the full digest of the model,
configuration, source fingerprints, token counters, timing and grade reasons.
Token totals sum the runtime's per-response counters; they are not unique input
tokens or an estimate of paid API cost. Latency is descriptive elapsed time on
this machine, not a controlled performance comparison.

The reports give per-task repeat consistency using
`pass^k = mean(comb(successes, k) / comb(repetitions, k))`, not any-of-three
success. Intervals use 2,000 paired task-cluster bootstrap draws. With only
12 synthetic and six retail cases, these describe sensitivity to the selected
task mix, not deployment-wide uncertainty. Two small models from one family
do not support conclusions about frontier models.

## A captured failure worth inspecting

In `m0-eval-cancel-10020-r0`, the 2B model verified the correct customer, read the
processing order, cancelled it and refunded the exact 74,070 cents. It then
called `close_case` with `resolution="refund"` instead of `"cancel"`, and told
the user it had followed policy. All six tool calls returned success.

The transcript baseline accepted the completion claim. Goal, final-state and
full verification rejected the wrong business resolution. This example shows
why tool success and confident final text do not establish task success. It is
not an example of a gap between final-state and history checks.

All 12 smaller-model cancellation trials made this closure-resolution error;
they still cancelled and refunded the correct full amount in the required order.
The public policy requires a “matching resolution” and the tool enumerates the
resolution values, but the policy does not explicitly spell out an
operation-to-enum mapping. That wording is a specification-clarity limitation,
so the result should not be read as 12 failed monetary cancellations. The frozen
policy and measured outcomes were preserved.

Two smaller-model exchange trials provide the history-check comparison:

| Captured trial | Successful replacement event, zero-based | Missing prerequisite |
|---|---:|---|
| [10020, repeat 2](studies/real-models-v1/trials/m0-eval-exchange-10020-r2.json.gz) | 5 | No `inspect_return` before replacement creation |
| [10023, repeat 1](studies/real-models-v1/trials/m0-eval-exchange-10023-r1.json.gz) | 3 | No `inspect_return` before replacement creation |

Both reach the correct final state. At each replacement event the captured
`inspected_orders` evidence is empty, so full verification rejects them. Their
final prose describes the order lookup as inspection, but `get_order` does not
establish the explicit return-inspection prerequisite. The first trial also
recovers from a rejected guessed reservation identifier; that atomic failure is
not itself counted as a policy violation.

Run the [small trace viewer](../examples/inspect_model_trial.py) to inspect that
captured sequence without a model server:

```bash
uv run python examples/inspect_model_trial.py \
  docs/studies/real-models-v1/trials/m0-eval-exchange-10020-r2.json.gz --final
```

The separate [trace review](studies/real-models-v1/review.json) screens all 72
trial headers and gives detailed annotations for all 16 full-checker rejections,
including both final-state acceptance gaps. All 36 larger-model episodes also
received structured policy/state review; smaller-model positives received only
header-level screening. The reviewer saw grader outputs and authored the
analysis/report code. This is unblinded model-assisted review, not external human
adjudication or an independently sampled ground-truth set. All 14 cancellation
rejections across both models share the closure-resolution limitation.

## Reproduction and engineering tradeoffs

The source has no required runtime dependency for its synthetic environment.
The optional `tau` group installs the unchanged native modules' dependencies;
`uv.lock` fixes the development environment. The published model weights are
identified by full digest rather than a mutable tag. Inference can vary across
hardware and runtime builds even with the same seed.

`gatebench verify-study` works offline. It checks the entire frozen schedule,
configuration and source hashes, raw request/response/tool linkage, replayed
environment results and recomputed grades. It compares saved rows and summaries
when present. Rendered reports, warm-ups and review annotations are outside its
semantic checks; the publication manifest covers their exact bytes through
`gatebench check-manifest`. A coherent
wholesale forgery could still pass: hashes and replay establish consistency
relative to trusted inputs, not the authenticity of the machine or model.

Resume checks reject mismatched runtime, model digest, source, configuration,
task identity or decoding seed. Trials have compressed raw evidence and
SHA-256 sidecars. Missing telemetry remains null, and truncated or late
responses are retained without executing incomplete tool payloads. Regression
tests cover these failure boundaries using explicitly labeled local HTTP
fixtures. They are not counted as model experiments.

The frozen-control timing study measured median full-verifier time of 844.71 μs
and p95 of 1,158.48 μs over 1,660 calls, excluding backend execution and file
handling. Removing replay reduced that median to 309.17 μs. These are bounded,
interleaved local microbenchmarks with no randomized ordering, not production
latency promises. The original corruption suite separately rejects 21/21
inconsistent records; executable model attacks and evidence corruption remain
different experiments.

## Limits and next experiments

The runner, verifier inputs and in-process integrations are trusted code. The
tool boundary is not an operating-system sandbox. Replay cannot protect against
a malicious recorder inventing an entirely coherent history.

The next useful evidence would come from external reviewers labeling model
traces without seeing grader outputs, genuinely new attack families committed
before testing, more model families and tasks, and the complete interactive
public-benchmark protocol. They are future work, not capabilities claimed by
this release. GateBench's contribution here is a reproducible, inspectable
measurement of concrete grading choices and their boundaries.
