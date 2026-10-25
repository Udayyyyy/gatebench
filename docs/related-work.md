# Related work and provenance

Public sources reviewed on 25 October 2026. This repository implements its own
synthetic tasks, tools, mutation fixtures, replay model, and reports. No task
data or implementation code was copied from these projects.

- [Anthropic, Demystifying evals for AI agents (2026)](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).
  Motivates inspecting actual environment outcomes, accepting valid alternatives,
  reviewing transcripts, and checking graders for bypasses.
- [Yao et al., τ-bench (2024)](https://arxiv.org/abs/2406.12045) and
  [Sierra Research's current implementation](https://github.com/sierra-research/tau2-bench).
  Establish stateful tool-use evaluation in realistic support domains. GateBench
  uses a smaller deterministic environment to study grading designs themselves;
  it does not claim to replace τ-bench or reproduce its leaderboard.
- [Zhong et al., Hardening Agent Benchmarks with Adversarial Hacker-Fixer Loops (2026)](https://arxiv.org/abs/2606.08960).
  Studies exploiting and patching benchmark verifiers. GateBench uses explicit
  scripted mutation operators, not an LLM hacker-fixer optimization loop.
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
