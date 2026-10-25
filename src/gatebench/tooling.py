"""The public tool schema. Business policy is intentionally not enforced here."""

from __future__ import annotations

from typing import Any

from gatebench.models import Action

_TOOLS: dict[str, tuple[str, dict[str, str]]] = {
    "get_order": (
        "Read one order, including price, owner, and current status.",
        {"order_id": "string"},
    ),
    "get_inventory": ("Read available units of a catalog SKU.", {"sku": "string"}),
    "verify_customer": (
        "Verify a customer using their supplied code.",
        {"customer_id": "string", "code": "string"},
    ),
    "inspect_return": (
        "Record inspection using the supplied return code.",
        {"order_id": "string", "code": "string"},
    ),
    "issue_refund": (
        "Issue integer cents. Same key/payload is an idempotent retry.",
        {"order_id": "string", "amount_cents": "integer", "idempotency_key": "string"},
    ),
    "cancel_order": (
        "Set an order to cancelled. You must check policy first.",
        {"order_id": "string"},
    ),
    "reserve_stock": (
        "Hold stock and return its reservation_id.",
        {"sku": "string", "quantity": "integer"},
    ),
    "release_stock": (
        "Release a held reservation, returning its stock.",
        {"reservation_id": "string"},
    ),
    "create_replacement": (
        "Consume a held reservation to create a replacement.",
        {"order_id": "string", "reservation_id": "string"},
    ),
    "close_case": (
        "Close a case with refund, cancel, or exchange resolution.",
        {"order_id": "string", "resolution": "string"},
    ),
    "set_order_note": (
        "Update an order note. This is a write subject to policy.",
        {"order_id": "string", "note": "string"},
    ),
}

TOOL_SCHEMAS = [
    {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {key: {"type": kind} for key, kind in fields.items()},
            "required": list(fields),
            "additionalProperties": False,
        },
    }
    for name, (description, fields) in _TOOLS.items()
]


def validate_action(action: Action) -> str | None:
    if not isinstance(action.name, str) or action.name not in _TOOLS:
        return "unknown tool"
    if not isinstance(action.arguments, dict):
        return "arguments must be an object"
    fields = _TOOLS[action.name][1]
    if set(action.arguments) != set(fields):
        return "missing or unexpected argument"
    for key, kind in fields.items():
        value: Any = action.arguments[key]
        if kind == "integer":
            if type(value) is not int or not 1 <= value <= 1_000_000_000:
                return f"{key} must be a positive integer <= 1000000000"
        elif not isinstance(value, str) or len(value) > 1000 or (key != "note" and not value):
            return f"{key} must be a nonempty string of at most 1000 characters"
    if action.name == "close_case" and action.arguments["resolution"] not in (
        "refund",
        "cancel",
        "exchange",
    ):
        return "unknown resolution"
    return None
