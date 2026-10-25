"""Comparable grading designs and one-check-removed verifier ablations."""

from __future__ import annotations

from .baselines import reference_plan
from .models import Episode, Verdict
from .tasks import Task
from .verifier import goal_satisfied, verify

GRADERS = (
    "transcript",
    "goal",
    "final_state",
    "exact_trace",
    "hardened",
    "no_history",
    "no_frame",
    "no_replay",
)


def grade(name: str, task: Task, episode: Episode) -> Verdict:
    if name == "transcript":
        passed = "completed" in episode.final_answer.lower()
        return Verdict(passed, () if passed else ("No completion claim in final answer.",))
    if name == "goal":
        passed = goal_satisfied(task, episode.final_state)
        return Verdict(passed, () if passed else ("Requested final fields are not satisfied.",))
    if name == "exact_trace":
        actions = [event.action for event in episode.events]
        passed = actions == reference_plan(task)
        return Verdict(passed, () if passed else ("Tool calls differ from the canonical plan.",))
    options = {
        "final_state": {"check_history": False, "check_replay": False},
        "hardened": {},
        "no_history": {"check_history": False},
        "no_frame": {"check_frame": False},
        "no_replay": {"check_replay": False},
    }
    if name not in options:
        raise ValueError(f"Unknown grader: {name!r}. Choose from {', '.join(GRADERS)}.")
    return verify(task, episode, **options[name])
