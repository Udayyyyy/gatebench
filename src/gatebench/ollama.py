"""A bounded tool-only agent loop; models never receive the SQLite connection."""

from __future__ import annotations

import copy
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from gatebench.environment import Environment
from gatebench.models import Action, Episode
from gatebench.tasks import Task
from gatebench.tooling import TOOL_SCHEMAS

MAX_RESPONSE = 4 * 1024 * 1024


def run_model(
    task: Task,
    *,
    model: str,
    endpoint: str = "http://127.0.0.1:11434",
    max_steps: int = 32,
    max_turns: int = 24,
    timeout: float = 30,
    deadline: float = 120,
    seed: int = 17,
    temperature: float = 0,
) -> tuple[Episode, dict[str, Any]]:
    url = urllib.parse.urlsplit(endpoint)
    if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
        raise ValueError("endpoint must be an HTTP(S) origin without credentials")
    if url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError("endpoint must be an origin; /api/chat is added by the runner")
    if (
        not isinstance(model, str)
        or not model
        or any(type(v) is not int or v < 1 for v in (max_steps, max_turns))
    ):
        raise ValueError("model and positive tool/turn budgets are required")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if not all(math.isfinite(v) and v > 0 for v in (timeout, deadline)):
        raise ValueError("timeout and deadline must be positive finite seconds")
    if not math.isfinite(temperature) or temperature < 0:
        raise ValueError("temperature must be nonnegative and finite")
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "Resolve the customer's request using tools. Follow every policy clause. You can call tools over multiple turns. End with a short factual summary.",
        },
        {"role": "user", "content": task.prompt},
    ]
    record: dict[str, Any] = {
        "kind": "model_trial",
        "adapter": "ollama",
        "model": model,
        "endpoint": endpoint,
        "seed": seed,
        "temperature": temperature,
        "max_steps": max_steps,
        "max_turns": max_turns,
        "timeout_seconds": timeout,
        "deadline_seconds": deadline,
        "task_fingerprint": task.fingerprint,
        "responses": [],
        "messages": messages,
    }
    started = time.monotonic()
    final, stop = "", "budget"
    with Environment(task) as env:
        try:
            for _ in range(max_turns):
                remaining = deadline - (time.monotonic() - started)
                if remaining <= 0:
                    break
                body = json.dumps(
                    {
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "tools": [
                            {"type": "function", "function": schema} for schema in TOOL_SCHEMAS
                        ],
                        "options": {"seed": seed, "temperature": temperature, "num_predict": 2048},
                    }
                ).encode()
                request = urllib.request.Request(
                    endpoint.rstrip("/") + "/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=min(timeout, remaining)) as response:
                    raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError("model response exceeded 4 MiB")
                data = json.loads(raw)
                record["responses"].append(copy.deepcopy(data))
                if time.monotonic() - started >= deadline:
                    record["deadline_exceeded"] = True
                    break
                message = data["message"]
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    raise ValueError("model response lacks an assistant message")
                final = message.get("content", "")
                if not isinstance(final, str):
                    raise ValueError("assistant content must be text")
                calls = message.get("tool_calls", [])
                if not isinstance(calls, list):
                    raise ValueError("tool_calls must be a list")
                messages.append(message)
                if data.get("done_reason") == "length":
                    # Never execute a potentially truncated tool-call payload.
                    stop = "budget"
                    break
                if not calls:
                    stop = "completed"
                    break
                exhausted = False
                for call in calls:
                    if len(env.events) >= max_steps or time.monotonic() - started >= deadline:
                        exhausted = True
                        break
                    function = call["function"]
                    action = Action.from_dict(
                        {"name": function["name"], "arguments": function["arguments"]}
                    )
                    result = env.execute(action)
                    messages.append(
                        {"role": "tool", "tool_name": action.name, "content": json.dumps(result)}
                    )
                if exhausted:
                    break
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Preserve partial evidence; a transport error must never become a pass.
            record["error"] = f"{type(exc).__name__}: {exc}"
            stop = "error"
        record["elapsed_seconds"] = round(time.monotonic() - started, 6)
        record["tool_calls"] = len(env.events)
        return env.episode(final, stop), record
