from __future__ import annotations

import copy
import random
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gatebench.environment import Environment
from gatebench.models import Action, Episode, canonical_json, digest
from gatebench.replay import reduce_action, replay
from gatebench.tasks import make_task
from gatebench.tooling import validate_action


@settings(max_examples=75, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 5), st.integers(1, 100_000)), min_size=1, max_size=40))
def test_refund_accounting_matches_an_independent_ledger(attempts):
    task = make_task("refund", 3)
    paid = task.initial_state["orders"][task.order_id]["paid_cents"]
    ledger = {}
    with Environment(task) as env:
        for key_number, amount in attempts:
            key = f"key-{key_number}"
            previous = env.snapshot()
            result = env.execute(
                Action(
                    "issue_refund",
                    {"order_id": task.order_id, "amount_cents": amount, "idempotency_key": key},
                )
            )
            total = sum(row[0] for row in ledger.values())
            if key in ledger:
                old_amount, refund_id = ledger[key]
                assert result["ok"] is (amount == old_amount)
                if amount == old_amount:
                    assert result == {"ok": True, "refund_id": refund_id, "reused": True}
                assert env.snapshot() == previous
            elif amount > paid - total:
                assert result["ok"] is False
                assert env.snapshot() == previous
            else:
                refund_id = f"f{len(ledger) + 1}"
                ledger[key] = (amount, refund_id)
                assert result == {"ok": True, "refund_id": refund_id, "reused": False}
            snapshot = env.snapshot()
            expected_total = sum(row[0] for row in ledger.values())
            assert snapshot["orders"][task.order_id]["refunded_cents"] == expected_total
            assert sum(row["amount_cents"] for row in snapshot["refunds"]) == expected_total
            assert len(snapshot["refunds"]) == len(ledger)
            assert 0 <= expected_total <= paid


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(st.sampled_from(["reserve", "release", "consume"]), st.integers(1, 20)),
        min_size=1,
        max_size=35,
    )
)
def test_stock_conservation_under_arbitrary_reservation_attempts(attempts):
    task = make_task("exchange", 5)
    sku = task.replacement_sku
    initial = task.initial_state["inventory"][sku]
    reservations = {}
    with Environment(task) as env:
        for operation, value in attempts:
            previous = env.snapshot()
            available = initial - sum(
                qty for qty, status in reservations.values() if status != "released"
            )
            if operation == "reserve":
                action = Action("reserve_stock", {"sku": sku, "quantity": value})
                expected_success = value <= available
            else:
                rid = f"r{value}"
                action = (
                    Action("release_stock", {"reservation_id": rid})
                    if operation == "release"
                    else Action(
                        "create_replacement", {"order_id": task.order_id, "reservation_id": rid}
                    )
                )
                expected_success = rid in reservations and reservations[rid][1] == "held"
            result = env.execute(action)
            assert result["ok"] is expected_success
            if not expected_success:
                assert env.snapshot() == previous
            elif operation == "reserve":
                reservations[f"r{len(reservations) + 1}"] = (value, "held")
            else:
                quantity, _ = reservations[rid]
                reservations[rid] = (quantity, "released" if operation == "release" else "consumed")
            snapshot = env.snapshot()
            committed = sum(qty for qty, status in reservations.values() if status != "released")
            assert snapshot["inventory"][sku] + committed == initial
            assert snapshot["inventory"][sku] >= 0
            assert sum(row["quantity"] for row in snapshot["replacements"]) == sum(
                qty for qty, status in reservations.values() if status == "consumed"
            )


@pytest.mark.parametrize("amount", [True, False, 0, -1, 1.0, "1", None, 1_000_000_001])
def test_money_schema_rejects_non_integer_and_out_of_range_values_without_effect(amount):
    task = make_task("refund", 2)
    with Environment(task) as env:
        before = env.snapshot()
        result = env.execute(
            Action(
                "issue_refund",
                {
                    "order_id": task.order_id,
                    "amount_cents": amount,
                    "idempotency_key": "bad-amount",
                },
            )
        )
        assert result["ok"] is False
        assert env.snapshot() == before
        assert env.events[-1].before_hash == env.events[-1].after_hash


