from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gatebench.models import Episode
from gatebench.runner import audit, verify_manifest, write_json
from gatebench.tasks import FAMILIES, Task, make_task
from gatebench.verifier import verify


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit outcome verifiers using executable controls."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("audit", help="run the labeled, scripted verifier audit")
    run.add_argument("--output", type=Path, default=Path("runs/audit"))
    run.add_argument("--split", choices=("dev", "eval", "all"), default="all")
    run.add_argument("--per-family", type=int, default=12)
    run.add_argument("--bootstrap-samples", type=int, default=2000)
    replay = sub.add_parser("replay", help="independently replay one captured episode")
    replay.add_argument("task", type=Path)
    replay.add_argument("episode", type=Path)
    check = sub.add_parser("check-manifest", help="check artifact hashes (not authorship)")
    check.add_argument("directory", type=Path)
    integrity = sub.add_parser("integrity", help="test serialized evidence corruption separately")
    integrity.add_argument("--output", type=Path, default=Path("runs/integrity"))
    inspect = sub.add_parser("inspect", help="print a generated public task")
    inspect.add_argument("--family", choices=FAMILIES, default="refund")
    inspect.add_argument("--seed", type=int, default=0)
    inspect.add_argument("--split", choices=("dev", "eval"), default="dev")
    model = sub.add_parser("model", help="run one real Ollama model trial")
    model.add_argument("--model", required=True)
    model.add_argument("--endpoint", default="http://127.0.0.1:11434")
    model.add_argument("--family", choices=FAMILIES, default="refund")
    model.add_argument("--seed", type=int, default=10000)
    model.add_argument("--output", type=Path, default=Path("runs/model"))
    model.add_argument("--max-steps", type=int, default=32)
    model.add_argument("--max-turns", type=int, default=24)
    model.add_argument("--timeout", type=float, default=30)
    model.add_argument("--deadline", type=float, default=120)
    study = sub.add_parser("study", help="collect or resume a frozen real-model study")
    study.add_argument("--config", type=Path, default=Path("configs/real-model-study.json"))
    study.add_argument("--output", type=Path, default=Path("runs/real-models-v1"))
    study.add_argument("--endpoint", default="http://127.0.0.1:11434")
    summary = sub.add_parser(
        "study-summary", help="validate and summarize captured model trials offline"
    )
    summary.add_argument("directory", type=Path)
    evidence = sub.add_parser(
        "verify-study", help="replay captured study evidence offline (not proof of origin)"
    )
    evidence.add_argument("directory", type=Path)
    redteam = sub.add_parser("redteam", help="assess committed independent controls")
    redteam.add_argument("--output", type=Path, default=Path("runs/redteam"))
    redteam.add_argument("--freeze", type=Path, default=Path("data/redteam/v1"))
    tau = sub.add_parser("tau-audit", help="execute pinned native retail controls (tau extra)")
    tau.add_argument("--output", type=Path, default=Path("runs/tau-retail"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "audit":
            summary = audit(
                args.output,
                split=args.split,
                per_family=args.per_family,
                bootstrap_samples=args.bootstrap_samples,
            )
            print(json.dumps(summary["corpus"], indent=2))
            print(f"Report: {args.output / 'report.html'}")
            return 0
        if args.command == "replay":
            task = Task.from_dict(json.loads(args.task.read_text()))
            episode = Episode.from_dict(json.loads(args.episode.read_text()))
            verdict = verify(task, episode)
            print(json.dumps(verdict.to_dict(), indent=2))
            return 0 if verdict.passed else 1
        if args.command == "check-manifest":
            problems = verify_manifest(args.directory)
            print(json.dumps({"valid": not problems, "problems": problems}, indent=2))
            return int(bool(problems))
        if args.command == "integrity":
            from gatebench.integrity import audit_integrity

            result = audit_integrity(args.output)
            print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
            return 0
        if args.command == "inspect":
            print(make_task(args.family, args.seed, args.split).prompt)
            return 0
        if args.command == "model":
            from gatebench.ollama import run_model

            if args.output.exists() and any(args.output.iterdir()):
                raise ValueError("model output directory must be empty")
            task = make_task(args.family, args.seed, "eval")
            episode, record = run_model(
                task,
                model=args.model,
                endpoint=args.endpoint,
                max_steps=args.max_steps,
                max_turns=args.max_turns,
                timeout=args.timeout,
                deadline=args.deadline,
            )
            verdict = verify(task, episode)
            write_json(args.output / "task.json", task.to_dict())
            write_json(args.output / "episode.json", episode.to_dict())
            write_json(args.output / "model.json", record)
            write_json(args.output / "verdict.json", verdict.to_dict())
            print(json.dumps(verdict.to_dict(), indent=2))
            return 0 if verdict.passed else 1
        if args.command == "study":
            from gatebench.experiments.runner import collect_study

            result = collect_study(args.config, args.output, endpoint=args.endpoint)
            print(json.dumps(result["corpus"], indent=2))
            return 0
        if args.command == "study-summary":
            from gatebench.experiments.runner import summarize_study

            print(json.dumps(summarize_study(args.directory)["corpus"], indent=2))
            return 0
        if args.command == "verify-study":
            from gatebench.experiments.verification import verify_study

            result = verify_study(args.directory)
            print(json.dumps(result, indent=2))
            return 0 if result["valid"] else 1
        if args.command == "redteam":
            from gatebench.redteam_audit import audit_redteam

            result = audit_redteam(args.output, args.freeze)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "tau-audit":
            from gatebench.integrations.tau_retail import run_audit

            print(json.dumps(run_audit(args.output), indent=2))
            return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(f"gatebench: {exc}", file=sys.stderr)
        return 2
    return 2
