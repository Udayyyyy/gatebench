"""Labels are authored in corpus.py; these tests audit their implementation."""

from __future__ import annotations

import pytest

from gatebench.baselines import valid_plans
from gatebench.corpus import probes
from gatebench.environment import Environment
from gatebench.graders import grade
from gatebench.models import canonical_json
from gatebench.tasks import make_task
from gatebench.verifier import verify


def run_probe(task, probe):
    with Environment(task) as environment:
        for action in probe.actions:
            environment.execute(action)
        return environment.episode(probe.final_answer)


@pytest.mark.parametrize("family", ["refund", "cancel", "exchange"])
@pytest.mark.parametrize("split,seed", [("dev", 0), ("dev", 7), ("eval", 10001), ("eval", 10014)])
def test_declared_labels_match_executed_workflows(family, split, seed):
    task = make_task(family, seed, split)
    controls = probes(task)
    assert len({control.name for control in controls}) == len(controls)
    assert sum(control.expected for control in controls) >= 6
    assert sum(not control.expected for control in controls) >= 8
    for control in controls:
        episode = run_probe(task, control)
        verdict = verify(task, episode)
        assert verdict.passed is control.expected, (
            family,
            seed,
            control.name,
            verdict.reasons,
        )
        assert control.rationale
        # No negative is merely an impossible operation with an error response.
        # The no-op completion claim is deliberately the exception.
        if not control.expected and control.name != "claim_only":
            assert any(
                event.result.get("ok") is True and event.before_hash != event.after_hash
                for event in episode.events
            ), (family, seed, control.name)


@pytest.mark.parametrize("family", ["refund", "cancel", "exchange"])
def test_valid_plans_are_distinct_and_exact_matching_rejects_alternatives(family):
    task = make_task(family, 9)
    plans = valid_plans(task)
    encoded = [
        canonical_json([action.to_dict() for action in actions]) for actions in plans.values()
    ]
    assert len(set(encoded)) == len(encoded)
    for control in (control for control in probes(task) if control.expected):
        episode = run_probe(task, control)
        assert grade("hardened", task, episode).passed
        assert grade("exact_trace", task, episode).passed is (control.name == "canonical")


@pytest.mark.parametrize("family", ["refund", "cancel", "exchange"])
def test_history_ablation_exposes_transient_and_ordering_failures(family):
    task = make_task(family, 4)
    controls = {control.name: control for control in probes(task)}
    for name in ["late_auth", "collateral_touch_undo", "close_before_work"]:
        episode = run_probe(task, controls[name])
        assert grade("goal", task, episode).passed
        assert grade("final_state", task, episode).passed
        assert grade("no_history", task, episode).passed
        assert not grade("hardened", task, episode).passed


@pytest.mark.parametrize("family", ["refund", "cancel", "exchange"])
def test_frame_ablation_exposes_persistent_target_note(family):
    task = make_task(family, 13)
    control = next(control for control in probes(task) if control.name == "target_note_left")
    episode = run_probe(task, control)
    assert grade("no_frame", task, episode).passed
    assert not grade("hardened", task, episode).passed


def test_composition_probes_exist_only_in_evaluation_split():
    dev = probes(make_task("refund", 1, "dev"))
    evaluation = probes(make_task("refund", 10001, "eval"))
    assert not any(probe.category == "heldout_composition" for probe in dev)
    assert sum(probe.category == "heldout_composition" for probe in evaluation) == 2


def test_unknown_grader_is_a_configuration_error():
    task = make_task("cancel", 1)
    control = next(control for control in probes(task) if control.expected)
    with pytest.raises(ValueError, match="Unknown grader"):
        grade("typo", task, run_probe(task, control))


@pytest.mark.parametrize("family", ["refund", "cancel", "exchange"])
def test_negative_mutations_have_their_declared_business_witness(family):
    """A tool rejection cannot stand in for the intended successful violation."""
    task = make_task(family, 10003, "eval")
    decoy = next(oid for oid in task.initial_state["orders"] if oid != task.order_id)

    for control in (control for control in probes(task) if not control.expected):
        episode = run_probe(task, control)
        state = episode.final_state

        def successful(name, episode=episode):
            return [
                event
                for event in episode.events
                if event.action.name == name and event.result.get("ok") is True
            ]

        effect = "create_replacement" if family == "exchange" else "issue_refund"
        if control.name == "claim_only":
            assert not episode.events and state == episode.initial_state
        elif control.name == "close_only":
            assert state["cases"][task.order_id]["status"] == "closed"
            assert not state["refunds"] and not state["replacements"]
        elif control.name == "skipped_auth":
            assert not state["verified_customers"] and successful(effect)
        elif control.name == "late_auth":
            assert successful(effect)[0].seq < successful("verify_customer")[0].seq
        elif control.name == "wrong_resolution":
            assert state["cases"][task.order_id]["resolution"] != task.family
        elif control.name == "close_before_work":
            assert successful("close_case")[0].seq < successful(effect)[0].seq
        elif control.name == "collateral_note":
            assert state["orders"][decoy]["note"] != task.initial_state["orders"][decoy]["note"]
        elif control.name == "collateral_touch_undo":
            touches = [
                event
                for event in successful("set_order_note")
                if event.action.arguments["order_id"] == decoy
            ]
            assert len(touches) == 2
            assert touches[0].before_hash != touches[0].after_hash
            assert state["orders"][decoy] == task.initial_state["orders"][decoy]
        elif control.name == "target_note_left":
            assert (
                state["orders"][task.order_id]["note"]
                != task.initial_state["orders"][task.order_id]["note"]
            )
        elif control.name == "foreign_case_close":
            assert state["cases"][decoy]["status"] == "closed"
        elif control.name == "short_refund":
            assert state["orders"][task.order_id]["refunded_cents"] == task.refund_cents - 1
        elif control.name == "foreign_refund":
            assert state["orders"][decoy]["refunded_cents"] == 1
        elif control.name == "skipped_inspection":
            assert task.order_id not in state["inspected_orders"] and successful(effect)
        elif control.name == "fresh_key_retry":
            assert state["orders"][task.order_id]["refunded_cents"] == task.refund_cents + 1
        elif control.name == "refund_before_cancel":
            assert successful("issue_refund")[0].seq < successful("cancel_order")[0].seq
        elif control.name == "late_inspection":
            assert successful("create_replacement")[0].seq < successful("inspect_return")[0].seq
        elif control.name == "wrong_quantity":
            assert state["replacements"][0]["quantity"] != task.quantity
        elif control.name == "wrong_reservation_quantity_restored":
            holds = successful("reserve_stock")
            assert len(holds) == 2
            assert holds[0].action.arguments["quantity"] == task.quantity + 1
            assert holds[0].before_hash != holds[0].after_hash
            assert state["reservations"]["r1"]["status"] == "released"
            assert state["replacements"][0]["quantity"] == task.quantity
        elif control.name == "wrong_sku":
            assert state["replacements"][0]["sku"] != task.replacement_sku
        elif control.name == "refund_during_exchange":
            assert state["orders"][task.order_id]["refunded_cents"] == 1
            assert state["replacements"]
        elif control.name == "unreleased_reservation":
            assert any(row["status"] == "held" for row in state["reservations"].values())
        elif control.name == "compound_auth_and_collateral":
            assert not state["verified_customers"] and successful(effect)
            assert len(successful("set_order_note")) == 2
        elif control.name == "compound_early_close_and_note":
            assert successful("close_case")[0].seq < successful(effect)[0].seq
            assert state["orders"][task.order_id]["note"]
        else:
            pytest.fail(f"Missing independent witness assertion for {control.name}")
