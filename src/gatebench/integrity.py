"""Serialized evidence corruption controls, separate from executable workflows."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

from gatebench.baselines import reference_plan
from gatebench.environment import Environment
from gatebench.models import Episode, digest
from gatebench.tasks import FAMILIES, make_task
from gatebench.verifier import verify


def corruptions(episode: Episode) -> dict[str, Episode]:
    first = episode.events[0]
    result = copy.deepcopy(first.result)
    result["order"]["note"] = "invented tool result"
    final = copy.deepcopy(episode.final_state)
    final["orders"][next(iter(final["orders"]))]["note"] = "invented final snapshot"
    return {
        "wrong_task": replace(episode, task_id="different-task"),
        "sequence_gap": replace(episode, events=(replace(first, seq=4), *episode.events[1:])),
        "forged_read_result": replace(
            episode, events=(replace(first, result=result), *episode.events[1:])
        ),
        "broken_state_hash": replace(
            episode, events=(replace(first, after_hash="0" * 64), *episode.events[1:])
        ),
        "missing_read": replace(episode, events=episode.events[1:]),
        "forged_final_state": replace(episode, final_state=final),
        "budget_termination": replace(episode, stop_reason="budget"),
    }


def audit_integrity(output: Path) -> dict[str, Any]:
    from gatebench.runner import write_json

    rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        task = make_task(family, 10000, "eval")
        with Environment(task) as env:
            for action in reference_plan(task):
                env.execute(action)
            clean = env.episode("Completed.")
        if not verify(task, clean).passed:
            raise ValueError("integrity suite positive control failed")
        for name, episode in corruptions(clean).items():
            full = verify(task, episode)
            without = verify(task, episode, check_replay=False)
            rows.append(
                {
                    "family": family,
                    "corruption": name,
                    "expected": False,
                    "hardened": full.passed,
                    "no_replay": without.passed,
                    "reasons": list(full.reasons),
                    "episode_digest": digest(episode.to_dict()),
                }
            )
    result = {
        "kind": "serialized_evidence_integrity",
        "controls": len(rows),
        "rejected": sum(not row["hardened"] for row in rows),
        "no_replay_accepted": sum(row["no_replay"] for row in rows),
        "rows": rows,
        "limitation": "Corrupted artifacts are not executable agent trajectories. Consistent wholesale forgery is outside offline authentication guarantees.",
    }
    write_json(output / "integrity.json", result)
    if result["rejected"] != result["controls"]:
        raise ValueError("independent replay accepted a corrupted-evidence control")
    return result
