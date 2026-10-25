"""A transactional tool backend. Each episode owns a fresh SQLite connection."""

from __future__ import annotations

import copy
import sqlite3
from typing import Any

from gatebench.models import Action, Episode, Event, digest
from gatebench.tasks import Task
from gatebench.tooling import TOOL_SCHEMAS, validate_action

__all__ = ["Environment", "TOOL_SCHEMAS"]

_SCHEMA = """
CREATE TABLE orders (
 id TEXT PRIMARY KEY, customer_id TEXT, status TEXT, sku TEXT, quantity INTEGER,
 unit_price_cents INTEGER, paid_cents INTEGER, refunded_cents INTEGER, note TEXT);
CREATE TABLE inventory (sku TEXT PRIMARY KEY, available INTEGER CHECK(available >= 0));
CREATE TABLE refunds (
 refund_id TEXT PRIMARY KEY, order_id TEXT, amount_cents INTEGER CHECK(amount_cents > 0),
 idempotency_key TEXT UNIQUE);
CREATE TABLE reservations (id TEXT PRIMARY KEY, sku TEXT, quantity INTEGER, status TEXT);
CREATE TABLE replacements (
 replacement_id TEXT PRIMARY KEY, order_id TEXT, sku TEXT, quantity INTEGER);
CREATE TABLE cases (order_id TEXT PRIMARY KEY, status TEXT, resolution TEXT);
CREATE TABLE verified_customers (id TEXT PRIMARY KEY);
CREATE TABLE inspected_orders (id TEXT PRIMARY KEY);
"""


class ToolError(Exception):
    pass


