"""Offline checks of a captured study's consistency, not proof of its origin."""

from __future__ import annotations

import hashlib
import json
import math
import zlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from gatebench.experiments.analysis import summarize_trials
from gatebench.experiments.runner import (
    _case_dict,
    _cases,
    _sources,
    _trial_id,
    _validate_config,
    _validate_trial,
    read_trial,
)
from gatebench.graders import GRADERS, grade
from gatebench.models import Action, Episode, canonical_json, digest
from gatebench.ollama import SYSTEM_PROMPT
from gatebench.replay import replay
from gatebench.tooling import TOOL_SCHEMAS

_SCOPE = (
    "Checks captured source/configuration/task hashes, the complete scheduled matrix, "
    "raw request-response-tool linkage, environment replay, and saved grades. "
    "Checks saved rows.json and summary.json when present; derived reports, warm-ups, "
    "and annotation bytes are outside this check. "
    "It does not authenticate artifact origin, prove which model weights actually ran, "
    "or independently measure elapsed time."
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _same(actual: Any, expected: Any, message: str) -> None:
    _require(canonical_json(actual) == canonical_json(expected), message)


def _tools(case: Any, domain: str) -> list[dict[str, Any]]:
    if domain == "gatebench":
        return TOOL_SCHEMAS
    if domain == "tau2-retail":
        from gatebench.integrations.tau_retail import TauRetailEnvironment

        with TauRetailEnvironment(case) as environment:
            return environment.tool_schemas
    raise ValueError("unknown study domain")


def _token_count(record: dict[str, Any], name: str) -> int | None:
    responses = record["responses"]
    if not responses or len(responses) != len(record["requests"]):
        return None
    values = [response.get(name) for response in responses]
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return sum(values)


def _link_transcript(case: Any, artifact: dict[str, Any], domain: str) -> None:
    record, episode = artifact["model_record"], artifact["episode"]
    _require(record.get("kind") == "model_trial", "record is not a captured model_trial")
    _require(record.get("adapter") == "ollama", "unsupported captured model adapter")
    _same(record.get("task_fingerprint"), case.fingerprint, "trusted task fingerprint differs")
    requests, responses, messages = record["requests"], record["responses"], record["messages"]
    _require(
        all(isinstance(value, list) for value in (requests, responses, messages)),
        "request/response/message collections must be lists",
    )
    stop = episode["stop_reason"]
    _require(stop in ("completed", "budget", "error"), "unknown captured termination")
    _require(
        len(responses) <= len(requests) <= record["max_turns"],
        "request/response turn counts violate budgets",
    )
    _require(
        len(requests) - len(responses) <= 1,
        "multiple unanswered requests in a sequential collector",
    )
    if stop == "completed":
        _require(
            bool(responses) and len(requests) == len(responses),
            "completed trial lacks a finished response",
        )
    if stop == "error":
        _require(
            isinstance(record.get("error"), str) and bool(record["error"]),
            "error termination lacks a recorded diagnostic",
        )
    else:
        _require(
            "error" not in record, "non-error termination has a contradictory error diagnostic"
        )
    _require(
        type(record["tool_calls"]) is int and 0 <= record["tool_calls"] <= record["max_steps"],
        "captured tool count violates budget",
    )
    events = episode["events"]
    _require(
        isinstance(events, list) and len(events) == record["tool_calls"],
        "episode and model tool counts differ",
    )
    initial = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": case.prompt},
    ]
    prefix = list(initial)
    schemas = [{"type": "function", "function": schema} for schema in _tools(case, domain)]
    cursor, final = 0, ""
    final_answer_seen = False

    def terminal(index: int, expected_stop: tuple[str, ...]) -> None:
        _require(index == len(requests) - 1, "collector continued after a terminal response")
        _require(stop in expected_stop, "terminal response contradicts captured stop reason")

    for index, request in enumerate(requests):
        expected_request = {
            "model": record["model"],
            "messages": prefix,
            "stream": False,
            "think": record["thinking"],
            "tools": schemas,
            "options": record["options"],
        }
        _same(
            request,
            expected_request,
            f"request[{index}] differs from trusted prompt, settings, tools, or prior transcript",
        )
        if index == len(responses):
            terminal(index, ("error",))
            continue
        response = responses[index]
        _require(isinstance(response, dict), "captured response must be an object")
        if "model" in response:
            _same(response["model"], record["model"], "raw response names a different model tag")
        if record.get("deadline_exceeded") is True and index == len(responses) - 1:
            terminal(index, ("budget",))
            _require(
                record["elapsed_seconds"] >= record["deadline_seconds"],
                "deadline flag contradicts captured elapsed time",
            )
            continue  # The collector stores the raw late response but does not consume it.
        message = response.get("message")
        if (
            not isinstance(message, dict)
            or message.get("role") != "assistant"
            or response.get("done") is not True
        ):
            terminal(index, ("error",))
            continue
        content = message.get("content", "")
        _require(isinstance(content, str), "captured assistant content is not text")
        final = content
        calls = message.get("tool_calls", [])
        if not isinstance(calls, list):
            terminal(index, ("error",))
            continue
        prefix.append(message)
        if response.get("done_reason") == "length":
            terminal(index, ("budget",))
            continue  # No potentially truncated tool payload is executed.
        if not calls:
            terminal(index, ("completed",))
            final_answer_seen = True
            continue
        for call in calls:
            try:
                function = call["function"]
                action = Action.from_dict(
                    {"name": function["name"], "arguments": function["arguments"]}
                )
            except (KeyError, TypeError, ValueError):
                terminal(index, ("error",))
                break
            if cursor == len(events):
                # A budget or execution error can leave a suffix of an assistant
                # tool batch unexecuted. It cannot be followed by another request.
                terminal(index, ("budget", "error"))
                break
            event = events[cursor]
            _same(
                action.to_dict(),
                event["action"],
                f"model tool action differs from episode event[{cursor}]",
            )
            _require(
                len(prefix) < len(messages), f"executed event[{cursor}] has no captured tool result"
            )
            tool_message = messages[len(prefix)]
            _require(
                isinstance(tool_message, dict)
                and set(tool_message) == {"role", "tool_name", "content"},
                "invalid tool-result message fields",
            )
            _require(
                tool_message["role"] == "tool" and tool_message["tool_name"] == action.name,
                "tool-result message names a different action",
            )
            _require(
                isinstance(tool_message["content"], str),
                "tool-result content is not serialized JSON",
            )
            _same(
                json.loads(tool_message["content"]),
                event["result"],
                f"captured tool result differs from episode event[{cursor}]",
            )
            prefix.append(tool_message)
            cursor += 1
    _same(messages, prefix, "captured message history contains missing or invented messages")
    _require(cursor == len(events), "episode contains actions absent from raw model responses")
    _same(episode["final_answer"], final, "episode final answer differs from consumed raw response")
    if stop == "completed":
        _require(final_answer_seen, "completed trial has no final response without tools")
    _same(
        record.get("prompt_tokens"),
        _token_count(record, "prompt_eval_count"),
        "prompt-token total differs from raw responses",
    )
    _same(
        record.get("completion_tokens"),
        _token_count(record, "eval_count"),
        "completion-token total differs from raw responses",
    )
    _same(
        record.get("load_duration_ns"),
        sum(r.get("load_duration", 0) for r in responses),
        "model-load duration differs from raw responses",
    )
    _same(
        record.get("context_window"),
        record["options"]["num_ctx"],
        "duplicate context-window metadata differs",
    )
    _same(
        record.get("num_predict"),
        record["options"]["num_predict"],
        "duplicate generation-budget metadata differs",
    )
    _same(
        record.get("temperature"),
        record["options"]["temperature"],
        "duplicate temperature metadata differs",
    )
    elapsed = record.get("elapsed_seconds")
    _require(
        type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
        "invalid captured elapsed time",
    )


