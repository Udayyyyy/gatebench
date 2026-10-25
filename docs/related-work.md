# Related work and provenance

Public sources reviewed on 25 October 2026. This repository implements its own
synthetic tasks, tools, mutation fixtures, replay model, and reports. The separate
retail integration vendors 29 unchanged upstream code/data/license files from
the pinned Sierra Research release; its provenance is described below.

- [Anthropic, Demystifying evals for AI agents (2026)](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).
  Motivates inspecting actual environment outcomes, accepting valid alternatives,
  reviewing transcripts, and checking graders for bypasses.
- [Yao et al., τ-bench (2024)](https://arxiv.org/abs/2406.12045) and
  [Sierra Research's current implementation](https://github.com/sierra-research/tau2-bench).
  Establish stateful tool-use evaluation in realistic support domains. GateBench
  uses its own smaller deterministic environment to study grading designs, and
  separately runs the original retail tools and ENV/DB evaluator from v1.0.1,
  commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`. The fixed-input adaptation
  and preserved MIT notice are documented in [the integration](public-benchmark.md).
  It does not reproduce the complete interactive benchmark or its leaderboard.
- [Zhong et al., Hardening Agent Benchmarks with Adversarial Hacker-Fixer Loops (2026)](https://arxiv.org/abs/2606.08960).
  Studies exploiting and patching benchmark verifiers. GateBench uses explicit
  scripted mutation operators and separately developed model-assisted controls;
  it does not implement an iterative verifier-guided hacker-fixer optimization loop.
- [Zheng et al., BenchShield (2026)](https://arxiv.org/abs/2609.11028).
  Motivates treating evaluation boundaries and infrastructure-side evidence as
  part of the measurement problem. GateBench's replay is a bounded consistency
  check, not BenchShield's taint analysis or an authenticity guarantee.
- [Ollama chat API](https://docs.ollama.com/api/chat) and
  [tool calling protocol](https://docs.ollama.com/capabilities/tool-calling).
  The optional adapter uses these documented HTTP interfaces without an SDK.

The project is independent of Uday's employer work. Company affiliation does not
imply endorsement. The synthetic customers, orders, amounts, and proof codes are
generated locally and do not represent actual people or transactions.
