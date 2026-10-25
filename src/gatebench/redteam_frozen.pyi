# Typed interface kept outside the byte-frozen pre-assessment generator.
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gatebench.models import Action, Episode
from gatebench.tasks import Task

@dataclass(frozen=True)
class FrozenPlan:
    name: str
    expected: bool
    category: str
    reason: str
    actions: tuple[Action, ...]
    witness: dict[str, Any]
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FrozenPlan: ...

def candidate_plans(task: Task) -> tuple[FrozenPlan, ...]: ...
def execute_plan(task: Task, plan: FrozenPlan) -> Episode: ...
def label_witness(task: Task, plan: FrozenPlan, episode: Episode) -> dict[str, Any]: ...
def write_freeze(directory: Path, *, seed_start: int = 10040, seeds: int = 4) -> dict[str, Any]: ...
def load_freeze(directory: Path) -> list[tuple[Task, FrozenPlan]]: ...