def _replay_and_grade(case: Any, artifact: dict[str, Any], domain: str) -> dict[str, Any]:
    evidence = artifact["episode"]
    if domain == "gatebench":
        episode = Episode.from_dict(evidence)
        # Replay incomplete trials too. The business verifier correctly fails
        # them early; that must not hide an inconsistent captured journal.
        consistency = replay(case, replace(episode, stop_reason="completed"))
        _require(consistency.passed, "episode replay differs: " + "; ".join(consistency.reasons))
        return {name: grade(name, case, episode).to_dict() for name in GRADERS}
    if domain != "tau2-retail":
        raise ValueError("unknown study domain")
    from gatebench.integrations.tau_retail import TauRetailEnvironment, evaluate

    with TauRetailEnvironment(case) as environment:
        for event in evidence["events"]:
            environment.execute(Action.from_dict(event["action"]))
        expected = environment.episode(evidence["final_answer"], evidence["stop_reason"])
    _same(evidence, expected, "native episode action/result/state replay differs")
    evaluation = evaluate(case, evidence)
    return {
        "native": {
            "passed": evaluation["native_environment"]["reward"] == 1,
            "reasons": [],
            "details": evaluation["native_environment"],
        },
        "hardened": {
            "passed": evaluation["hardened_passed"],
            "reasons": evaluation["policy"]["reasons"],
            "details": evaluation,
        },
    }


def verify_trial_evidence(case: Any, artifact: dict[str, Any], domain: str) -> dict[str, Any]:
    """Link one captured trial to a separately supplied trusted case, offline."""
    problems = []
    try:
        _link_transcript(case, artifact, domain)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        problems.append(f"transcript: {exc}")
    try:
        expected = _replay_and_grade(case, artifact, domain)
        _same(artifact["verdicts"], expected, "saved detailed verdicts differ from regrading")
        _same(
            artifact["row"]["graders"],
            {name: value["passed"] for name, value in expected.items()},
            "saved row grader decisions differ from regrading",
        )
        _same(
            artifact["row"]["reasons"],
            {name: value["reasons"] for name, value in expected.items()},
            "saved row rejection reasons differ from regrading",
        )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        problems.append(f"replay/grades: {exc}")
    return {"valid": not problems, "problems": problems, "verification_scope": _SCOPE}


