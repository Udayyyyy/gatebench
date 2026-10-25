# Contributing

Start with `uv sync --locked --extra dev`, then run `make check`.

A useful verifier change includes a minimal executable counterexample, the
policy clause it violates, and a valid neighboring plan that must still pass.
Do not change expected labels merely to make tests pass. Keep impossible trace
edits in the evidence-integrity suite, not the executable corpus.

After changing semantics, regenerate the checked-in audit with `make reproduce`
and inspect both counts and failure reasons. Document any policy change before
using its new results as comparable to the previous version.