@pytest.mark.parametrize(
    "action",
    [
        Action("nonexistent", {}),
        Action("get_order", {}),
        Action("get_order", {"order_id": "unknown", "unexpected": 1}),
        Action("get_order", {"order_id": ""}),
        Action("get_order", {"order_id": "x" * 1001}),
        Action("get_order", {"order_id": 123}),
        Action("close_case", {"order_id": "unknown", "resolution": "something_else"}),
        Action("reserve_stock", {"sku": "unknown", "quantity": True}),
    ],
)
def test_invalid_action_schema_is_logged_and_atomic(action):
    task = make_task("cancel", 2)
    with Environment(task) as env:
        before = env.snapshot()
        assert validate_action(action) is not None
        assert env.execute(action)["ok"] is False
        assert env.snapshot() == before
        assert len(env.events) == 1


def test_payload_reuse_is_global_and_conflicts_never_change_state():
    task = make_task("refund", 4)
    decoy = next(oid for oid in task.initial_state["orders"] if oid != task.order_id)
    with Environment(task) as env:
        action = Action(
            "issue_refund",
            {"order_id": task.order_id, "amount_cents": 1, "idempotency_key": "global-key"},
        )
        assert env.execute(action)["reused"] is False
        before = env.snapshot()
        assert env.execute(action) == {"ok": True, "refund_id": "f1", "reused": True}
        for order_id, amount in [(task.order_id, 2), (decoy, 1)]:
            conflict = Action(
                "issue_refund",
                {"order_id": order_id, "amount_cents": amount, "idempotency_key": "global-key"},
            )
            assert env.execute(conflict)["ok"] is False
            assert env.snapshot() == before


def test_failed_reservation_operations_preserve_every_table():
    task = make_task("exchange", 8)
    actions = [
        Action("reserve_stock", {"sku": task.replacement_sku, "quantity": 1_000_000}),
        Action("release_stock", {"reservation_id": "unknown"}),
        Action("create_replacement", {"order_id": task.order_id, "reservation_id": "unknown"}),
        Action("create_replacement", {"order_id": "unknown", "reservation_id": "r1"}),
    ]
    with Environment(task) as env:
        env.execute(Action("reserve_stock", {"sku": task.replacement_sku, "quantity": 1}))
        before = env.snapshot()
        for action in actions:
            assert env.execute(action)["ok"] is False
            assert env.snapshot() == before


def test_episode_state_and_results_are_not_aliased_to_callers():
    task = make_task("refund", 2)
    original_task = copy.deepcopy(task.to_dict())
    with Environment(task) as first, Environment(task) as second:
        args = {"order_id": task.order_id, "note": "One episode only"}
        first.execute(Action("set_order_note", args))
        args["note"] = "changed by caller"
        result = first.execute(Action("get_order", {"order_id": task.order_id}))
        result["order"]["note"] = "changed returned result"
        snapshot = first.snapshot()
        snapshot["orders"][task.order_id]["note"] = "changed snapshot"
        episode = first.episode()
        episode.events[-1].result["order"]["note"] = "changed episode"
        assert first.snapshot()["orders"][task.order_id]["note"] == "One episode only"
        assert first.events[0].action.arguments["note"] == "One episode only"
        assert first.events[-1].result["order"]["note"] == "One episode only"
        assert second.snapshot() == task.initial_state
    assert task.to_dict() == original_task


