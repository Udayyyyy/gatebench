# Real-model study protocol

The primary study asks whether grader choices change the measured completion
rate of actual small-model tool-use trials. It is separate from the scripted
verifier corpus and separately developed attack controls.

The checked-in plan is [configs/real-model-study.json](../configs/real-model-study.json).
The runner must copy and hash that plan, generated task states, policy, runtime
metadata, and model digests before collecting primary outcomes. Model tags are
mutable; the recorded full digest is the identity of the evaluated artifact.

## Sampling and generation

The fixed matrix contains 12 GateBench tasks: eval seeds 10020–10023 for each of
refund, cancellation, and exchange. Two Qwen3.5 model sizes use explicit Q4_K_M
tags, with three repetitions per task: decoding seeds 17, 29, and 43. This makes
72 trials. It is a same-family size comparison, not evidence about diverse model
families or frontier systems. Inputs are text-only despite the model packages'
multimodal capability.

Every trial uses the same unmodified public policy and tool interface. Generation
uses temperature 0.2, thinking disabled, 8,192 context tokens, at most 512 generated
tokens per response, top-k 20, top-p 0.95, presence penalty zero, and repeat penalty
one. Budgets are 24 tool calls and 16 assistant turns. Socket timeout is 60 seconds;
the elapsed-time budget is 180 seconds, checked between calls and after reading
a response. A socket inactivity timeout is not a hard hostile-server deadline.

Pilot trials use seed 10000 and are excluded from primary results. Any change
motivated by a pilot must be made before freezing the primary plan. Do not change
the plan after seeing primary outcomes, select successful repeats, silently retry
failed trials, or omit incomplete rows. A rerun is a separate identified attempt,
and its reason belongs in the experiment record.

Inference runs sequentially on one model at a time. Record warm-up separately and
retain model load duration where available. Runtime defaults must not silently
override the recorded generation settings. Fixed seeds improve traceability but
do not guarantee bitwise inference reproducibility across runtime builds or GPUs.

## Evidence and failure accounting

Retain each raw request and response, tool result, final snapshot, verifier reason,
stop reason, elapsed time, and prompt/completion token count. Also retain transport
errors, malformed responses, and truncated generations. A complete business outcome
does not turn a budget or transport termination into a completed trial. An invalid
tool call rejected atomically is distinct from a successful policy violation.

Malformed tool parsing is a harness/model-interface failure. Some runtimes may
drop malformed generated calls while returning an otherwise ordinary response.
Save runtime diagnostics where available and inspect that failure mode in pilots;
do not present an empty parsed call list as proof that no call was attempted.

## Metrics

Each grader receives exactly the same captured episode. Report accepted trials
over all scheduled trials, exact numerators/denominators, workflow slices,
termination counts, token coverage, and latency. Missing token counts are `null`
with a reporting-coverage count, rather than zero tokens.

The hardened verifier is a specification implementation, not independent truth.
Consequently model-trace comparisons are **grader disagreements**, not false
acceptance/rejection estimates. For each comparison report both directions:
grader accepts/hardened rejects and hardened accepts/grader rejects. Explain every
observed acceptance gap using reviewed concrete traces, or disclose the review
sample and any unreviewed records.

For task i with n repetitions and c successful trials under a given grader:

`pass^k = mean_i(comb(c_i, k) / comb(n, k))`

With three repetitions, `pass^3` is the fraction of tasks that pass all three.
`pass^1` is ordinary mean success; `pass^2` measures success on two draws without
replacement. Any-of-three success is a different quantity and is not reported as
`pass^3`. The repeated-success question follows the reliability motivation in
[τ-bench](https://arxiv.org/abs/2406.12045).

Uncertainty uses 2,000 percentile bootstrap draws, seed 17, resampling whole
`(domain, task_id)` clusters with all repetitions retained. Every grader and
model uses the same sampled task IDs. Paired differences are model B minus model
A for lexicographically sorted model names. Small fixed task sets give limited
precision and do not estimate deployment-wide failure rates. The bootstrap
captures sensitivity to this task mix; three decoding seeds do not comprehensively
sample each model's stochastic behavior. Family/domain slices report point
estimates only, to avoid presenting tiny subgroup intervals as strong evidence.

Public-benchmark trials must retain their own domain, task IDs, upstream revision,
native evaluator, selection rule, and any departures from the upstream protocol.
Do not merge a modified fixed-user study into an official benchmark leaderboard.
For the 36 native retail trials, the separate
[confirmation-boundary rubric](retail-confirmation-protocol.md) was committed
before collection in `9d2a6b4`. It defines behavior annotations under the absence
of a fresh customer reply; native/bounded-layer acceptance remains diagnostic.

## Annotation record

For any reviewed model-trace disagreement, store an annotation separate from
the raw trace. The schema is:

```json
{
  "trial_id": "stable trial identifier",
  "reviewer": "actual person or model-assisted review process",
  "outcome": "valid | invalid | ambiguous | harness_failure",
  "policy_clauses": ["policy version and clause"],
  "event_indices": [2],
  "rationale": "The concrete state change and why it satisfies or violates the clause.",
  "evidence_digest": "SHA-256 of the reviewed raw episode",
  "independence": "Whether the reviewer saw grader outputs and existing labels."
}
```

An adjudicator who saw grader reasons is not blind. Model-assisted independent
attack generation is not external human adjudication. Document actual roles and
information access rather than implying a stronger independent review process.

## Analysis interface

`summarize_trials(rows, expected_models=None, expected_task_ids=None, repeats=3,
bootstrap_samples=2000, seed=17)` requires a complete paired matrix. Each row has
`trial_id`, `task_id`, `family`, `model`, zero-based `repeat`, `decode_seed`,
`stop_reason`, `graders` (boolean mapping including `hardened`),
`elapsed_seconds`, `prompt_tokens`, and `completion_tokens`. Optional `domain`
defaults to `gatebench`. Repetition indices must use distinct, consistent seeds.

Duplicate trials, inconsistent grader sets, model/task coverage gaps, and missing
repetitions raise errors. Supplying expected model and task lists also detects an
entirely absent planned model or task. A subset without those lists can only be
validated against its observed matrix; callers must pass the frozen plan.

The output includes `corpus`, `bootstrap`, `models`, and
`paired_model_differences`. Per-model results include `graders`, `consistency`,
`disagreements_vs_hardened`, `stop_reasons`, `latency_seconds`, `tokens`, and
`family`/`domain` slices. Rate intervals are two-element fractions or `null`
when bootstrap is disabled. Consistency at k larger than the repetition count
is undefined, represented as `null`.

Model package details were checked against the official
[2B Q4 tag](https://ollama.com/library/qwen3.5:2b-q4_K_M),
[4B Q4 tag](https://ollama.com/library/qwen3.5:4b-q4_K_M), and
[Ollama model metadata API](https://docs.ollama.com/api/tags).

## Offline review and archival use

`gatebench verify-study DIRECTORY` validates captured raw evidence without a
model service. It replays the full scheduled matrix and recomputes grades. Saved
rows and summaries are compared when present; publication additionally requires
both aggregates and both report formats. `scripts/package_study.py` checks those
requirements, copies the evidence, and writes a manifest covering raw files,
rendered reports, warm-ups and any supplied review annotations.

`gatebench check-manifest DIRECTORY` checks the listed bytes against that
publication manifest. Neither command establishes artifact authenticity. Report
prose and reviewer conclusions are not independently adjudicated by the checker.
If collector/evaluator source changes in a later release, use the recorded
collection revision or the matching release source to inspect its historical
study; the source mismatch is intentionally an error.
