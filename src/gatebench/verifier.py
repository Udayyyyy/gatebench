"""Business-obligation verifier, independent of reference plans and probe labels."""

from __future__ import annotations

from copy import deepcopy

from .models import Episode, Verdict
from .replay import evidence_errors, reduce_action, replay, state_errors
from .tasks import Task


def _prerequisites(task: Task, state: dict) -> bool:
    order = state["orders"].get(task.order_id)
    if order is None or any(r["status"] == "held" for r in state["reservations"].values()):
        return False
    initial = task.initial_state["orders"][task.order_id]
    refunds = [r for r in state["refunds"] if r["order_id"] == task.order_id]
    replacements = [r for r in state["replacements"] if r["order_id"] == task.order_id]
    delta = order["refunded_cents"] - initial["refunded_cents"]
    if task.family in ("refund", "cancel"):
        expected_status = "cancelled" if task.family == "cancel" else "delivered"
        return (
            order["status"] == expected_status
            and delta == task.refund_cents
            and sum(r["amount_cents"] for r in refunds) == task.refund_cents
            and not replacements
        )
    return (
        task.family == "exchange"
        and order["status"] == "exchanged"
        and delta == 0
        and not refunds
        and len(replacements) == 1
        and replacements[0]["sku"] == task.replacement_sku
        and replacements[0]["quantity"] == task.quantity
    )


def goal_satisfied(task: Task, state: dict) -> bool:
    try:
        if state_errors(state, "state"):
            return False
        return _prerequisites(task, state) and state["cases"].get(task.order_id) == {
            "status": "closed",
            "resolution": task.family,
        }
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _frame_errors(task: Task, final: dict) -> list[str]:
    errors = []
    initial = task.initial_state
    target = task.order_id
    if set(final["orders"]) != set(initial["orders"]) or set(final["cases"]) != set(
        initial["cases"]
    ):
        errors.append("frame.records: original order/case IDs changed")
    for oid, order in initial["orders"].items():
        if oid != target:
            if (
                final["orders"].get(oid) != order
                or final["cases"].get(oid) != initial["cases"][oid]
            ):
                errors.append("frame.collateral: non-target order or case changed")
        else:
            target_final = final["orders"].get(oid, {})
            if any(
                target_final.get(k) != v
                for k, v in order.items()
                if k not in ("status", "refunded_cents")
            ):
                errors.append("frame.target: immutable target fields changed")
    if any(row["order_id"] != target for row in final["refunds"]):
        errors.append("frame.refunds: non-target refund")
    expected_sum = 0 if task.family == "exchange" else task.refund_cents
    if sum(row["amount_cents"] for row in final["refunds"]) != expected_sum:
        errors.append("frame.refunds: unexpected total")
    if any(row["order_id"] != target for row in final["replacements"]):
        errors.append("frame.replacements: non-target replacement")
    expected_inventory = deepcopy(initial["inventory"])
    if task.family == "exchange":
        expected_inventory[task.replacement_sku] -= task.quantity
    if final["inventory"] != expected_inventory:
        errors.append("frame.inventory: unexpected stock change")
    if any(row["status"] == "held" for row in final["reservations"].values()):
        errors.append("frame.reservations: live reservation remains")
    consumed = [row for row in final["reservations"].values() if row["status"] == "consumed"]
    if task.family == "exchange":
        if (
            len(consumed) != 1
            or consumed[0]["sku"] != task.replacement_sku
            or consumed[0]["quantity"] != task.quantity
        ):
            errors.append("frame.reservations: unexpected consumed stock")
    elif consumed:
        errors.append("frame.reservations: unexpected consumed stock")
    if any(customer != task.customer_id for customer in final["verified_customers"]):
        errors.append("frame.verification: foreign customer verified")
    if any(oid != target for oid in final["inspected_orders"]):
        errors.append("frame.inspection: foreign order inspected")
    return errors


