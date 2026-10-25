"""Independent, pure-Python reconstruction of a recorded tool episode.

This module deliberately does not import the SQLite environment.  Replay proves
internal consistency of a journal, not the provenance of a coherent forgery.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from .models import Action, Episode, Verdict, digest
from .tasks import Task

STATE_KEYS = {
    "orders",
    "inventory",
    "refunds",
    "reservations",
    "replacements",
    "cases",
    "verified_customers",
    "inspected_orders",
}
ORDER_KEYS = {
    "customer_id",
    "status",
    "sku",
    "quantity",
    "unit_price_cents",
    "paid_cents",
    "refunded_cents",
    "note",
}


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _json_value(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return isfinite(value)
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_value(item) for key, item in value.items())
    return False


def state_errors(state: Any, label: str) -> list[str]:
    """Validate evidence before accessing it; bool is never a monetary value."""
    bad = f"evidence.{label}"
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        return [f"{bad}: invalid snapshot keys"]
    for name in ("orders", "inventory", "reservations", "cases"):
        if not isinstance(state[name], dict):
            return [f"{bad}: {name} must be a mapping"]
    for name in ("refunds", "replacements", "verified_customers", "inspected_orders"):
        if not isinstance(state[name], list):
            return [f"{bad}: {name} must be a list"]
    for oid, order in state["orders"].items():
        if not _string(oid) or not isinstance(order, dict) or set(order) != ORDER_KEYS:
            return [f"{bad}: malformed order"]
        if not all(_string(order[k]) for k in ("customer_id", "status", "sku")):
            return [f"{bad}: malformed order strings"]
        if not isinstance(order["note"], str):
            return [f"{bad}: malformed order note"]
        if not _integer(order["quantity"], 1) or not _integer(order["unit_price_cents"], 1):
            return [f"{bad}: malformed order quantity/price"]
        if not _integer(order["paid_cents"]) or not _integer(order["refunded_cents"]):
            return [f"{bad}: malformed order money"]
        if order["refunded_cents"] > order["paid_cents"]:
            return [f"{bad}: refund exceeds payment"]
    if any(not _string(sku) or not _integer(qty) for sku, qty in state["inventory"].items()):
        return [f"{bad}: malformed inventory"]
    if set(state["cases"]) != set(state["orders"]):
        return [f"{bad}: case/order IDs differ"]
    for case in state["cases"].values():
        if not isinstance(case, dict) or set(case) != {"status", "resolution"}:
            return [f"{bad}: malformed case"]
        if case["status"] not in ("open", "closed") or case["resolution"] not in (
            "",
            "refund",
            "cancel",
            "exchange",
        ):
            return [f"{bad}: invalid case values"]
    refund_ids, keys = set(), set()
    for row in state["refunds"]:
        if not isinstance(row, dict) or set(row) != {
            "refund_id",
            "order_id",
            "amount_cents",
            "idempotency_key",
        }:
            return [f"{bad}: malformed refund"]
        if not all(
            _string(row[k]) for k in ("refund_id", "order_id", "idempotency_key")
        ) or not _integer(row["amount_cents"], 1):
            return [f"{bad}: malformed refund values"]
        if (
            row["order_id"] not in state["orders"]
            or row["refund_id"] in refund_ids
            or row["idempotency_key"] in keys
        ):
            return [f"{bad}: invalid refund IDs"]
        refund_ids.add(row["refund_id"])
        keys.add(row["idempotency_key"])
    for rid, row in state["reservations"].items():
        if (
            not _string(rid)
            or not isinstance(row, dict)
            or set(row) != {"sku", "quantity", "status"}
        ):
            return [f"{bad}: malformed reservation"]
        if (
            row["sku"] not in state["inventory"]
            or not _integer(row["quantity"], 1)
            or row["status"] not in ("held", "released", "consumed")
        ):
            return [f"{bad}: invalid reservation values"]
    replacement_ids = set()
    for row in state["replacements"]:
        if not isinstance(row, dict) or set(row) != {
            "replacement_id",
            "order_id",
            "sku",
            "quantity",
        }:
            return [f"{bad}: malformed replacement"]
        if (
            not _string(row["replacement_id"])
            or row["replacement_id"] in replacement_ids
            or row["order_id"] not in state["orders"]
            or row["sku"] not in state["inventory"]
            or not _integer(row["quantity"], 1)
        ):
            return [f"{bad}: invalid replacement values"]
        replacement_ids.add(row["replacement_id"])
    for name, known in (
        ("verified_customers", {o["customer_id"] for o in state["orders"].values()}),
        ("inspected_orders", set(state["orders"])),
    ):
        values = state[name]
        if (
            not all(_string(v) for v in values)
            or len(set(values)) != len(values)
            or values != sorted(values)
        ):
            return [f"{bad}: malformed {name}"]
        if not set(values) <= known:
            return [f"{bad}: unknown {name}"]
    return []


def evidence_errors(task: Task, episode: Episode) -> list[str]:
    errors = []
    try:
        if not isinstance(episode.task_id, str) or episode.task_id != task.id:
            errors.append("evidence.task_id: does not match task")
        if episode.stop_reason != "completed":
            errors.append("evidence.stop_reason: episode did not complete")
        if not isinstance(episode.final_answer, str):
            errors.append("evidence.final_answer: must be text")
        errors.extend(state_errors(episode.initial_state, "initial_state"))
        errors.extend(state_errors(episode.final_state, "final_state"))
        if not errors and episode.initial_state != task.initial_state:
            errors.append("evidence.initial_state: does not match task")
        if not isinstance(episode.events, (tuple, list)):
            errors.append("evidence.events: must be a sequence")
            return errors
        if len(episode.events) > 1000:
            errors.append("evidence.events: exceeds 1000-event limit")
        for index, event in enumerate(episode.events):
            if type(event.seq) is not int or event.seq != index:
                errors.append(f"evidence.event[{index}]: invalid sequence")
            if not isinstance(event.action.name, str) or not isinstance(
                event.action.arguments, dict
            ):
                errors.append(f"evidence.event[{index}]: invalid action")
            elif not _json_value(event.action.arguments):
                errors.append(f"evidence.event[{index}]: non-JSON arguments")
            if not isinstance(event.result, dict) or type(event.result.get("ok")) is not bool:
                errors.append(f"evidence.event[{index}]: invalid result")
            elif event.result["ok"] is False and (
                set(event.result) != {"ok", "error"} or not isinstance(event.result["error"], str)
            ):
                errors.append(f"evidence.event[{index}]: invalid error result")
            elif not _json_value(event.result):
                errors.append(f"evidence.event[{index}]: non-JSON result")
            for name in ("before_hash", "after_hash"):
                value = getattr(event, name)
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)
                ):
                    errors.append(f"evidence.event[{index}]: invalid {name}")
    except (AttributeError, TypeError, ValueError):
        errors.append("evidence: malformed episode")
    return errors


def reduce_action(task: Task, state: dict, action: Action) -> tuple[dict, dict]:
    """Apply the tool's structural semantics without any business-policy check."""
    from .tooling import validate_action

    validation = validate_action(action)
    if validation:
        return deepcopy(state), {"ok": False, "error": str(validation)}
    updated = deepcopy(state)
    name, args = action.name, action.arguments
    orders = updated["orders"]

    def fail(message: str) -> tuple[dict, dict]:
        return deepcopy(state), {"ok": False, "error": message}

    if "order_id" in args and args["order_id"] not in orders:
        return fail("unknown order")
    if name == "get_order":
        result = {"ok": True, "order": deepcopy(orders[args["order_id"]])}
    elif name == "get_inventory":
        if args["sku"] not in updated["inventory"]:
            return fail("unknown SKU")
        result = {"ok": True, "sku": args["sku"], "available": updated["inventory"][args["sku"]]}
    elif name == "verify_customer":
        if args["customer_id"] != task.customer_id or args["code"] != task.auth_code:
            return fail("invalid verification")
        updated["verified_customers"] = sorted(
            set(updated["verified_customers"]) | {args["customer_id"]}
        )
        result = {"ok": True, "verified": args["customer_id"]}
    elif name == "inspect_return":
        if args["order_id"] != task.order_id or args["code"] != task.return_code:
            return fail("invalid return inspection")
        updated["inspected_orders"] = sorted(set(updated["inspected_orders"]) | {args["order_id"]})
        result = {"ok": True, "inspected": args["order_id"]}
    elif name == "issue_refund":
        for row in updated["refunds"]:
            if row["idempotency_key"] == args["idempotency_key"]:
                if (
                    row["order_id"] != args["order_id"]
                    or row["amount_cents"] != args["amount_cents"]
                ):
                    return fail("idempotency conflict")
                return updated, {"ok": True, "refund_id": row["refund_id"], "reused": True}
        order = orders[args["order_id"]]
        if args["amount_cents"] > order["paid_cents"] - order["refunded_cents"]:
            return fail("refund exceeds remaining payment")
        refund_id = f"f{len(updated['refunds']) + 1}"
        updated["refunds"].append({"refund_id": refund_id, **args})
        updated["refunds"].sort(key=lambda row: row["refund_id"])
        order["refunded_cents"] += args["amount_cents"]
        result = {"ok": True, "refund_id": refund_id, "reused": False}
    elif name == "cancel_order":
        orders[args["order_id"]]["status"] = "cancelled"
        result = {"ok": True, "status": "cancelled"}
    elif name == "reserve_stock":
        if args["sku"] not in updated["inventory"]:
            return fail("unknown SKU")
        if updated["inventory"][args["sku"]] < args["quantity"]:
            return fail("insufficient stock")
        reservation_id = f"r{len(updated['reservations']) + 1}"
        updated["inventory"][args["sku"]] -= args["quantity"]
        updated["reservations"][reservation_id] = {**args, "status": "held"}
        result = {"ok": True, "reservation_id": reservation_id}
    elif name == "release_stock":
        reservation = updated["reservations"].get(args["reservation_id"])
        if not reservation or reservation["status"] != "held":
            return fail("reservation is not held")
        reservation["status"] = "released"
        updated["inventory"][reservation["sku"]] += reservation["quantity"]
        result = {"ok": True, "status": "released"}
    elif name == "create_replacement":
        reservation = updated["reservations"].get(args["reservation_id"])
        if not reservation or reservation["status"] != "held":
            return fail("reservation is not held")
        replacement_id = f"x{len(updated['replacements']) + 1}"
        updated["replacements"].append(
            {
                "replacement_id": replacement_id,
                "order_id": args["order_id"],
                "sku": reservation["sku"],
                "quantity": reservation["quantity"],
            }
        )
        updated["replacements"].sort(key=lambda row: row["replacement_id"])
        reservation["status"] = "consumed"
        orders[args["order_id"]]["status"] = "exchanged"
        result = {"ok": True, "replacement_id": replacement_id}
    elif name == "close_case":
        updated["cases"][args["order_id"]] = {"status": "closed", "resolution": args["resolution"]}
        result = {"ok": True, "status": "closed"}
    elif name == "set_order_note":
        orders[args["order_id"]]["note"] = args["note"]
        result = {"ok": True}
    else:
        return fail("unknown tool")
    return updated, result


def replay(task: Task, episode: Episode) -> Verdict:
    errors = evidence_errors(task, episode)
    if errors:
        return Verdict(False, tuple(errors))
    state = deepcopy(task.initial_state)
    for index, event in enumerate(episode.events):
        if event.before_hash != digest(state):
            errors.append(f"replay.event[{index}]: before hash mismatch")
        try:
            updated, expected = reduce_action(task, state, event.action)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"replay.event[{index}]: invalid transition ({type(exc).__name__})")
            break
        if expected["ok"]:
            # Equality alone would accept 1 in place of True: compare JSON types too.
            if digest(event.result) != digest(expected):
                errors.append(f"replay.event[{index}]: result mismatch")
        elif event.result.get("ok") is not False:
            errors.append(f"replay.event[{index}]: expected failed call")
        if event.after_hash != digest(updated):
            errors.append(f"replay.event[{index}]: after hash mismatch")
        state = updated
    if digest(state) != digest(episode.final_state):
        errors.append("replay.final_state: reconstructed snapshot differs")
    return Verdict(not errors, tuple(errors))


replay_episode = replay
