"""Execute labeled controls and retain enough evidence to inspect disagreements."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from gatebench import __version__
from gatebench.corpus import Probe, probes
from gatebench.environment import Environment
from gatebench.graders import GRADERS, grade
from gatebench.models import Episode, canonical_json, digest
from gatebench.report import write_report
from gatebench.statistics import summarize
from gatebench.tasks import Task, suite


def execute_probe(task: Task, probe: Probe) -> Episode:
    with Environment(task) as env:
        for action in probe.actions:
            env.execute(action)
        return env.episode(probe.final_answer)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _revision() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def source_fingerprint() -> str:
    source = Path(__file__).resolve().parent
    return digest(
        {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.glob("*.py"))}
    )


def audit(
    output: Path, *, split: str = "all", per_family: int = 12, bootstrap_samples: int = 2000
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    splits = ("dev", "eval") if split == "all" else (split,)
    tasks = [task for part in splits for task in suite(part, per_family)]
    rows: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    mismatches: list[str] = []
    # Tasks and artifacts are addressed by stable IDs; wall time is metadata, not evidence.
    with (output / "episodes.jsonl").open("w") as episodes:
        for task in tasks:
            write_json(output / "tasks" / f"{task.id}.json", task.to_dict())
            for probe in probes(task):
                episode = execute_probe(task, probe)
                verdicts = {name: grade(name, task, episode) for name in GRADERS}
                row = {
                    "task_id": task.id,
                    "family": task.family,
                    "split": task.split,
                    "probe": probe.name,
                    "expected": probe.expected,
                    "rationale": probe.rationale,
                    "category": getattr(probe, "category", "control"),
                    "graders": {name: verdict.passed for name, verdict in verdicts.items()},
                    "reasons": {name: list(verdict.reasons) for name, verdict in verdicts.items()},
                    "events": len(episode.events),
                    "episode_digest": digest(episode.to_dict()),
                }
                rows.append(row)
                labels.append(
                    {k: row[k] for k in ("task_id", "probe", "expected", "rationale", "category")}
                )
                episodes.write(
                    canonical_json(
                        {"task_id": task.id, "probe": probe.name, "episode": episode.to_dict()}
                    )
                    + "\n"
                )
                if verdicts["hardened"].passed != probe.expected:
                    mismatches.append(f"{task.id}/{probe.name}: {verdicts['hardened'].reasons}")
    write_json(output / "rows.json", rows)
    write_json(output / "labels.json", labels)
    if mismatches:
        write_json(output / "label_disagreements.json", mismatches)
        raise ValueError(
            "hardened verifier disagrees with independently labeled controls: "
            + "; ".join(mismatches[:5])
        )
    summary = summarize(rows, bootstrap_samples=bootstrap_samples)
    write_json(output / "summary.json", summary)
    write_report(summary, rows, output)
    payload_files = sorted(p for p in output.rglob("*") if p.is_file())
    manifest = {
        "schema_version": 1,
        "project_version": __version__,
        "source_fingerprint": source_fingerprint(),
        "git_revision": _revision(),
        "python": platform.python_version(),
        "kind": "scripted_verifier_audit",
        "split": split,
        "per_family": per_family,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": 17,
        "tasks_digest": digest([t.to_dict() for t in tasks]),
        "rows_digest": digest(rows),
        "files": {
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in payload_files
        },
    }
    write_json(output / "manifest.json", manifest)
    return summary


def verify_manifest(directory: Path) -> list[str]:
    manifest = json.loads((directory / "manifest.json").read_text())
    problems = []
    root = directory.resolve()
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            problems.append(f"unsafe manifest path: {name}")
        elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append(f"missing or changed artifact: {name}")
    return problems
