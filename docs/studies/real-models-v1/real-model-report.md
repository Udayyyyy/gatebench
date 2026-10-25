# GateBench — real-model study

Observed tool-use trials, kept separate from scripted verifier controls.

**Recorded matrix:** 72 trials; 2 model packages; 12 task clusters; 3 repetitions per model/task.
**Domains:** gatebench.
The listed Qwen3.5 packages share a model family and Q4_K_M quantization. This is a size comparison on the frozen tasks, not a broad model leaderboard. The study uses text inputs only.

## Acceptance and repeated success

Acceptance is the grader's decision over all scheduled trials, including budget/error terminations. Hardened acceptance requires completed, policy-compliant evidence. The hardened implementation is not independent ground truth. In a public-benchmark domain, native means the unchanged upstream environment/database component only; natural-language assertions and confirmation checks are not assessed by this adapter.

| Model | Grader | Accepted | 95% interval (%) | pass^1 | pass^2 | pass^3 |
|---|---|---:|---:|---:|---:|---:|
| qwen3.5:2b-q4_K_M | exact_trace | 0/36 (0.0%) | [0.0, 0.0] | 0.0% | 0.0% | 0.0% |
| qwen3.5:2b-q4_K_M | final_state | 24/36 (66.7%) | [41.7, 91.7] | 66.7% | 66.7% | 66.7% |
| qwen3.5:2b-q4_K_M | goal | 24/36 (66.7%) | [41.7, 91.7] | 66.7% | 66.7% | 66.7% |
| qwen3.5:2b-q4_K_M | hardened | 22/36 (61.1%) | [36.1, 83.3] | 61.1% | 55.6% | 50.0% |
| qwen3.5:2b-q4_K_M | no_frame | 22/36 (61.1%) | [36.1, 83.3] | 61.1% | 55.6% | 50.0% |
| qwen3.5:2b-q4_K_M | no_history | 24/36 (66.7%) | [41.7, 91.7] | 66.7% | 66.7% | 66.7% |
| qwen3.5:2b-q4_K_M | no_replay | 22/36 (61.1%) | [36.1, 83.3] | 61.1% | 55.6% | 50.0% |
| qwen3.5:2b-q4_K_M | transcript | 36/36 (100.0%) | [100.0, 100.0] | 100.0% | 100.0% | 100.0% |
| qwen3.5:4b-q4_K_M | exact_trace | 0/36 (0.0%) | [0.0, 0.0] | 0.0% | 0.0% | 0.0% |
| qwen3.5:4b-q4_K_M | final_state | 34/36 (94.4%) | [86.1, 100.0] | 94.4% | 88.9% | 83.3% |
| qwen3.5:4b-q4_K_M | goal | 34/36 (94.4%) | [86.1, 100.0] | 94.4% | 88.9% | 83.3% |
| qwen3.5:4b-q4_K_M | hardened | 34/36 (94.4%) | [86.1, 100.0] | 94.4% | 88.9% | 83.3% |
| qwen3.5:4b-q4_K_M | no_frame | 34/36 (94.4%) | [86.1, 100.0] | 94.4% | 88.9% | 83.3% |
| qwen3.5:4b-q4_K_M | no_history | 34/36 (94.4%) | [86.1, 100.0] | 94.4% | 88.9% | 83.3% |
| qwen3.5:4b-q4_K_M | no_replay | 34/36 (94.4%) | [86.1, 100.0] | 94.4% | 88.9% | 83.3% |
| qwen3.5:4b-q4_K_M | transcript | 28/36 (77.8%) | [66.7, 88.9] | 77.8% | 58.3% | 41.7% |

`pass^k = mean_task(comb(successes, k) / comb(repetitions, k))`. With three repetitions, pass^3 requires all three to succeed. It is not any-of-three success.

## Runtime and reporting coverage

| Model | Stop reasons | Mean / median / p95 seconds | Prompt tokens (reported trials) | Completion tokens (reported trials) |
|---|---|---:|---:|---:|
| qwen3.5:2b-q4_K_M | completed: 36 | 11.55 / 11.26 / 17.16 | 421159 (36/36) | 17277 (36/36) |
| qwen3.5:4b-q4_K_M | completed: 36 | 41.74 / 40.36 / 52.65 | 433849 (36/36) | 24914 (36/36) |

## Paired model differences

Difference is model B minus model A in acceptance percentage points. Every model uses the same bootstrap task draws.

| Model A | Model B | Grader | Difference (pp) | 95% interval (pp) |
|---|---|---|---:|---:|
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | exact_trace | +0.0 | [+0.0, +0.0] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | final_state | +27.8 | [+5.6, +50.0] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | goal | +27.8 | [+5.6, +50.0] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | hardened | +33.3 | [+13.9, +55.6] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | no_frame | +33.3 | [+13.9, +55.6] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | no_history | +27.8 | [+5.6, +50.0] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | no_replay | +33.3 | [+13.9, +55.6] |
| qwen3.5:2b-q4_K_M | qwen3.5:4b-q4_K_M | transcript | -22.2 | [-33.3, -11.1] |

