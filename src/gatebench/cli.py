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
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"gatebench: {exc}", file=sys.stderr)
        return 2
    return 2