class Environment:
    def __init__(self, task: Task):
        self.task = task
        self._db = sqlite3.connect(":memory:")
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self.events: list[Event] = []
        state = copy.deepcopy(task.initial_state)
        with self._db:
            for oid, order in state["orders"].items():
                fields = (
                    "customer_id",
                    "status",
                    "sku",
                    "quantity",
                    "unit_price_cents",
                    "paid_cents",
                    "refunded_cents",
                    "note",
                )
                self._db.execute(
                    "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                    (oid, *(order[k] for k in fields)),
                )
            self._db.executemany("INSERT INTO inventory VALUES (?,?)", state["inventory"].items())
            for row in state["refunds"]:
                self._db.execute(
                    "INSERT INTO refunds VALUES (?,?,?,?)",
                    tuple(
                        row[k] for k in ("refund_id", "order_id", "amount_cents", "idempotency_key")
                    ),
                )
            for rid, row in state["reservations"].items():
                self._db.execute(
                    "INSERT INTO reservations VALUES (?,?,?,?)",
                    (rid, *(row[k] for k in ("sku", "quantity", "status"))),
                )
            for row in state["replacements"]:
                self._db.execute(
                    "INSERT INTO replacements VALUES (?,?,?,?)",
                    tuple(row[k] for k in ("replacement_id", "order_id", "sku", "quantity")),
                )
            for oid, row in state["cases"].items():
                self._db.execute(
                    "INSERT INTO cases VALUES (?,?,?)", (oid, row["status"], row["resolution"])
                )
            for table in ("verified_customers", "inspected_orders"):
                self._db.executemany(
                    f"INSERT INTO {table} VALUES (?)", [(x,) for x in state[table]]
                )
        self._initial = self.snapshot()

    def __enter__(self) -> Environment:
        return self

    def __exit__(self, *args: Any) -> None:
        self._db.close()

    def snapshot(self) -> dict[str, Any]:
        def keyed(table: str, key: str) -> dict[str, Any]:
            rows = [dict(r) for r in self._db.execute(f"SELECT * FROM {table} ORDER BY {key}")]
            return {row.pop(key): row for row in rows}

        return {
            "orders": keyed("orders", "id"),
            "inventory": {
                r[0]: r[1] for r in self._db.execute("SELECT * FROM inventory ORDER BY sku")
            },
            "refunds": [
                dict(r) for r in self._db.execute("SELECT * FROM refunds ORDER BY refund_id")
            ],
            "reservations": keyed("reservations", "id"),
            "replacements": [
                dict(r)
                for r in self._db.execute("SELECT * FROM replacements ORDER BY replacement_id")
            ],
            "cases": keyed("cases", "order_id"),
            "verified_customers": [
                r[0] for r in self._db.execute("SELECT id FROM verified_customers ORDER BY id")
            ],
            "inspected_orders": [
                r[0] for r in self._db.execute("SELECT id FROM inspected_orders ORDER BY id")
            ],
        }

    def execute(self, action: Action) -> dict[str, Any]:
        # Callers cannot mutate recorded evidence by retaining an arguments dict.
        action = copy.deepcopy(action)
        before = digest(self.snapshot())
        error = validate_action(action)
        if error:
            result = {"ok": False, "error": error}
        else:
            try:
                with self._db:
                    result = self._apply(action.name, action.arguments)
            except ToolError as exc:
                result = {"ok": False, "error": str(exc)}
            except sqlite3.IntegrityError:
                result = {"ok": False, "error": "database constraint rejected the call"}
        self.events.append(
            Event(len(self.events), action, copy.deepcopy(result), before, digest(self.snapshot()))
        )
        return copy.deepcopy(result)

    def episode(self, final_answer: str = "", stop_reason: str = "completed") -> Episode:
        return Episode(
            self.task.id,
            copy.deepcopy(self._initial),
            self.snapshot(),
            tuple(copy.deepcopy(self.events)),
            final_answer,
            stop_reason,
        )

    def _order(self, order_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise ToolError("unknown order")
        order = dict(row)
        del order["id"]
        return order

    def _reservation(self, reservation_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT * FROM reservations WHERE id=?", (reservation_id,)
        ).fetchone()
        if row is None or row["status"] != "held":
            raise ToolError("reservation is not held")
        return dict(row)

    def _next(self, table: str, prefix: str) -> str:
        count = self._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return f"{prefix}{count + 1}"

    def _apply(self, name: str, a: dict[str, Any]) -> dict[str, Any]:
        if "order_id" in a:
            order = self._order(a["order_id"])
        if name == "get_order":
            return {"ok": True, "order": order}
        if name == "get_inventory":
            row = self._db.execute(
                "SELECT available FROM inventory WHERE sku=?", (a["sku"],)
            ).fetchone()
            if row is None:
                raise ToolError("unknown SKU")
            return {"ok": True, "sku": a["sku"], "available": row[0]}
        if name == "verify_customer":
            if a["customer_id"] != self.task.customer_id or a["code"] != self.task.auth_code:
                raise ToolError("verification failed")
            self._db.execute(
                "INSERT OR IGNORE INTO verified_customers VALUES (?)", (a["customer_id"],)
            )
            return {"ok": True, "verified": a["customer_id"]}
        if name == "inspect_return":
            if a["order_id"] != self.task.order_id or a["code"] != self.task.return_code:
                raise ToolError("inspection code rejected")
            self._db.execute("INSERT OR IGNORE INTO inspected_orders VALUES (?)", (a["order_id"],))
            return {"ok": True, "inspected": a["order_id"]}
        if name == "issue_refund":
            prior = self._db.execute(
                "SELECT * FROM refunds WHERE idempotency_key=?", (a["idempotency_key"],)
            ).fetchone()
            if prior:
                if prior["order_id"] != a["order_id"] or prior["amount_cents"] != a["amount_cents"]:
                    raise ToolError("idempotency key payload mismatch")
                return {"ok": True, "refund_id": prior["refund_id"], "reused": True}
            if a["amount_cents"] > order["paid_cents"] - order["refunded_cents"]:
                raise ToolError("refund exceeds remaining payment")
            fid = self._next("refunds", "f")
            self._db.execute(
                "INSERT INTO refunds VALUES (?,?,?,?)",
                (fid, a["order_id"], a["amount_cents"], a["idempotency_key"]),
            )
            self._db.execute(
                "UPDATE orders SET refunded_cents=refunded_cents+? WHERE id=?",
                (a["amount_cents"], a["order_id"]),
            )
            return {"ok": True, "refund_id": fid, "reused": False}
        if name == "cancel_order":
            self._db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (a["order_id"],))
            return {"ok": True, "status": "cancelled"}
        if name == "reserve_stock":
            row = self._db.execute(
                "SELECT available FROM inventory WHERE sku=?", (a["sku"],)
            ).fetchone()
            if row is None or row[0] < a["quantity"]:
                raise ToolError("insufficient stock or unknown SKU")
            rid = self._next("reservations", "r")
            self._db.execute(
                "UPDATE inventory SET available=available-? WHERE sku=?", (a["quantity"], a["sku"])
            )
            self._db.execute(
                "INSERT INTO reservations VALUES (?,?,?,'held')", (rid, a["sku"], a["quantity"])
            )
            return {"ok": True, "reservation_id": rid}
        if name == "release_stock":
            held = self._reservation(a["reservation_id"])
            self._db.execute(
                "UPDATE inventory SET available=available+? WHERE sku=?",
                (held["quantity"], held["sku"]),
            )
            self._db.execute(
                "UPDATE reservations SET status='released' WHERE id=?", (a["reservation_id"],)
            )
            return {"ok": True, "status": "released"}
        if name == "create_replacement":
            held = self._reservation(a["reservation_id"])
            xid = self._next("replacements", "x")
            self._db.execute(
                "INSERT INTO replacements VALUES (?,?,?,?)",
                (xid, a["order_id"], held["sku"], held["quantity"]),
            )
            self._db.execute(
                "UPDATE reservations SET status='consumed' WHERE id=?", (a["reservation_id"],)
            )
            self._db.execute("UPDATE orders SET status='exchanged' WHERE id=?", (a["order_id"],))
            return {"ok": True, "replacement_id": xid}
        if name == "close_case":
            self._db.execute(
                "UPDATE cases SET status='closed',resolution=? WHERE order_id=?",
                (a["resolution"], a["order_id"]),
            )
            return {"ok": True, "status": "closed"}
        if name == "set_order_note":
            self._db.execute("UPDATE orders SET note=? WHERE id=?", (a["note"], a["order_id"]))
            return {"ok": True}
        raise ToolError("unknown tool")