def verify_study(output: Path) -> dict[str, Any]:
    """Verify the complete saved matrix without contacting a model server."""
    problems: list[str] = []
    checked, verified, expected_count = 0, 0, 0
    try:
        frozen = json.loads((output / "frozen-study.json").read_text())
        _require(
            frozen.get("kind") == "frozen_real_model_study" and frozen.get("schema_version") == 1,
            "unsupported frozen study manifest",
        )
        config = frozen["config"]
        _validate_config(config)
        _same(frozen["config_sha256"], digest(config), "frozen configuration hash differs")
        _same(
            frozen["sources"],
            _sources(config["domain"]),
            "collector/evaluator sources differ from the frozen study",
        )
        cases = _cases(config)
        _same(
            frozen["tasks_digest"],
            digest([_case_dict(case) for case in cases]),
            "frozen task specification digest differs",
        )
        schedule = [
            (_trial_id(model_index, case.id, repeat), case, model_index, repeat)
            for model_index, _ in enumerate(config["models"])
            for case in cases
            for repeat, _ in enumerate(config["repetitions"]["decode_seeds"])
        ]
        expected_ids = [trial_id for trial_id, *_ in schedule]
        expected_count = len(expected_ids)
        _same(
            frozen["expected_trials"],
            expected_ids,
            "frozen expected matrix differs from the configured schedule",
        )
        for case in cases:
            _same(
                json.loads((output / "tasks" / f"{case.id}.json").read_text()),
                _case_dict(case),
                f"saved task file differs: {case.id}",
            )
        for model in config["models"]:
            metadata = frozen["model_metadata"][model]
            _same(
                metadata["template_sha256"],
                hashlib.sha256(metadata["show"].get("template", "").encode()).hexdigest(),
                f"model template fingerprint differs: {model}",
            )
            model_digest = metadata["tag"]["digest"]
            _require(
                isinstance(model_digest, str)
                and len(model_digest) == 64
                and all(c in "0123456789abcdef" for c in model_digest),
                f"invalid pinned model digest: {model}",
            )
        expected_paths = {f"{trial_id}.json.gz" for trial_id in expected_ids}
        actual_paths = {path.name for path in (output / "trials").glob("*.json.gz")}
        for name in sorted(expected_paths - actual_paths):
            problems.append(f"missing scheduled trial: {name}")
        for name in sorted(actual_paths - expected_paths):
            problems.append(f"unexpected trial outside frozen matrix: {name}")
        rows = []
        for trial_id, case, model_index, repeat in schedule:
            path = output / "trials" / f"{trial_id}.json.gz"
            if not path.is_file():
                continue
            try:
                data = read_trial(path)
                checked += 1
                _validate_trial(data, frozen, case, model_index, repeat)
                _require(
                    type(data["row"]["repeat"]) is int and type(data["row"]["decode_seed"]) is int,
                    "trial repetition/seed metadata must be integers",
                )
                _same(
                    data["row"]["artifact"],
                    f"trials/{path.name}",
                    "trial artifact path differs from scheduled file",
                )
                result = verify_trial_evidence(case, data, config["domain"])
                if result["valid"]:
                    verified += 1
                else:
                    problems.extend(f"{trial_id}: {problem}" for problem in result["problems"])
                rows.append(data["row"])
            except (
                OSError,
                EOFError,
                zlib.error,
                AttributeError,
                KeyError,
                TypeError,
                ValueError,
                OverflowError,
            ) as exc:
                problems.append(f"{trial_id}: {exc}")
        if len(rows) == expected_count:
            row_path = output / "rows.json"
            if row_path.is_file():
                _same(
                    json.loads(row_path.read_text()),
                    rows,
                    "published rows differ from checked trial artifacts",
                )
            summary_path = output / "summary.json"
            if summary_path.is_file():
                expected_summary = summarize_trials(
                    rows,
                    expected_models=config["models"],
                    expected_task_ids=[case.id for case in cases],
                    repeats=len(config["repetitions"]["decode_seeds"]),
                    bootstrap_samples=config["analysis"]["bootstrap_samples"],
                    seed=config["analysis"]["seed"],
                )
                _same(
                    json.loads(summary_path.read_text()),
                    expected_summary,
                    "published summary differs from checked trial artifacts",
                )
    except (OSError, AttributeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        problems.append(str(exc))
    return {
        "valid": not problems,
        "trials": checked,
        "expected_trials": expected_count,
        "verified_trials": verified,
        "problems": problems,
        "verification_scope": _SCOPE,
    }