## Workflow and domain slices

Point estimates only; all repetitions remain in their task cluster.

| Model | Dimension | Slice | Grader | Accepted |
|---|---|---|---|---:|
| qwen3.5:2b-q4_K_M | domain | gatebench | exact_trace | 0/36 (0.0%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | final_state | 24/36 (66.7%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | goal | 24/36 (66.7%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | hardened | 22/36 (61.1%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | no_frame | 22/36 (61.1%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | no_history | 24/36 (66.7%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | no_replay | 22/36 (61.1%) |
| qwen3.5:2b-q4_K_M | domain | gatebench | transcript | 36/36 (100.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | exact_trace | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | final_state | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | goal | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | hardened | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | no_frame | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | no_history | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | no_replay | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | cancel | transcript | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | exact_trace | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | final_state | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | goal | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | hardened | 10/12 (83.3%) |
| qwen3.5:2b-q4_K_M | family | exchange | no_frame | 10/12 (83.3%) |
| qwen3.5:2b-q4_K_M | family | exchange | no_history | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | exchange | no_replay | 10/12 (83.3%) |
| qwen3.5:2b-q4_K_M | family | exchange | transcript | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | exact_trace | 0/12 (0.0%) |
| qwen3.5:2b-q4_K_M | family | refund | final_state | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | goal | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | hardened | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | no_frame | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | no_history | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | no_replay | 12/12 (100.0%) |
| qwen3.5:2b-q4_K_M | family | refund | transcript | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | exact_trace | 0/36 (0.0%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | final_state | 34/36 (94.4%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | goal | 34/36 (94.4%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | hardened | 34/36 (94.4%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | no_frame | 34/36 (94.4%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | no_history | 34/36 (94.4%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | no_replay | 34/36 (94.4%) |
| qwen3.5:4b-q4_K_M | domain | gatebench | transcript | 28/36 (77.8%) |
| qwen3.5:4b-q4_K_M | family | cancel | exact_trace | 0/12 (0.0%) |
| qwen3.5:4b-q4_K_M | family | cancel | final_state | 10/12 (83.3%) |
| qwen3.5:4b-q4_K_M | family | cancel | goal | 10/12 (83.3%) |
| qwen3.5:4b-q4_K_M | family | cancel | hardened | 10/12 (83.3%) |
| qwen3.5:4b-q4_K_M | family | cancel | no_frame | 10/12 (83.3%) |
| qwen3.5:4b-q4_K_M | family | cancel | no_history | 10/12 (83.3%) |
| qwen3.5:4b-q4_K_M | family | cancel | no_replay | 10/12 (83.3%) |
| qwen3.5:4b-q4_K_M | family | cancel | transcript | 8/12 (66.7%) |
| qwen3.5:4b-q4_K_M | family | exchange | exact_trace | 0/12 (0.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | final_state | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | goal | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | hardened | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | no_frame | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | no_history | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | no_replay | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | exchange | transcript | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | exact_trace | 0/12 (0.0%) |
| qwen3.5:4b-q4_K_M | family | refund | final_state | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | goal | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | hardened | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | no_frame | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | no_history | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | no_replay | 12/12 (100.0%) |
| qwen3.5:4b-q4_K_M | family | refund | transcript | 8/12 (66.7%) |

## final_state acceptance disagreements

All 2 trials accepted by final_state and rejected by hardened are listed below. These are disagreements pending trace adjudication, not measured false-positive rates.

| Trial | Model | Domain / workflow | Hardened reason | Evidence |
|---|---|---|---|---|
| m0-eval-exchange-10020-r2 | qwen3.5:2b-q4_K_M | gatebench / exchange | history.event[5].replacement: invalid target, inspection, or reservation | [raw trial](trials/m0-eval-exchange-10020-r2.json.gz) |
| m0-eval-exchange-10023-r1 | qwen3.5:2b-q4_K_M | gatebench / exchange | history.event[3].replacement: invalid target, inspection, or reservation | [raw trial](trials/m0-eval-exchange-10023-r1.json.gz) |

## Method and limits

- Bootstrap: 2000 paired task-cluster draws, seed 17; all repetitions retained. Intervals describe sensitivity to this fixed task mix.
- Missing trials are rejected by the analyzer. Token counts that were not reported remain missing.
- Model digests, generation settings, task/policy fingerprints, and raw responses belong in the accompanying run manifest and trial artifacts.
- Model outputs can vary across runtime builds and hardware even when decoding seeds match.
- Public benchmark domains retain their own protocol and upstream revision. A fixed-user subset is not an official full-benchmark leaderboard run.
- A disagreement alone establishes neither a verifier error nor intentional reward hacking. Use separate evidence-backed annotations for adjudication.

[Download the trial summary](trial-summary.tsv). Open `real-model-report.html` for the searchable complete trial table.
