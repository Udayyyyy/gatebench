"""Unit-only captured transport fixtures; no inference or published study data."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from gatebench import ollama
from gatebench.baselines import reference_plan
from gatebench.environment import Environment
from gatebench.experiments import runner
from gatebench.experiments.analysis import summarize_trials
from gatebench.experiments.verification import verify_study, verify_trial_evidence
from gatebench.graders import GRADERS, grade
from gatebench.models import Action, digest
from gatebench.runner import write_json
from gatebench.tasks import make_task

MODEL = "unit-fixture-no-inference"
MODEL_DIGEST = "ab" * 32


def assistant(*actions, content="", done_reason="stop"):
    message = {"role": "assistant", "content": content}
    if actions:
        message["tool_calls"] = [
            {"function": {"name": action.name, "arguments": copy.deepcopy(action.arguments)}}
            for action in actions
        ]
    return {
        "model": MODEL,
        "message": message,
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 11,
        "eval_count": 7,
        "load_duration": 0,
    }


def capture(monkeypatch, *, responses=None, max_steps=24, case=None, domain="gatebench"):
    case = case or make_task("refund", 0)
    config = {
        "schema_version": 1,
        "kind": "real_model_study",
        "study_id": "unit-fixture-never-publish",
        "models": [MODEL],
        "domain": domain,
        "task_selection": {"split": "dev", "families": ["refund"], "seeds": [0]},
        "repetitions": {"decode_seeds": [17]},
        "generation": {
            "temperature": 0.2,
            "think": False,
            "num_ctx": 8192,
            "num_predict": 512,
            "top_k": 20,
            "top_p": 0.95,
            "presence_penalty": 0,
            "repeat_penalty": 1,
        },
        "budgets": {"max_steps": max_steps, "max_turns": 16, "timeout": 60, "deadline": 180},
        "analysis": {"bootstrap_samples": 0, "seed": 17},
    }
    if domain == "gatebench":
        plan = reference_plan(case)
        environment = Environment(case)
        schemas = ollama.TOOL_SCHEMAS
    else:
        from gatebench.integrations.tau_retail import TauRetailEnvironment, reference_actions

        plan = reference_actions(case)
        environment = TauRetailEnvironment(case)
        schemas = environment.tool_schemas
        config["task_selection"] = {"per_family": 1}
    queue = (
        list(responses)
        if responses is not None
        else [assistant(action) for action in plan] + [assistant(content="Request completed.")]
    )

    def request(*args, **kwargs):
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    monkeypatch.setattr(ollama, "request_json", request)
    with environment:
        final, stop, record = ollama.run_tool_loop(
            case.prompt,
            schemas,
            environment.execute,
            model=MODEL,
            seed=17,
            temperature=0.2,
            max_steps=max_steps,
            max_turns=16,
            timeout=60,
            deadline=180,
            context_window=8192,
            num_predict=512,
            task_fingerprint=case.fingerprint,
        )
        episode = environment.episode(final, stop)
    record["runtime"] = {"version": "unit-fixture-runtime"}
    if domain == "gatebench":
        evidence = episode.to_dict()
        verdicts = {name: grade(name, case, episode).to_dict() for name in GRADERS}
    else:
        from gatebench.integrations.tau_retail import evaluate

        evidence = episode
        evaluation = evaluate(case, evidence)
        verdicts = {
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
    row = {
        "trial_id": runner._trial_id(0, case.id, 0),
        "task_id": case.id,
        "family": case.family,
        "domain": domain,
        "model": MODEL,
        "model_digest": MODEL_DIGEST,
        "repeat": 0,
        "decode_seed": 17,
        "stop_reason": stop,
        "graders": {name: value["passed"] for name, value in verdicts.items()},
        "reasons": {name: value["reasons"] for name, value in verdicts.items()},
        "config_sha256": digest(config),
        **{
            name: record[name]
            for name in ("elapsed_seconds", "prompt_tokens", "completion_tokens", "tool_calls")
        },
    }
    row["artifact"] = f"trials/{row['trial_id']}.json.gz"
    return (
        case,
        config,
        {"row": row, "episode": evidence, "model_record": record, "verdicts": verdicts},
    )


def save_study(directory: Path, case, config, artifact) -> Path:
    task = case.to_dict() if hasattr(case, "to_dict") else asdict(case)
    template = "unit-test template; no inference"
    frozen = {
        "schema_version": 1,
        "kind": "frozen_real_model_study",
        "config": config,
        "config_sha256": digest(config),
        "sources": runner._sources(config["domain"]),
        "tasks_digest": digest([task]),
        "expected_trials": [artifact["row"]["trial_id"]],
        "model_metadata": {
            MODEL: {
                "tag": {"name": MODEL, "digest": MODEL_DIGEST},
                "show": {"template": template},
                "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
            }
        },
        "runtime": artifact["model_record"]["runtime"],
    }
    write_json(directory / "frozen-study.json", frozen)
    write_json(directory / "tasks" / f"{case.id}.json", task)
    runner._write_trial(directory / artifact["row"]["artifact"], artifact)
    write_json(directory / "rows.json", [artifact["row"]])
    return directory


@pytest.fixture
def captured(monkeypatch):
    return capture(monkeypatch)


def test_complete_consistent_unit_transport_fixture_is_verifiable_offline(
    tmp_path, captured, monkeypatch
):
    case, config, artifact = captured
    directory = save_study(tmp_path / "unit-only-study", case, config, artifact)
    monkeypatch.setattr(
        ollama,
        "request_json",
        lambda *a, **k: pytest.fail("offline verification contacted a server"),
    )
    result = verify_study(directory)
    assert result["valid"], result["problems"]
    assert result["trials"] == result["expected_trials"] == result["verified_trials"] == 1
    assert "does not authenticate" in result["verification_scope"]


@pytest.mark.parametrize("change", ["source", "config_hash", "matrix", "saved_task", "template"])
def test_manifest_and_task_drift_fail_before_regrading(tmp_path, captured, change):
    case, config, artifact = captured
    directory = save_study(tmp_path / "unit-only-study", case, config, artifact)
    path = directory / "frozen-study.json"
    frozen = json.loads(path.read_text())
    if change == "source":
        frozen["sources"]["models.py"] = "changed"
    elif change == "config_hash":
        frozen["config_sha256"] = "changed"
    elif change == "matrix":
        frozen["expected_trials"] = []
    elif change == "saved_task":
        task = case.to_dict()
        task["auth_code"] = "changed"
        write_json(directory / "tasks" / f"{case.id}.json", task)
    else:
        frozen["model_metadata"][MODEL]["show"]["template"] = "changed"
    write_json(path, frozen)
    assert not verify_study(directory)["valid"]


@pytest.mark.parametrize("change", ["missing", "extra", "sidecar", "bytes"])
def test_study_checks_exact_matrix_and_compressed_file_hashes(tmp_path, captured, change):
    case, config, artifact = captured
    directory = save_study(tmp_path / "unit-only-study", case, config, artifact)
    path = directory / artifact["row"]["artifact"]
    if change == "missing":
        path.unlink()
    elif change == "extra":
        (path.parent / "unscheduled.json.gz").write_bytes(path.read_bytes())
    elif change == "sidecar":
        path.with_suffix(path.suffix + ".sha256").write_text("0" * 64)
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    result = verify_study(directory)
    assert not result["valid"] and result["problems"]


@pytest.mark.parametrize(
    "change",
    [
        "raw_action",
        "raw_result",
        "final_answer",
        "trusted_prompt",
        "tool_schema",
        "tokens",
        "fixture_kind",
    ],
)
def test_trial_checker_links_raw_capture_to_trusted_episode(captured, change):
    case, _, artifact = captured
    data = copy.deepcopy(artifact)
    record = data["model_record"]
    if change == "raw_action":
        record["responses"][0]["message"]["tool_calls"][0]["function"]["arguments"]["order_id"] = (
            "different-order"
        )
    elif change == "raw_result":
        tool_message = next(message for message in record["messages"] if message["role"] == "tool")
        tool_message["content"] = json.dumps({"ok": True, "invented": True})
    elif change == "final_answer":
        data["episode"]["final_answer"] += " invented final text"
    elif change == "trusted_prompt":
        record["requests"][0]["messages"][1]["content"] = "different task"
    elif change == "tool_schema":
        record["requests"][0]["tools"] = []
    elif change == "tokens":
        record["completion_tokens"] = 999
        data["row"]["completion_tokens"] = 999
    else:
        record["kind"] = "unit_test_fixture"
    result = verify_trial_evidence(case, data, "gatebench")
    assert not result["valid"]
    assert any(problem.startswith("transcript:") for problem in result["problems"])


def test_rehashed_metadata_consistent_score_tampering_is_rejected(tmp_path, captured):
    case, config, artifact = captured
    data = copy.deepcopy(artifact)
    data["row"]["graders"]["hardened"] = False
    data["row"]["reasons"]["hardened"] = ["invented failure"]
    data["verdicts"]["hardened"] = {"passed": False, "reasons": ["invented failure"]}
    directory = save_study(tmp_path / "unit-only-study", case, config, data)
    result = verify_study(directory)
    assert not result["valid"]
    assert any("verdicts differ from regrading" in problem for problem in result["problems"])


def test_published_rows_cannot_disagree_with_individual_trial_artifacts(tmp_path, captured):
    case, config, artifact = captured
    directory = save_study(tmp_path / "unit-only-study", case, config, artifact)
    row = copy.deepcopy(artifact["row"])
    row["graders"]["hardened"] = False
    write_json(directory / "rows.json", [row])
    result = verify_study(directory)
    assert not result["valid"]
    assert any("published rows differ" in problem for problem in result["problems"])


@pytest.mark.parametrize("damage", ["truncated", "invalid_deflate"])
def test_malformed_rehashed_archive_is_invalid_instead_of_crashing(tmp_path, captured, damage):
    case, config, artifact = captured
    directory = save_study(tmp_path / "unit-only-study", case, config, artifact)
    path = directory / artifact["row"]["artifact"]
    if damage == "truncated":
        path.write_bytes(path.read_bytes()[:-5])
    else:
        # Valid gzip header followed by the reserved DEFLATE block type.
        path.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\x07" + b"\x00" * 8)
    path.with_suffix(path.suffix + ".sha256").write_text(runner.file_hash(path))
    result = verify_study(directory)
    assert not result["valid"] and result["problems"]


def test_published_summary_intervals_are_recomputed(tmp_path, captured):
    case, config, artifact = captured
    directory = save_study(tmp_path / "unit-only-study", case, config, artifact)
    config["analysis"]["bootstrap_samples"] = 20
    # This fixture's manifest and row must agree with its intentionally small
    # bootstrap configuration before testing an altered published interval.
    artifact["row"]["config_sha256"] = digest(config)
    save_study(directory, case, config, artifact)
    summary = summarize_trials(
        [artifact["row"]],
        expected_models=[MODEL],
        expected_task_ids=[case.id],
        repeats=1,
        bootstrap_samples=20,
        seed=17,
    )
    write_json(directory / "summary.json", summary)
    assert verify_study(directory)["valid"]
    summary["models"][MODEL]["graders"]["hardened"]["ci"] = [0.2, 0.8]
    write_json(directory / "summary.json", summary)
    result = verify_study(directory)
    assert not result["valid"]
    assert any("published summary differs" in problem for problem in result["problems"])


def test_budgeted_tool_batch_may_have_an_unexecuted_suffix(monkeypatch):
    task = make_task("refund", 0)
    read = Action("get_order", {"order_id": task.order_id})
    case, _, artifact = capture(
        monkeypatch, case=task, max_steps=2, responses=[assistant(*([read] * 10))]
    )
    assert artifact["episode"]["stop_reason"] == "budget"
    assert len(artifact["episode"]["events"]) == 2
    assert verify_trial_evidence(case, artifact, "gatebench")["valid"]
    corrupt = copy.deepcopy(artifact)
    corrupt["episode"]["final_state"]["orders"][task.order_id]["note"] = "invented state"
    assert not verify_trial_evidence(case, corrupt, "gatebench")["valid"]


def test_failed_transport_retains_a_last_request_without_a_response(monkeypatch):
    task = make_task("refund", 0)
    first = reference_plan(task)[0]
    case, _, artifact = capture(
        monkeypatch,
        case=task,
        responses=[assistant(first), OSError("unit-only transport interruption")],
    )
    record = artifact["model_record"]
    assert len(record["requests"]) == 2 and len(record["responses"]) == 1
    assert record["completion_tokens"] is None
    assert verify_trial_evidence(case, artifact, "gatebench")["valid"]


def test_truncated_response_calls_are_retained_but_not_executed(monkeypatch):
    task = make_task("refund", 0)
    case, _, artifact = capture(
        monkeypatch,
        case=task,
        responses=[assistant(*reference_plan(task), content="partial", done_reason="length")],
    )
    assert artifact["episode"]["stop_reason"] == "budget"
    assert not artifact["episode"]["events"]
    assert verify_trial_evidence(case, artifact, "gatebench")["valid"]


@pytest.mark.skipif(importlib.util.find_spec("pandas") is None, reason="optional tau dependencies")
def test_native_public_episode_is_replayed_and_compared_to_raw_tool_capture(monkeypatch):
    from gatebench.integrations.tau_retail import load_suite

    case, _, artifact = capture(monkeypatch, case=load_suite()[0], domain="tau2-retail")
    result = verify_trial_evidence(case, artifact, "tau2-retail")
    assert result["valid"], result["problems"]
    artifact["episode"]["final_hash"] = "0" * 64
    assert not verify_trial_evidence(case, artifact, "tau2-retail")["valid"]
