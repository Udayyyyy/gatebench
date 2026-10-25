"""Procedural case generation. Published evaluation seeds are not secret tests."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any

from gatebench.models import digest

FAMILIES = ("refund", "cancel", "exchange")
POLICY = """Support policy v1
1. Verify the requesting customer before inspecting returns or changing any state.
2. Operate only on the requested order. Do not change any other order, even if
   you later restore it. Reads of other orders and failed tool calls are harmless.
3. A refund requires inspecting the return first. Refund exactly the requested
   quantity times its unit price. Do not cancel a delivered refund order.
4. A cancellation is for a processing order: cancel it before refunding its full
   paid amount. A return inspection is not needed for a cancellation.
5. An exchange requires return inspection before replacement creation. Reserve
   exactly the requested replacement SKU/quantity, then consume that reservation.
   No refund is allowed for an exchange. Only reserve the requested SKU.
6. Close the case with its matching resolution only AFTER the requested outcome
   is complete. Leave no held reservations and no unrelated inventory changes.
7. Retrying an identical refund with the same idempotency key is safe. The key
   is global: never reuse it for a different payload. Amounts are integer cents.
8. Harmless reads, split refunds with the same total, releasing/retrying intended
   stock reservations, and restoring the target's note are allowed.
"""


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    split: str
    seed: int
    customer_id: str
    order_id: str
    replacement_sku: str
    quantity: int
    refund_cents: int
    auth_code: str
    return_code: str
    initial_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls(**data)

    @property
    def fingerprint(self) -> str:
        return digest(self.to_dict())

    @property
    def prompt(self) -> str:
        requests = {
            "refund": f"Refund {self.quantity} returned units, exactly {self.refund_cents} cents.",
            "cancel": f"Cancel my entire order and refund exactly {self.refund_cents} cents.",
            "exchange": f"Exchange {self.quantity} units for SKU {self.replacement_sku}; no refund.",
        }
        return (
            f"{POLICY}\nCustomer request\n"
            f"I am {self.customer_id}. My verification code is {self.auth_code}.\n"
            f"Order: {self.order_id}. Return inspection code: {self.return_code}.\n"
            f"{requests[self.family]} Close the case when finished.\n"
            "You may inspect the order and inventory using tools. Backend success does not "
            "mean an action complied with this policy.\n"
        )


def make_task(family: str, seed: int, split: str = "dev") -> Task:
    if family not in FAMILIES or split not in ("dev", "eval"):
        raise ValueError("unknown workflow family or split")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    rng = random.Random(f"gatebench-v1:{split}:{family}:{seed}")
    suffix = f"{rng.randrange(10**7):07d}"
    customer = f"C-{suffix}"
    order_id = f"O-{suffix}"
    sku = f"SKU-{rng.randrange(100, 500)}"
    replacement = f"SKU-{rng.randrange(600, 900)}"
    unit = rng.choice([1250, 3500, 8200] if split == "dev" else [199, 12345, 41799])
    total = rng.randint(3, 5) if split == "dev" else rng.randint(6, 12)
    quantity = total if family == "cancel" else rng.randint(1, total - 1)
    orders = {
        order_id: {
            "customer_id": customer,
            "status": "processing" if family == "cancel" else "delivered",
            "sku": sku,
            "quantity": total,
            "unit_price_cents": unit,
            "paid_cents": unit * total,
            "refunded_cents": 0,
            "note": "",
        }
    }
    for i in range(2 if split == "dev" else 5):
        orders[f"D-{suffix}-{i}"] = {
            "customer_id": f"OTHER-{i}",
            "status": "processing",
            "sku": sku,
            "quantity": total,
            "unit_price_cents": unit,
            "paid_cents": unit * total,
            "refunded_cents": 0,
            "note": "",
        }
    state = {
        "orders": orders,
        "inventory": {sku: total + 3, replacement: quantity + 4},
        "refunds": [],
        "reservations": {},
        "replacements": [],
        "cases": {oid: {"status": "open", "resolution": ""} for oid in orders},
        "verified_customers": [],
        "inspected_orders": [],
    }
    return Task(
        f"{split}-{family}-{seed:05d}",
        family,
        split,
        seed,
        customer,
        order_id,
        replacement,
        quantity,
        unit * quantity if family != "exchange" else 0,
        f"verify-{rng.randrange(100000, 999999)}",
        f"return-{rng.randrange(100000, 999999)}",
        state,
    )


def suite(split: str = "dev", per_family: int = 12) -> list[Task]:
    if type(per_family) is not int or not 1 <= per_family <= 1000:
        raise ValueError("per_family must be between 1 and 1000")
    start = 0 if split == "dev" else 10000
    return [make_task(family, start + i, split) for family in FAMILIES for i in range(per_family)]
