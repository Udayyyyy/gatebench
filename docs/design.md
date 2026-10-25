# Design notes

## Why a verifier audit

A large agent framework would add integration code without answering a clear
question. This project instead makes one failure mode inspectable: a workflow
can reach the right final state while violating policy along the way. The
environment is small enough to understand, and rich enough for transactions,
partial amounts, inventory reservations, retries, and collateral effects.

## SQLite plus a separate state model

The backend stores orders, refunds, cases, reservations, replacements, and
evidence in separate SQLite tables. Each tool call commits atomically or rolls
back. Calls with unknown fields, invalid integer types, missing IDs, or failed
preconditions return a recorded error and preserve state. Cents are integers.
Each episode gets an independent connection; no cross-run database is reused.

The replay implementation is a pure Python reducer. It shares public types and
argument schemas, but not the SQLite transition code. It predicts tool outputs
and state changes from the initial state and compares every before/after hash,
sequence number, result, and final snapshot. Property-based tests compare the
two implementations on generated sequences, including failures and retries.
Shared schemas remain a possible common-mode error.

## Three different correctness questions

**Goal:** did the intended refund/cancellation/exchange complete?

**Frame:** did the rest of the state remain within the declared boundary?

**History:** were the necessary facts already true when each write happened?

Replay checks a fourth question: is the supplied record consistent with the
mechanics of the environment? It cannot infer authenticity of the record.

## Alternatives considered

- Exact database hashing against one oracle run would reject legal changes such
  as released retry reservations and split refund records. Semantic predicates
  are more appropriate here; exact hashing remains useful for replay consistency.
- LLM judging would introduce another moving component for obligations that are
  explicit and decidable. No natural-language judge is needed.
- A web service, Redis queue, distributed scheduler, and vector database would
  not strengthen the experiment. The CLI, local evidence files, and offline
  report cover its actual use case.
- A Gymnasium training wrapper would suggest a training study that has not been
  done. The tool interface is suitable for future integration, but no trained
  policy or RL learning result is claimed.

## Extension points

Add a workflow by defining its initial state and public policy, independent
goal/frame/history checks, executable positive/negative controls with witnesses,
and transition-model tests. Add a model integration at the tool-only runner
boundary. New attacks should be reviewed against the policy before changing
the verifier, with a positive control to protect legitimate alternatives.
