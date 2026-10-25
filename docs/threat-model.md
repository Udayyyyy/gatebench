# Trust boundary

The evaluated model receives a task prompt, tool schemas, and results returned
by the runner. It chooses tool calls and its final text. The runner owns the
SQLite connection, captures events immediately, and evaluates against its own
task specification. There is no shell/file execution tool exposed to the model.

The verifier checks unsafe successful actions, incomplete goals, collateral
effects, evidence inconsistency, and invalid run termination. A failed tool call
is not itself a policy violation. The environment allows structurally valid but
policy-forbidden actions so the verifier can detect them.

Local Python integrations are trusted application code. Accessing the process,
monkey-patching modules, modifying the task specification, compromising the
runner, or reading its memory is outside this boundary. This is not an OS
sandbox, an authenticated event service, or a production authorization system.

State hashes are content identifiers. A manifest lets a consumer compare files
to an already trusted reference. Neither is a signature or proof of origin.
Offline replay rejects inconsistent artifacts; a coherent record fabricated
from scratch can still replay. Trusting a task file supplied by an adversary
would let the adversary redefine the task. Supply the trusted task separately.

The artifact-corruption suite and the executable workflow suite answer separate
questions and are reported separately. No claim of comprehensive adversarial
coverage, formal verification, or reward-hacking immunity is made.