def test_twelve_generated_ids_replay_with_lexicographic_snapshot_order():
    original = make_task("exchange", 6)
    state = copy.deepcopy(original.initial_state)
    state["inventory"][original.replacement_sku] = 30
    task = replace(original, initial_state=state)
    with Environment(task) as env:
        for index in range(1, 13):
            assert (
                env.execute(
                    Action(
                        "issue_refund",
                        {
                            "order_id": task.order_id,
                            "amount_cents": 1,
                            "idempotency_key": f"key-{index}",
                        },
                    )
                )["ok"]
                is True
            )
            assert (
                env.execute(Action("reserve_stock", {"sku": task.replacement_sku, "quantity": 1}))[
                    "reservation_id"
                ]
                == f"r{index}"
            )
            assert (
                env.execute(
                    Action(
                        "create_replacement",
                        {"order_id": task.order_id, "reservation_id": f"r{index}"},
                    )
                )["replacement_id"]
                == f"x{index}"
            )
        episode = env.episode()
    assert [row["refund_id"] for row in episode.final_state["refunds"]] == sorted(
        f"f{i}" for i in range(1, 13)
    )
    assert [row["replacement_id"] for row in episode.final_state["replacements"]] == sorted(
        f"x{i}" for i in range(1, 13)
    )
    assert replay(task, episode).passed
    restored = Episode.from_dict(episode.to_dict())
    assert canonical_json(restored.to_dict()) == canonical_json(episode.to_dict())
    assert digest(restored.to_dict()) == digest(episode.to_dict())


def test_task_generation_does_not_depend_on_global_random_state():
    before = make_task("refund", 7, "eval")
    random.seed(123)
    for _ in range(50):
        random.random()
    assert make_task("refund", 7, "eval") == before


@settings(max_examples=90, deadline=None)
@given(
    st.sampled_from(["refund", "cancel", "exchange"]),
    st.lists(st.tuples(st.integers(0, 10), st.integers(0, 30)), min_size=1, max_size=45),
)
def test_sqlite_and_pure_python_replay_conform_on_mixed_tool_sequences(family, attempts):
    task = make_task(family, 12)
    decoy = next(oid for oid in task.initial_state["orders"] if oid != task.order_id)
    old_sku = task.initial_state["orders"][task.order_id]["sku"]
    with Environment(task) as env:
        for operation, value in attempts:
            order_id = [task.order_id, decoy, "unknown"][value % 3]
            actions = [
                Action("get_order", {"order_id": order_id}),
                Action(
                    "verify_customer",
                    {
                        "customer_id": task.customer_id,
                        "code": task.auth_code if value % 2 else "incorrect",
                    },
                ),
                Action(
                    "inspect_return",
                    {"order_id": order_id, "code": task.return_code if value % 2 else "incorrect"},
                ),
                Action(
                    "issue_refund",
                    {
                        "order_id": order_id,
                        "amount_cents": value,
                        "idempotency_key": f"key-{value % 4}",
                    },
                ),
                Action("cancel_order", {"order_id": order_id}),
                Action(
                    "reserve_stock",
                    {
                        "sku": [task.replacement_sku, old_sku, "unknown"][value % 3],
                        "quantity": value,
                    },
                ),
                Action("release_stock", {"reservation_id": f"r{value % 8}"}),
                Action(
                    "create_replacement", {"order_id": order_id, "reservation_id": f"r{value % 8}"}
                ),
                Action(
                    "close_case",
                    {
                        "order_id": order_id,
                        "resolution": ["refund", "cancel", "exchange", "unknown"][value % 4],
                    },
                ),
                Action("set_order_note", {"order_id": order_id, "note": f"note-{value}"}),
                Action("unknown-tool", {}),
            ]
            action = actions[operation]
            expected_state, expected_result = reduce_action(task, env.snapshot(), action)
            actual_result = env.execute(action)
            assert actual_result["ok"] is expected_result["ok"]
            if actual_result["ok"]:
                assert canonical_json(actual_result) == canonical_json(expected_result)
            assert env.snapshot() == expected_state
        assert replay(task, env.episode()).passed
