# Assessment of independently authored frozen controls

The hardened verifier rejected all **180 invalid controls** and accepted all
**152 valid alternatives** in the frozen set. No bypass or valid-plan rejection
was found, and these observations justify no verifier change. This is a finite
model-assisted control study, not evidence that the verifier is generally sound.

The set was committed before grading at `3e70108`. Its exact actions and labels
have SHA-256
`df3feb4bf3aefe41a818c540db278e18a67b01121ec80068f794dede5aba5315`.
The [blind-design process](redteam-process.md) documents public inputs, excluded
ambiguities, and the authorship boundary. There are 23 distinct negative mutation
templates and 16 positive stress templates across 12 tasks. The same templates
were used during development, so these are held-out parameters rather than
held-out attack types. No labels were inferred from the hardened verifier.

| Grader | Invalid accepted | Valid rejected |
|---|---:|---:|
| Transcript | 0 / 180 | 152 / 152 |
| Requested outcome | 136 / 180 | 0 / 152 |
| Full final state | 88 / 180 | 0 / 152 |
| Exact canonical trace | 0 / 180 | 152 / 152 |
| Hardened | 0 / 180 | 0 / 152 |
| Without history | 88 / 180 | 0 / 152 |
| Without frame | 12 / 180 | 0 / 152 |
| Without replay | 0 / 180 | 0 / 152 |

The transcript result has a fixed-input confound: the committed executor's
answer is “Frozen independently labeled control.” It contains no completion
claim, so that grader rejects every trajectory solely for its wording. The
frozen executor was preserved instead of rewriting its answers after seeing
this result. Treat this row as a wording-sensitivity diagnostic, not a useful
comparison of policy-checking strength.

The exact-trace grader also rejects every valid alternative because each differs
from the published canonical action list. The outcome and final-state graders
accept successful history violations such as repaired collateral notes,
premature closures, and late inspection. Removing the frame check admits the
12 persistent target-note changes. All episodes come from the real backend;
this set has no journal corruption, so the replay ablation supplies no evidence
about corruption resistance.

All **628 grader/trajectory disagreements** are retained in the evidence. Each
has its frozen rationale, successful negative-event witness or positive
obligation check, observed verdict, rejection reasons, and a post-freeze
public-policy label review. That review supports the frozen labels and proposes
no relabeling. It was performed by the model-assisted designer using the public
contract; there was no external human adjudication. An intentionally incorrect
grader in the regression tests demonstrates that hardened disagreements are
reported rather than suppressed.

## Original implementation and bounded timing

The current verifier, grader dispatch, replay model, backend, models, task policy,
tool schema and canonical baseline sources are byte-identical to revision
`e24711d` (the original v0.1 implementation). The counts therefore also describe
that implementation by source equivalence. A historical checkout was not
executed separately, and no patch was made to make the freeze pass.

Timing measures `grade()` on fixed, already executed episodes. Each of the 332
episodes has one unmeasured warm-up and five measured calls per grader, giving
1,660 observations per grader. Backend creation, tool execution, label checking,
and serialization are excluded. Calls are interleaved by episode and grader,
without randomized ordering. These measurements bound a small local Python
microbenchmark; they do not estimate deployment latency or large-trace scaling.

| Grader | Median μs | p95 μs |
|---|---:|---:|
| Transcript | 0.46 | 0.71 |
| Requested outcome | 12.71 | 14.25 |
| Full final state | 69.83 | 84.46 |
| Exact canonical trace | 2.54 | 2.92 |
| Hardened | 844.71 | 1,158.48 |
| Without history | 585.77 | 843.40 |
| Without frame | 837.38 | 1,145.42 |
| Without replay | 309.17 | 446.04 |

The [machine-readable summary](studies/redteam-v1/redteam-v1-assessment-summary.json)
contains exact confusion counts, timing distributions, source comparisons and
machine metadata. The [complete assessment archive](studies/redteam-v1/redteam-v1-assessment.tar.gz)
contains literal frozen cases, executed episodes, every disagreement, raw timing
samples, generated report, and an internal file-hash manifest. The
[artifact manifest](studies/redteam-v1/redteam-v1-assessment-manifest.json) commits the
summary and archive bytes.

To reproduce the assessment after installing the package, call
`audit_redteam(output_path)` from `gatebench.redteam_audit`. It rejects a changed
freeze and refuses a nonempty output directory. Runtime timings will vary;
the exact action/label commitment and confusion counts are the reproducible
experimental inputs and outcomes. Targeted structural, label-witness,
assessment, corruption, and disagreement-preservation checks all passed
(18 tests), along with lint and formatting checks.
