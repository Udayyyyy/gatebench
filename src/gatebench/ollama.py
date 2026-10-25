"""Ollama transport and a bounded loop shared by local and public environments."""

from __future__ import annotations

import copy
import json
import math
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from gatebench.environment import Environment
from gatebench.models import Action, Episode
from gatebench.tasks import Task
from gatebench.tooling import TOOL_SCHEMAS

MAX_RESPONSE = 4 * 1024 * 1024
SYSTEM_PROMPT = (
    "Resolve the customer's request using tools. Follow every policy clause. "
    "You can call tools over multiple turns. End with a short factual summary."
)


def _token_total(record: dict[str, Any], field: str) -> int | None:
    responses = record["responses"]
    if not responses or len(responses) != len(record["requests"]):
        return None
    counts = [response.get(field) for response in responses]
    if any(type(count) is not int or count < 0 for count in counts):
        return None
    return sum(counts)


def _origin(endpoint: str) -> str:
    url = urllib.parse.urlsplit(endpoint)
    if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password:
        raise ValueError("endpoint must be an HTTP(S) origin without credentials")
    if url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError("endpoint must be an origin; /api/chat is added by the runner")
    return endpoint.rstrip("/")


def request_json(
    endpoint: str, path: str, payload: dict[str, Any] | None = None, *, timeout: float = 30
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = urllib.request.Request(
        _origin(endpoint) + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("model response exceeded 4 MiB")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("model response must be an object")
    return result


def run_tool_loop(
    prompt: str,
    tool_schemas: list[dict[str, Any]],
    execute: Callable[[Action], dict[str, Any]],
    *,
    model: str,
    endpoint: str = "http://127.0.0.1:11434",
    max_steps: int = 32,
    max_turns: int = 24,
    timeout: float = 30,
    deadline: float = 120,
    seed: int = 17,
    temperature: float = 0,
    thinking: bool = False,
    context_window: int = 8192,
    num_predict: int = 512,
    task_fingerprint: str = "",
) -> tuple[str, str, dict[str, Any]]:
    _origin(endpoint)
    integers = (max_steps, max_turns, context_window, num_predict)
    if (
        not isinstance(model, str)
        or not model
        or any(type(v) is not int or v < 1 for v in integers)
    ):
        raise ValueError("model and positive integer budgets are required")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if not all(math.isfinite(v) and v > 0 for v in (timeout, deadline)):
        raise ValueError("timeout and deadline must be positive finite seconds")
    if not math.isfinite(temperature) or temperature < 0 or type(thinking) is not bool:
        raise ValueError("temperature must be nonnegative and thinking must be boolean")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    options = {
        "seed": seed,
        "temperature": temperature,
        "num_predict": num_predict,
        "num_ctx": context_window,
        "top_k": 20,
        "top_p": 0.95,
        "presence_penalty": 0,
        "repeat_penalty": 1,
    }
    record: dict[str, Any] = {
        "kind": "model_trial",
        "adapter": "ollama",
        "model": model,
        "endpoint": endpoint,
        "seed": seed,
        "temperature": temperature,
        "thinking": thinking,
        "max_steps": max_steps,
        "max_turns": max_turns,
        "timeout_seconds": timeout,
        "deadline_seconds": deadline,
        "context_window": context_window,
        "num_predict": num_predict,
        "options": options,
        "task_fingerprint": task_fingerprint,
        "requests": [],
        "responses": [],
        "messages": messages,
    }
    started = time.monotonic()
    final, stop, calls_executed = "", "budget", 0
    try:
        for _ in range(max_turns):
            remaining = deadline - (time.monotonic() - started)
            if remaining <= 0:
                break
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": thinking,
                "tools": [{"type": "function", "function": schema} for schema in tool_schemas],
                "options": options,
            }
            record["requests"].append(copy.deepcopy(payload))
            data = request_json(endpoint, "/api/chat", payload, timeout=min(timeout, remaining))
            record["responses"].append(copy.deepcopy(data))
            if time.monotonic() - started >= deadline:
                record["deadline_exceeded"] = True
                break
            message = data["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError("model response lacks an assistant message")
            if data.get("done") is not True:
                raise ValueError("nonstreaming response did not finish")
            final = message.get("content", "")
            if not isinstance(final, str):
                raise ValueError("assistant content must be text")
            calls = message.get("tool_calls", [])
            if not isinstance(calls, list):
                raise ValueError("tool_calls must be a list")
            messages.append(message)
            if data.get("done_reason") == "length":
                break
            if not calls:
                stop = "completed"
                break
            exhausted = False
            for call in calls:
                if calls_executed >= max_steps or time.monotonic() - started >= deadline:
                    exhausted = True
                    break
                function = call["function"]
                action = Action.from_dict(
                    {"name": function["name"], "arguments": function["arguments"]}
                )
                result = execute(action)
                calls_executed += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": action.name,
                        "content": json.dumps(result, allow_nan=False),
                    }
                )
            if exhausted:
                break
    except (OSError, ValueError, KeyError, TypeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        stop = "error"
    record["elapsed_seconds"] = round(time.monotonic() - started, 6)
    record["tool_calls"] = calls_executed
    record["prompt_tokens"] = _token_total(record, "prompt_eval_count")
    record["completion_tokens"] = _token_total(record, "eval_count")
    record["load_duration_ns"] = sum(r.get("load_duration", 0) for r in record["responses"])
    return final, stop, record


def run_model(task: Task, **options: Any) -> tuple[Episode, dict[str, Any]]:
    """Keep the GateBench environment outside the model's tool-only interface."""
    with Environment(task) as env:
        final, stop, record = run_tool_loop(
            task.prompt, TOOL_SCHEMAS, env.execute, task_fingerprint=task.fingerprint, **options
        )
        return env.episode(final, stop), record
