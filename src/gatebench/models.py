"""The on-disk format is deliberately plain JSON, not pickled Python objects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class Action:
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Action:
        if set(data) != {"name", "arguments"}:
            raise ValueError("action requires only name and arguments")
        if not isinstance(data["name"], str) or not isinstance(data["arguments"], dict):
            raise ValueError("invalid action types")
        return cls(data["name"], data["arguments"])


@dataclass(frozen=True)
class Event:
    seq: int
    action: Action
    result: dict[str, Any]
    before_hash: str
    after_hash: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        if set(data) != {"seq", "action", "result", "before_hash", "after_hash"}:
            raise ValueError("invalid event fields")
        if type(data["seq"]) is not int or not isinstance(data["result"], dict):
            raise ValueError("invalid event types")
        for field in ("before_hash", "after_hash"):
            if not isinstance(data[field], str) or len(data[field]) != 64:
                raise ValueError("event hashes must be SHA-256 hex strings")
        return cls(
            data["seq"],
            Action.from_dict(data["action"]),
            data["result"],
            data["before_hash"],
            data["after_hash"],
        )


@dataclass(frozen=True)
class Episode:
    task_id: str
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    events: tuple[Event, ...]
    final_answer: str
    stop_reason: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "events": [e.to_dict() for e in self.events],
            "final_answer": self.final_answer,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Episode:
        fields = {
            "task_id",
            "initial_state",
            "final_state",
            "events",
            "final_answer",
            "stop_reason",
        }
        if set(data) != fields:
            raise ValueError("invalid episode fields")
        if not all(isinstance(data[k], str) for k in ("task_id", "final_answer", "stop_reason")):
            raise ValueError("invalid episode text fields")
        if not all(isinstance(data[k], dict) for k in ("initial_state", "final_state")):
            raise ValueError("episode states must be objects")
        if not isinstance(data["events"], list) or len(data["events"]) > 1000:
            raise ValueError("episode must contain at most 1000 events")
        return cls(
            data["task_id"],
            data["initial_state"],
            data["final_state"],
            tuple(Event.from_dict(e) for e in data["events"]),
            data["final_answer"],
            data["stop_reason"],
        )


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "reasons": list(self.reasons)}
