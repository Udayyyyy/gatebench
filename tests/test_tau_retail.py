from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from gatebench.integrations.tau_retail import (
    UPSTREAM_COMMIT,
    TauRetailEnvironment,
    audit_policy,
    evaluate,
    evaluate_native,
    load_suite,
    prepare_sources,
    provenance,
    reference_actions,
    run_audit,
    selection_ledger,
    verify_sources,
)
from gatebench.models import Action

_DEPENDENCIES = (
    "pydantic",
    "pandas",
    "docstring_parser",
    "deepdiff",
    "loguru",
    "dotenv",
    "yaml",
    "toml",
    "addict",
)
pytestmark = pytest.mark.skipif(
    any(importlib.util.find_spec(name) is None for name in _DEPENDENCIES),
    reason="install the optional tau extra to run native public-benchmark tests",
)


def capture(case, actions=None):
    with TauRetailEnvironment(case) as environment:
        for action in reference_actions(case) if actions is None else actions:
            environment.execute(action)
        return environment.episode("Completed.")


def test_pinned_source_slice_can_be_materialized_without_network(tmp_path: Path) -> None:
    source = prepare_sources(tmp_path / "native")
    verify_sources(source)
    assert provenance()["commit"] == UPSTREAM_COMMIT
    assert (source / "LICENSE").read_text().startswith("MIT License")
    assert len(provenance()["files"]) == 29
    (source / "src/tau2/domains/retail/tools.py").write_text("changed")
    with pytest.raises(ValueError, match="missing or changed"):
        prepare_sources(source)


def test_selection_is_deterministic_and_accounts_for_every_public_task() -> None:
    cases = load_suite()
    assert [case.upstream_id for case in cases] == ["0", "1", "2", "19", "38", "66"]
    ledger = selection_ledger()
    assert len(ledger) == 114
    assert sum(row["selection"] == "selected" for row in ledger) == 6
    assert all(row["selection"] for row in ledger)
    assert {row["upstream_id"] for row in ledger} == {str(i) for i in range(114)}
    assert [case.fingerprint for case in cases] == [case.fingerprint for case in load_suite()]


def test_model_prompt_uses_public_scenario_without_reference_plan() -> None:
    for case in load_suite():
        assert "fixed-input protocol" in case.prompt
        assert case.native_task["user_scenario"]["instructions"]["known_info"] in case.prompt
        assert "evaluation_criteria" not in case.prompt
        for action in case.native_task["evaluation_criteria"]["actions"]:
            for field in ("item_ids", "new_item_ids"):
                for hidden_identifier in action["arguments"].get(field, []):
                    assert hidden_identifier not in case.prompt


def test_native_structural_study_executes_all_preselected_controls(tmp_path: Path) -> None:
    summary = run_audit(tmp_path / "audit")
    assert summary["cases"] == 6
    assert summary["controls"] == 60
    assert summary["valid"] == 24
    assert summary["invalid"] == summary["native_accepted_invalid"] == 36
    assert summary["hardened_accepted_invalid"] == summary["hardened_rejected_valid"] == 0
    assert len(list((tmp_path / "audit/episodes").glob("*.json"))) == 60
    assert all(row["native_environment_reward"] == 1.0 for row in summary["rows"])
    restored = [row for row in summary["rows"] if row["control"] == "foreign_address_restored"]
    assert len(restored) == 6
    for row in restored:
        episode = json.loads(
            (tmp_path / "audit/episodes" / f"{row['case_id']}-{row['control']}.json").read_text()
        )
        writes = [e for e in episode["events"] if e["action"]["name"] == "modify_user_address"]
        assert len(writes) == 2
        assert all(e["result"]["ok"] and e["changed_records"]["users"] for e in writes)
        assert any("another customer's profile" in reason for reason in row["reasons"])


def test_native_backend_and_reward_are_original_upstream_classes() -> None:
    case = load_suite()[0]
    with TauRetailEnvironment(case) as environment:
        assert type(environment.env.tools).__module__ == "tau2.domains.retail.tools"
        assert environment.native.evaluator.__module__ == "tau2.evaluator.evaluator_env"
        assert len(environment.tool_schemas) == 16
    result = evaluate_native(case, capture(case))
    assert result["details"]["db_check"]["db_match"]
    assert result["details"]["reward_breakdown"] == {"DB": 1.0}
    assert result["full_benchmark_score"] is False


def test_native_expected_actions_are_not_a_required_policy_trajectory() -> None:
    case = next(case for case in load_suite() if case.upstream_id == "38")
    raw = [
        Action(a["name"], a["arguments"])
        for a in case.native_task["evaluation_criteria"]["actions"]
    ]
    episode = capture(case, raw)
    assert episode["events"][0]["result"]["ok"] is False
    assert evaluate_native(case, episode)["reward"] == 1.0
    assert any("status was not checked" in reason for reason in audit_policy(case, episode).reasons)
    assert evaluate(case, capture(case))["hardened_passed"]


def test_replay_checks_reads_that_native_env_reward_does_not_compare() -> None:
    case = load_suite()[0]
    episode = capture(case)
    corrupt = copy.deepcopy(episode)
    corrupt["events"][0]["result"]["value"] = "invented-customer"
    # The unchanged native scorer focuses on mutating state, not read evidence.
    assert evaluate_native(case, corrupt)["reward"] == 1.0
    assert not audit_policy(case, corrupt).passed


def test_termination_and_task_identity_cannot_be_overridden_by_native_goal() -> None:
    case = load_suite()[0]
    episode = capture(case)
    episode["stop_reason"] = "budget"
    result = evaluate(case, episode)
    assert result["native_environment"]["reward"] == 1.0
    assert not result["hardened_passed"]
    episode["task_fingerprint"] = "different-task"
    assert not audit_policy(case, episode).passed
    assert result["unassessed"]


@pytest.mark.parametrize(
    "bad", [{}, {"events": "not a list"}, {"events": [None]}, {"events": [None] * 1001}]
)
def test_malformed_policy_evidence_fails_closed(bad) -> None:
    assert not audit_policy(load_suite()[0], bad).passed
