"""A final-state grader misses a refund that was issued before authentication."""

from gatebench.corpus import probes
from gatebench.graders import grade
from gatebench.runner import execute_probe
from gatebench.tasks import make_task

task = make_task("refund", 0)
probe = next(p for p in probes(task) if p.name == "late_auth")
episode = execute_probe(task, probe)

print(probe.rationale)
for event in episode.events:
    print(f"{event.seq}: {event.action.name} -> {event.result['ok']}")
for grader in ("goal", "final_state", "hardened"):
    verdict = grade(grader, task, episode)
    print(f"{grader}: {'PASS' if verdict.passed else 'FAIL'}")
    for reason in verdict.reasons:
        print(f"  {reason}")
