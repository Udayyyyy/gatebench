"""Structural/label-witness checks; deliberately never import any grader."""

import hashlib
import json
from pathlib import Path

import pytest

from gatebench.models import Action
from gatebench.redteam_frozen import (
    candidate_plans,
    execute_plan,
    label_witness,
    load_freeze,
)
from gatebench.tasks import FAMILIES, make_task
from gatebench.tooling import validate_action


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("seed", (0, 1, 2, 3))
def test_development_structural_execution_and_independent_label_witness(family, seed):
    task = make_task(family, seed, "dev")
    plans = candidate_plans(task)
    assert len({plan.name for plan in plans}) == len(plans)
    assert sum(plan.expected for plan in plans) >= 8
    for plan in plans:
        for action in plan.actions:
            assert validate_action(action) is None, (plan.name, action)
            assert Action.from_dict(action.to_dict()) == action
        episode = execute_plan(task, plan)
        witness = label_witness(task, plan, episode)
        if not plan.expected:
            event = episode.events[witness["event_index"]]
            assert event.result["ok"] is True
            assert witness["changed_state"] is True


def test_template_diversity_is_counted_separately_from_seed_count():
    plans = [plan for family in FAMILIES for plan in candidate_plans(make_task(family, 0))]
    negatives = {plan.name for plan in plans if not plan.expected}
    positives = {plan.name for plan in plans if plan.expected}
    assert len(negatives) >= 15
    assert len(positives) >= 8
    assert {plan.category for plan in plans if not plan.expected} >= {
        "scope_repaired_note",
        "closure_partial_outcome",
        "retry_duplicate_charge",
        "inventory_temporary_wrong_sku",
        "exchange_wrong_quantity",
        "refund_partial_ordering",
    }


def test_frozen_literal_actions_labels_and_policy_digest():
    directory = Path(__file__).resolve().parents[1] / "data" / "redteam" / "v1"
    if not (directory / "manifest.json").exists():
        pytest.skip("freeze has not been written yet; no grading is permitted")
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["tasks"] == 12
    assert manifest["seeds"] == [10040, 10041, 10042, 10043]
    assert manifest["template_counts"]["invalid"] >= 15
    assert manifest["template_counts"]["valid"] >= 8
    source = directory.parents[2] / "src" / "gatebench" / "redteam_frozen.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["generator_sha256"]
    cases = load_freeze(directory)
    assert len({task.id for task, _ in cases}) == 12
    for task, plan in cases:
        label_witness(task, plan, execute_plan(task, plan))
