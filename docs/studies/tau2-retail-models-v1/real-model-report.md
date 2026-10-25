# GateBench — retail behavior without confirmation
<!-- GATEBENCH_RETAIL_CONFIRMATION_NOTICE -->

> **Confirmation boundary.** No fresh user reply is available in this fixed-input protocol. Fully policy-compliant database-write completion is therefore impossible: the policy requires explicit confirmation after action details. Native ENV/DB and bounded-layer acceptance are diagnostics, not a ranking of tool-use ability or full-policy completion. A concrete confirmation request can be appropriate despite an incomplete database outcome.
> [Predeclared behavior protocol](https://github.com/Udayyyyy/gatebench/blob/9d2a6b45545624c2d21d885c41faed1e90d92bf0/docs/retail-confirmation-protocol.md) · [Frozen protocol source](confirmation-protocol.source.txt) · [Behavior annotations (JSON)](review.json) · [Behavior review](review.html) · [Review source (Markdown)](review.md)

<!-- END_GATEBENCH_RETAIL_CONFIRMATION_NOTICE -->


Observed tool-use trials, kept separate from scripted verifier controls.

**Recorded matrix:** 36 trials; 2 model packages; 6 task clusters; 3 repetitions per model/task.
**Domains:** tau2-retail.
The listed Qwen3.5 packages share a model family and Q4_K_M quantization. This is a size comparison on the frozen tasks, not a broad model leaderboard. The study uses text inputs only.

## Acceptance and repeated success

Acceptance is the grader's decision over all scheduled trials, including budget/error terminations. Hardened acceptance requires completed, policy-compliant evidence. The hardened implementation is not independent ground truth. In a public-benchmark domain, native means the unchanged upstream environment/database component only; natural-language assertions and confirmation checks are not assessed by this adapter.

| Model | Grader | Accepted | 95% interval (%) | pass^1 | pass^2 | pass^3 |
|---|---|---:|---:|---:|---:|---:|
| qwen3.5:2b-q4_K_M | hardened | 0/18 (0.0%) | [0.0, 0.0] | 0.0% | 0.0% | 0.0% |
| qwen3.5:2b-q4_K_M | native | 0/18 (0.0%) | [0.0, 0.0] | 0.0% | 0.0% | 0.0% |
| qwen3.5:4b-q4_K_M | hardened | 0/18 (0.0%) | [0.0, 0.0] | 0.0% | 0.0% | 0.0% |
| qwen3.5:4b-q4_K_M | native | 0/18 (0.0%) | [0.0, 0.0] | 0.0% | 0.0% | 0.0% |

`pass^k = mean_task(comb(successes, k) / comb(repetitions, k))`. With three repetitions, pass^3 requires all three to succeed. It is not any-of-three success.

## Runtime and reporting coverage

| Model | Stop reasons | Mean / median / p95 seconds | Prompt tokens (reported trials) | Completion tokens (reported trials) |
|---|---|---:|---:|---:|
| qwen3.5:2b-q4_K_M | budget: 10, completed: 8 | 36.83 / 42.00 / 67.40 | 610801 (18/18) | 16725 (18/18) |
| qwen3.5:4b-q4_K_M | budget: 7, completed: 11 | 86.69 / 92.93 / 128.48 | 814535 (18/18) | 19651 (18/18) |

## Paired model differences

Difference is model B minus model A in acceptance percentage points. Every model uses the same bootstrap task draws.

| Model A | Model B | Grader | Difference (pp) | 95% interval (pp) |
|---|---|---|---:|---:|
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | hardened | +0.0 | [+0.0, +0.0] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | native | +0.0 | [+0.0, +0.0] |

## Workflow and domain slices

Point estimates only; all repetitions remain in their task cluster.

| Model | Dimension | Slice | Grader | Accepted |
|---|---|---|---|---:|
| qwen3.5:2b-q4_K_M | domain | tau2-retail | hardened | 0/18 (0.0%) |
| qwen3.5:2b-q4_K_M | domain | tau2-retail | native | 0/18 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | hardened | 0/6 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | native | 0/6 (0.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | hardened | 0/6 (0.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | native | 0/6 (0.0%) |
| qwen3.5:2b-q4_K_M | family | return | hardened | 0/6 (0.0%) |
| qwen3.5:2b-q4_K_M | family | return | native | 0/6 (0.0%) |
| qwen3.5:4b-q4_K_M | domain | tau2-retail | hardened | 0/18 (0.0%) |
| qwen3.5:4b-q4_K_M | domain | tau2-retail | native | 0/18 (0.0%) |
| qwen3.5:4b-q4_K_M | family | cancel | hardened | 0/6 (0.0%) |
| qwen3.5:4b-q4_K_M | family | cancel | native | 0/6 (0.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | hardened | 0/6 (0.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | native | 0/6 (0.0%) |
| qwen3.5:4b-q4_K_M | family | return | hardened | 0/6 (0.0%) |
| qwen3.5:4b-q4_K_M | family | return | native | 0/6 (0.0%) |

## native acceptance disagreements

All 0 trials accepted by native and rejected by hardened are listed below. These are disagreements pending trace adjudication, not measured false-positive rates.

| Trial | Model | Domain / workflow | Hardened reason | Evidence |
|---|---|---|---|---|

## Method and limits

- Bootstrap: 2000 paired task-cluster draws, seed 17; all repetitions retained. Intervals describe sensitivity to this fixed task mix.
- Missing trials are rejected by the analyzer. Token counts that were not reported remain missing.
- Model digests, generation settings, task/policy fingerprints, and raw responses belong in the accompanying run manifest and trial artifacts.
- Model outputs can vary across runtime builds and hardware even when decoding seeds match.
- Public benchmark domains retain their own protocol and upstream revision. A fixed-user subset is not an official full-benchmark leaderboard run.
- A disagreement alone establishes neither a verifier error nor intentional reward hacking. Use separate evidence-backed annotations for adjudication.

[Download the trial summary](trial-summary.tsv). Open `real-model-report.html` for the searchable complete trial table.
