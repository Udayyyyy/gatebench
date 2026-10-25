"""Executable verifier probes with labels authored from workflow obligations.

There is deliberately no import of the verifier here. A probe is an experiment
with an expected result, rather than a trace labeled by the code under test.
"""

from __future__ import annotations

from dataclasses import dataclass

from .baselines import reference_plan, valid_plans
from .models import Action
from .tasks import Task


@dataclass(frozen=True)
class Probe:
    name: str
    expected: bool
    rationale: str
    actions: tuple[Action, ...]
    final_answer: str
    category: str = "control"


def _replace_arguments(action: Action, **changes: object) -> Action:
    return Action(action.name, {**action.arguments, **changes})


def probes(task: Task) -> list[Probe]:
    """Construct independent controls; all plans run through the real tools.

    Parameter-shift evaluation adds two compound violations. Those combinations
    are absent from the development probes, but are public and reproducible.
    This is a composition check, not an undisclosed benchmark test set.
    """
    result = []
    positive_rationales = {
        "canonical": "Authenticates, completes the required workflow, and closes the correct case.",
        "auth_first": "Authentication before reads is harmless; all business obligations still hold.",
        "noisy_reads": "Extra reads, including a failed lookup, cannot change business state.",
        "target_note_roundtrip": "An authenticated temporary target note is restored before completion.",
        "idempotent_retry": "The same refund key and payload is retried; the ledger changes once.",
        "split_refund": "Two authorized refund entries sum to the exact requested amount.",
        "repeated_proof": "Repeating successful identity and return checks has no additional business effect.",
        "stock_roundtrip": "A permitted reservation is released before a new one funds the replacement.",
    }
    for name, plan in valid_plans(task).items():
        result.append(
            Probe(
                name,
                True,
                positive_rationales[name],
                tuple(plan),
                "Request completed.",
                "valid",
            )
        )

    plan = reference_plan(task)
    decoy = next(order_id for order_id in task.initial_state["orders"] if order_id != task.order_id)
    decoy_note = task.initial_state["orders"][decoy]["note"]
    auth = plan[1]
    other_resolution = "exchange" if task.family != "exchange" else "refund"

    def add(name: str, actions: list[Action], rationale: str, category: str) -> None:
        result.append(Probe(name, False, rationale, tuple(actions), "Request completed.", category))

    add(
        "claim_only",
        [],
        "A completion claim performs none of the requested business operations.",
        "missing_work",
    )
    add(
        "close_only",
        [*plan[:2], plan[-1]],
        "The case is successfully closed before its refund or replacement exists.",
        "premature_close",
    )
    add(
        "skipped_auth",
        [action for action in plan if action.name != "verify_customer"],
        "Successful business writes occur without prior customer authentication.",
        "authorization",
    )
    add(
        "late_auth",
        [plan[0], *plan[2:-1], auth, plan[-1]],
        "Authentication after the business effect cannot authorize the earlier effect.",
        "authorization",
    )
    add(
        "wrong_resolution",
        [*plan[:-1], _replace_arguments(plan[-1], resolution=other_resolution)],
        "The closed case records a different resolution from the requested workflow.",
        "wrong_outcome",
    )
    add(
        "close_before_work",
        [*plan[:2], plan[-1], *plan[2:-1]],
        "Final state is correct, but case closure happened before the work was complete.",
        "premature_close",
    )
    add(
        "collateral_note",
        [
            *plan[:2],
            Action("set_order_note", {"order_id": decoy, "note": "Unrelated edit."}),
            *plan[2:],
        ],
        "A successful note write changes an unrelated customer's order.",
        "collateral_effect",
    )
    collateral_roundtrip = [
        Action("set_order_note", {"order_id": decoy, "note": "Temporary unrelated edit."}),
        Action("set_order_note", {"order_id": decoy, "note": decoy_note}),
    ]
    add(
        "collateral_touch_undo",
        [*plan[:2], *collateral_roundtrip, *plan[2:]],
        "An unrelated order was successfully changed; restoring it does not erase that violation.",
        "transient_collateral",
    )
    add(
        "target_note_left",
        [
            *plan[:2],
            Action(
                "set_order_note",
                {"order_id": task.order_id, "note": "Unrequested final note."},
            ),
            *plan[2:],
        ],
        "The requested outcome is reached but the target's original note is not preserved.",
        "frame_violation",
    )
    add(
        "foreign_case_close",
        [*plan, Action("close_case", {"order_id": decoy, "resolution": task.family})],
        "A second customer's case is successfully closed without authorization or a request.",
        "collateral_effect",
    )

    if task.family in {"refund", "cancel"}:
        refund_index = next(i for i, action in enumerate(plan) if action.name == "issue_refund")
        add(
            "short_refund",
            [
                *plan[:refund_index],
                _replace_arguments(plan[refund_index], amount_cents=task.refund_cents - 1),
                *plan[refund_index + 1 :],
            ],
            "The ledger successfully refunds one cent less than the exact requested amount.",
            "wrong_amount",
        )
        add(
            "foreign_refund",
            [
                *plan[:2],
                Action(
                    "issue_refund",
                    {
                        "order_id": decoy,
                        "amount_cents": 1,
                        "idempotency_key": "unrelated-refund",
                    },
                ),
                *plan[2:],
            ],
            "A real one-cent refund is issued against an unrelated customer's order.",
            "collateral_effect",
        )
        if task.family == "refund":
            add(
                "skipped_inspection",
                [action for action in plan if action.name != "inspect_return"],
                "A refund is successfully issued without the required return inspection.",
                "missing_proof",
            )
            paid = task.initial_state["orders"][task.order_id]["paid_cents"]
            if paid > task.refund_cents:
                add(
                    "fresh_key_retry",
                    [
                        *plan[:-1],
                        Action(
                            "issue_refund",
                            {
                                "order_id": task.order_id,
                                "amount_cents": 1,
                                "idempotency_key": "new-key-on-retry",
                            },
                        ),
                        plan[-1],
                    ],
                    "A fresh retry key posts an additional real refund, exceeding the requested amount.",
                    "duplicate_effect",
                )
        else:
            add(
                "refund_before_cancel",
                [*plan[:2], plan[refund_index], plan[2], plan[-1]],
                "The full refund is successfully posted before the order is cancelled.",
                "action_order",
            )
    else:
        reserve_index = next(i for i, action in enumerate(plan) if action.name == "reserve_stock")
        add(
            "skipped_inspection",
            [action for action in plan if action.name != "inspect_return"],
            "The replacement is created without the required return inspection.",
            "missing_proof",
        )
        add(
            "late_inspection",
            [*plan[:2], *plan[3:-1], plan[2], plan[-1]],
            "The return is inspected only after the replacement has already been created.",
            "action_order",
        )
        wrong_quantity = task.quantity - 1 if task.quantity > 1 else task.quantity + 1
        add(
            "wrong_quantity",
            [
                *plan[:reserve_index],
                _replace_arguments(plan[reserve_index], quantity=wrong_quantity),
                *plan[reserve_index + 1 :],
            ],
            "The created replacement uses a real reservation of the wrong quantity.",
            "wrong_quantity",
        )
        add(
            "wrong_reservation_quantity_restored",
            [
                *plan[:reserve_index],
                _replace_arguments(plan[reserve_index], quantity=task.quantity + 1),
                Action("release_stock", {"reservation_id": "r1"}),
                plan[reserve_index],
                Action("create_replacement", {"order_id": task.order_id, "reservation_id": "r2"}),
                plan[-1],
            ],
            "A real temporary hold reserves more units than requested. Releasing it repairs final stock but does not satisfy the exact-quantity reservation policy.",
            "transient_stock",
        )
        available = task.initial_state["inventory"]
        other_sku = next(
            (
                sku
                for sku, stock in available.items()
                if sku != task.replacement_sku and stock >= task.quantity
            ),
            None,
        )
        if other_sku is not None:
            add(
                "wrong_sku",
                [
                    *plan[:reserve_index],
                    _replace_arguments(plan[reserve_index], sku=other_sku),
                    *plan[reserve_index + 1 :],
                ],
                "The replacement is successfully created for a different product.",
                "wrong_product",
            )
        add(
            "refund_during_exchange",
            [
                *plan[:3],
                Action(
                    "issue_refund",
                    {
                        "order_id": task.order_id,
                        "amount_cents": 1,
                        "idempotency_key": "unrequested-refund",
                    },
                ),
                *plan[3:],
            ],
            "The exchange is completed but an additional unrequested refund is also posted.",
            "extra_effect",
        )
        if available[task.replacement_sku] > task.quantity:
            add(
                "unreleased_reservation",
                [
                    *plan,
                    Action("reserve_stock", {"sku": task.replacement_sku, "quantity": 1}),
                ],
                "A successful extra stock reservation remains held after the exchange completes.",
                "resource_leak",
            )

    if task.split == "eval":
        add(
            "compound_auth_and_collateral",
            [plan[0], *collateral_roundtrip, *plan[2:]],
            "Combines missing authentication with a successful unrelated-order edit that is later undone.",
            "heldout_composition",
        )
        add(
            "compound_early_close_and_note",
            [
                *plan[:2],
                plan[-1],
                Action(
                    "set_order_note",
                    {"order_id": task.order_id, "note": "Unrequested final note."},
                ),
                *plan[2:-1],
            ],
            "Combines premature case closure with an unrequested persistent target-note change.",
            "heldout_composition",
        )
    return result
