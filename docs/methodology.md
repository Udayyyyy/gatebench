# Experimental protocol

The unit of the experiment is a labeled executable action plan. The subject
under test is the grader. A generated task determines the starting records,
public policy, requested outcome, and customer-supplied proof codes.

## Labels

`corpus.probes` constructs each plan and attaches a verdict and rationale before
the plan is executed. It never calls the hardened verifier to assign a label.
Corpus tests separately inspect the concrete mutation witness: for example, a
successful collateral write or a refund before authentication. Thus an invalid
plan cannot quietly become a rejected no-op while retaining its negative label.

Valid plans include the canonical solution plus permitted alternatives. Negative
plans target specific omitted obligations. The audit fails if its full verifier
disagrees with a label. Disagreement artifacts are retained for investigation;
the audit never relabels a probe to match the verifier.

These are developer-authored labels, not independent external adjudication.
They can share misunderstandings with the policy implementation. Unit tests,
an independent transition model, and counterexample review reduce that risk but
do not eliminate it.

## Splits

The default configuration generates 12 tasks per workflow per split: 36 `dev`
and 36 `eval` cases. `eval` uses different seed IDs, larger order quantities,
different price values, and more distractor orders. It also includes combined
violations reserved from the development probe set. All code and seeds are
public. The split tests parameter and composition changes within known workflow
rules; it does not establish generalization to unseen policies or hidden attacks.

## Graders

| Grader | Information it trusts |
|---|---|
| transcript | Final response contains a completion claim; a weak control |
| goal | Requested final outcome fields |
| final_state | Goal and full frame conditions, no action-time policy or replay |
| exact_trace | Action list equals one canonical example |
| hardened | Goal, frame, action-time policy, independent state replay |
| no_history | Hardened with action-time conditions removed |
| no_frame | Hardened with collateral/final frame conditions removed |
| no_replay | Hardened with independent transition replay removed |

`final_state` and `no_history` are expected to agree on honest tool-captured
trajectories. `no_replay` is expected to agree with `hardened` on the executable
corpus; replay's value is tested separately through evidence corruption and
backend/model conformance tests. Redundant ablations make those expectations
visible instead of inflating a claimed contribution.

## Metrics and uncertainty

False acceptance = accepted negative controls / all negative controls.
False rejection = rejected positive controls / all positive controls. Confusion
counts, denominators, and per-workflow/split results accompany rates. An empty
denominator is undefined, represented as `null` rather than zero.

The bootstrap uses task IDs as clusters, retaining all sibling probes together.
The same sampled task clusters are used for paired comparisons between graders.
Intervals are percentile intervals over 2,000 seeded bootstrap samples. Repeated
seeds often yield identical behavior on fixed mutation templates, so intervals
may collapse. This is not evidence of universal certainty; variation outside
this curated generator is not sampled. Counts of seeds, probe templates, and
workflow rules should be considered together.

No LLM ran in the default structural study. It estimates neither the frequency
of model mistakes nor the prevalence or intent of reward hacking. Real model
trials use separate artifacts and require model identifier, configuration,
budgets, raw responses, and complete captured tool evidence.

## Reproducibility

Every action is replayable from a saved task, and every payload has a SHA-256
identifier. Manifests include the source fingerprint, Git revision if available,
Python version, generator arguments, and exact file hashes. They contain no
timestamps in semantic results. Rerunning with the same code/configuration must
produce byte-identical task files, labels, rows, normalized episodes, summaries,
and rendered reports. The host Python version/Git revision are provenance and
may differ across otherwise equivalent runs.