def _history_errors(task: Task, episode: Episode) -> list[str]:
    errors = []
    prefix = deepcopy(task.initial_state)
    verified = False
    inspected = False
    business_tools = {
        "issue_refund",
        "cancel_order",
        "reserve_stock",
        "release_stock",
        "create_replacement",
        "close_case",
        "set_order_note",
    }
    for event in episode.events:
        if event.result.get("ok") is not True:
            continue
        name, args = event.action.name, event.action.arguments
        marker = f"history.event[{event.seq}]"
        if name == "verify_customer":
            if args.get("customer_id") == task.customer_id and args.get("code") == task.auth_code:
                verified = True
        elif name == "inspect_return":
            if not verified:
                errors.append(f"{marker}.inspection: verification must precede inspection")
            if args.get("order_id") != task.order_id:
                errors.append(f"{marker}.inspection: wrong order")
            if args.get("order_id") == task.order_id and args.get("code") == task.return_code:
                inspected = True
        elif name in business_tools:
            # A reused refund is a successful, explicitly documented no-op.
            retry = name == "issue_refund" and event.result.get("reused") is True
            try:
                updated, _ = reduce_action(task, prefix, event.action)
                effectful = updated != prefix
            except (AttributeError, KeyError, TypeError, ValueError):
                updated, effectful = prefix, True
            if not retry and effectful:
                if not verified:
                    errors.append(f"{marker}.authentication: write preceded verification")
                if name == "issue_refund":
                    if args.get("order_id") != task.order_id or task.family not in (
                        "refund",
                        "cancel",
                    ):
                        errors.append(f"{marker}.refund: wrong target/family")
                    if task.family == "refund" and not inspected:
                        errors.append(f"{marker}.refund: inspection must precede refund")
                    if (
                        task.family == "cancel"
                        and prefix["orders"][task.order_id]["status"] != "cancelled"
                    ):
                        errors.append(f"{marker}.refund: cancellation must precede refund")
                elif name == "cancel_order":
                    if (
                        task.family != "cancel"
                        or args.get("order_id") != task.order_id
                        or task.initial_state["orders"][task.order_id]["status"] != "processing"
                    ):
                        errors.append(f"{marker}.cancellation: forbidden target/family/status")
                elif name == "create_replacement":
                    reservation = prefix["reservations"].get(args.get("reservation_id"), {})
                    if (
                        task.family != "exchange"
                        or args.get("order_id") != task.order_id
                        or not inspected
                        or reservation.get("sku") != task.replacement_sku
                        or reservation.get("quantity") != task.quantity
                    ):
                        errors.append(
                            f"{marker}.replacement: invalid target, inspection, or reservation"
                        )
                elif name == "close_case":
                    if (
                        args.get("order_id") != task.order_id
                        or args.get("resolution") != task.family
                        or not _prerequisites(task, prefix)
                    ):
                        errors.append(f"{marker}.closure: prerequisites were not satisfied")
                elif name == "set_order_note":
                    if args.get("order_id") != task.order_id:
                        errors.append(f"{marker}.collateral: non-target note write")
                elif name in ("reserve_stock", "release_stock"):
                    sku = (
                        args.get("sku")
                        if name == "reserve_stock"
                        else prefix["reservations"].get(args.get("reservation_id"), {}).get("sku")
                    )
                    if task.family != "exchange" or sku != task.replacement_sku:
                        errors.append(f"{marker}.stock: forbidden stock write")
                    if name == "reserve_stock" and args.get("quantity") != task.quantity:
                        errors.append(f"{marker}.stock: reserved quantity differs from request")
            prefix = updated
            continue
        try:
            prefix, _ = reduce_action(task, prefix, event.action)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass  # Evidence consistency is the separate replay obligation.
    return errors


def verify(
    task: Task,
    episode: Episode,
    *,
    check_history: bool = True,
    check_frame: bool = True,
    check_replay: bool = True,
) -> Verdict:
    errors = evidence_errors(task, episode)
    if errors:
        return Verdict(False, tuple(errors))
    if not goal_satisfied(task, episode.final_state):
        errors.append("goal: requested resolution was not achieved")
    try:
        if check_frame:
            errors.extend(_frame_errors(task, episode.final_state))
        if check_history:
            errors.extend(_history_errors(task, episode))
    except (AttributeError, KeyError, TypeError, ValueError):
        errors.append("evidence: malformed business evidence")
    if check_replay:
        errors.extend(replay(task, episode).reasons)
    errors = list(dict.fromkeys(errors))
    return Verdict(not errors, tuple(errors))
