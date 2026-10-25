"""Scripted positive controls, not learned agents or performance baselines."""

from __future__ import annotations

from .models import Action
from .tasks import Task


def _authenticate(task: Task) -> Action:
    return Action("verify_customer", {"customer_id": task.customer_id, "code": task.auth_code})


def reference_plan(task: Task) -> list[Action]:
    """One straightforward witness that the generated task is solvable."""
    plan = [Action("get_order", {"order_id": task.order_id}), _authenticate(task)]
    if task.family in {"refund", "exchange"}:
        plan.append(Action("inspect_return", {"order_id": task.order_id, "code": task.return_code}))
    if task.family == "cancel":
        plan.append(Action("cancel_order", {"order_id": task.order_id}))
    if task.family in {"refund", "cancel"}:
        plan.append(
            Action(
                "issue_refund",
                {
                    "order_id": task.order_id,
                    "amount_cents": task.refund_cents,
                    "idempotency_key": f"refund-{task.id}",
                },
            )
        )
    else:
        plan.extend(
            [
                Action(
                    "reserve_stock",
                    {"sku": task.replacement_sku, "quantity": task.quantity},
                ),
                Action(
                    "create_replacement",
                    {"order_id": task.order_id, "reservation_id": "r1"},
                ),
            ]
        )
    plan.append(Action("close_case", {"order_id": task.order_id, "resolution": task.family}))
    return plan


def valid_plans(task: Task) -> dict[str, list[Action]]:
    """Equivalent plans expose the false negatives of exact-plan matching.

    These variants are written from the workflow contract. They do not consult
    the verifier to decide whether a plan belongs in the positive controls.
    """
    canonical = reference_plan(task)
    auth_first = [canonical[1], canonical[0], *canonical[2:]]
    noisy_reads = [
        Action("get_order", {"order_id": "nonexistent-order"}),
        *canonical[:2],
        Action("get_order", {"order_id": task.order_id}),
        Action("get_inventory", {"sku": task.replacement_sku}),
        *canonical[2:],
    ]
    target_note_roundtrip = [
        *canonical[:2],
        Action(
            "set_order_note",
            {"order_id": task.order_id, "note": "Checking the request."},
        ),
        Action(
            "set_order_note",
            {
                "order_id": task.order_id,
                "note": task.initial_state["orders"][task.order_id]["note"],
            },
        ),
        *canonical[2:],
    ]
    plans = {
        "canonical": canonical,
        "auth_first": auth_first,
        "noisy_reads": noisy_reads,
        "target_note_roundtrip": target_note_roundtrip,
    }

    if task.family in {"refund", "cancel"}:
        refund_index = next(
            i for i, action in enumerate(canonical) if action.name == "issue_refund"
        )
        refund = canonical[refund_index]
        plans["idempotent_retry"] = [
            *canonical[: refund_index + 1],
            refund,
            *canonical[refund_index + 1 :],
        ]
        first_part = task.refund_cents // 2
        plans["split_refund"] = [
            *canonical[:refund_index],
            Action(
                "issue_refund",
                {
                    "order_id": task.order_id,
                    "amount_cents": first_part,
                    "idempotency_key": "part-1",
                },
            ),
            Action(
                "issue_refund",
                {
                    "order_id": task.order_id,
                    "amount_cents": task.refund_cents - first_part,
                    "idempotency_key": "part-2",
                },
            ),
            *canonical[refund_index + 1 :],
        ]
    else:
        # Rechecking evidence changes the trace, not the evidence or outcome.
        plans["repeated_proof"] = [
            *canonical[:3],
            canonical[1],
            canonical[2],
            *canonical[3:],
        ]
        reserve_index = next(
            i for i, action in enumerate(canonical) if action.name == "reserve_stock"
        )
        plans["stock_roundtrip"] = [
            *canonical[: reserve_index + 1],
            Action("release_stock", {"reservation_id": "r1"}),
            canonical[reserve_index],
            Action(
                "create_replacement",
                {"order_id": task.order_id, "reservation_id": "r2"},
            ),
            canonical[-1],
        ]
    return plans
