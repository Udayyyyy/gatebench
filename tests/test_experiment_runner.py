"""Unit fixtures only: no inference, network calls, or public study artifacts."""

import copy
import json

import pytest

from gatebench import ollama
from gatebench.environment import Environment
from gatebench.experiments import runner


@pytest.fixture
def fixture_study(tmp_path, monkeypatch):
    config = {
        "schema_version": 1,
        "kind": "real_model_study",
        "study_id": "unit-fixture-no-inference",
        "models": ["unit-fixture-a", "unit-fixture-b"],
        "domain": "gatebench",
        "task_selection": {"split": "dev", "families": ["refund", "cancel"], "seeds": [0]},
        "repetitions": {"decode_seeds": [17, 29]},
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
        "budgets": {"max_steps": 24, "max_turns": 16, "timeout": 60, "deadline": 180},
        "analysis": {"bootstrap_samples": 0, "seed": 17},
    }
    path = tmp_path / "fixture-config.json"
    path.write_text(json.dumps(config))
    state = {"runtime": {"version": "unit-fixture-runtime"}, "calls": [], "fail_at": None}

    def metadata(endpoint, names):
        return {
            name: {
                "tag": {"name": name, "digest": "unit-fixture-digest-" + name},
                "show": {"template": "unit fixture"},
                "template_sha256": "fixture-only",
            }
            for name in names
        }

    def request(endpoint, route, payload=None, **options):
        if route == "/api/version":
            return copy.deepcopy(state["runtime"])
        if route == "/api/chat":
            assert payload["messages"][0]["content"] == "Reply with OK."
            return {"unit_fixture": True, "message": {"role": "assistant", "content": "OK"}}
        raise AssertionError("unit fixture attempted an unexpected network route")

    def collect(case, study_config, model, endpoint, seed):
        state["calls"].append((model, case.id, seed))
        if len(state["calls"]) == state["fail_at"]:
            raise RuntimeError("unit fixture interruption")
        with Environment(case) as environment:
            episode = environment.episode("Unit fixture; no model inference or business actions.")
        record = {
            "kind": "unit_test_fixture",
            "model": model,
            "seed": seed,
            "task_fingerprint": case.fingerprint,
            "thinking": False,
            "max_steps": 24,
            "max_turns": 16,
            "timeout_seconds": 60,
            "deadline_seconds": 180,
            "options": {
                "seed": seed,
                "temperature": 0.2,
                "num_predict": 512,
                "num_ctx": 8192,
                "top_k": 20,
                "top_p": 0.95,
                "presence_penalty": 0,
                "repeat_penalty": 1,
            },
            "elapsed_seconds": 0.125,
            "prompt_tokens": None,
            "completion_tokens": None,
            "tool_calls": 0,
            "requests": [],
            "responses": [],
        }
        verdicts = {
            name: {"passed": False, "reasons": ["Unit fixture performed no requested outcome."]}
            for name in runner.GRADERS
        }
        return episode.to_dict(), record, verdicts

    monkeypatch.setattr(runner, "_model_metadata", metadata)
    monkeypatch.setattr(runner, "request_json", request)
    monkeypatch.setattr(runner, "_collect", collect)
    monkeypatch.setattr(runner, "_hardware", lambda: {"unit_fixture": True})
    # Stabilize the fixture while other development work changes unrelated files.
    monkeypatch.setattr(runner, "_sources", lambda domain: {"unit-fixture.py": "fixture-source"})
    return {
        "config": config,
        "config_path": path,
        "output": tmp_path / "fixture-study",
        "state": state,
        "collect": collect,
    }


def _collect_fixture(fixture):
    return runner.collect_study(
        fixture["config_path"], fixture["output"], endpoint="http://unit.invalid"
    )


def test_source_capture_includes_analysis_and_report():
    actual = runner._sources("gatebench")
    assert "experiments/analysis.py" in actual
    assert "experiments/report.py" in actual
    assert all(len(fingerprint) == 64 for fingerprint in actual.values())


def test_interrupted_fixture_collection_resumes_without_repeating_saved_trials(fixture_study):
    fixture = fixture_study
    fixture["state"]["fail_at"] = 2
    with pytest.raises(RuntimeError, match="fixture interruption"):
        _collect_fixture(fixture)
    trials = sorted((fixture["output"] / "trials").glob("*.json.gz"))
    assert len(trials) == 1
    preserved = trials[0].read_bytes()
    first_identity = fixture["state"]["calls"][0]
    fixture["state"]["fail_at"] = None
    summary = _collect_fixture(fixture)
    assert summary["corpus"]["trials"] == 8
    assert summary["corpus"]["task_clusters"] == 2
    assert trials[0].read_bytes() == preserved
    assert fixture["state"]["calls"].count(first_identity) == 1
    assert len(list((fixture["output"] / "trials").glob("*.json.gz"))) == 8
    assert len(list((fixture["output"] / "warmups").glob("m0-*.json"))) == 2
    for artifact in (fixture["output"] / "trials").glob("*.json.gz"):
        assert runner.read_trial(artifact)["model_record"]["kind"] == "unit_test_fixture"
    count = len(fixture["state"]["calls"])
    assert _collect_fixture(fixture) == summary
    assert len(fixture["state"]["calls"]) == count
    assert (fixture["output"] / "real-model-report.html").is_file()


def test_missing_trial_is_rejected_then_only_that_trial_is_collected(fixture_study):
    fixture = fixture_study
    _collect_fixture(fixture)
    artifact = sorted((fixture["output"] / "trials").glob("*.json.gz"))[0]
    expected = runner.read_trial(artifact)["row"]
    artifact.unlink()
    with pytest.raises(ValueError, match="study incomplete"):
        runner.summarize_study(fixture["output"])
    before = len(fixture["state"]["calls"])
    summary = _collect_fixture(fixture)
    assert summary["corpus"]["trials"] == 8
    assert len(fixture["state"]["calls"]) == before + 1
    assert fixture["state"]["calls"][-1] == (
        expected["model"],
        expected["task_id"],
        expected["decode_seed"],
    )


@pytest.mark.parametrize("which", ("artifact", "sidecar"))
def test_trial_corruption_is_not_silently_resumed(fixture_study, which):
    fixture = fixture_study
    _collect_fixture(fixture)
    path = sorted((fixture["output"] / "trials").glob("*.json.gz"))[0]
    if which == "artifact":
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        path.with_suffix(path.suffix + ".sha256").write_text("0" * 64 + "\n")
    with pytest.raises(ValueError, match="trial artifact changed"):
        _collect_fixture(fixture)


@pytest.mark.parametrize("field", ("config", "seed", "task_fingerprint"))
def test_rehashed_semantically_wrong_trials_rejected_on_resume_and_summary(fixture_study, field):
    fixture = fixture_study
    _collect_fixture(fixture)
    path = sorted((fixture["output"] / "trials").glob("*.json.gz"))[0]
    data = runner.read_trial(path)
    if field == "config":
        data["row"]["config_sha256"] = "different-budget-study"
    elif field == "seed":
        data["row"]["decode_seed"] = 999
    else:
        data["model_record"]["task_fingerprint"] = "different-task"
    runner._write_trial(path, data)  # Deliberately recompute the sidecar: identity must still fail.
    with pytest.raises(ValueError, match="differs from frozen"):
        _collect_fixture(fixture)
    with pytest.raises(ValueError, match="differs from frozen"):
        runner.summarize_study(fixture["output"])


@pytest.mark.parametrize(
    ("section", "field", "replacement", "message"),
    [
        ("model_record", "runtime", {"version": "different"}, "identity/runtime"),
        ("model_record", "options", {}, "generation settings"),
        ("model_record", "thinking", True, "generation settings"),
        ("model_record", "max_steps", 25, "budgets"),
        ("row", "completion_tokens", 99, "metrics"),
        ("episode", "stop_reason", "error", "termination"),
    ],
)
def test_trial_validator_checks_recorded_runtime_settings_budgets_and_metrics(
    fixture_study, section, field, replacement, message
):
    fixture = fixture_study
    _collect_fixture(fixture)
    frozen = json.loads((fixture["output"] / "frozen-study.json").read_text())
    case = runner._cases(fixture["config"])[0]
    path = fixture["output"] / "trials" / f"{runner._trial_id(0, case.id, 0)}.json.gz"
    data = runner.read_trial(path)
    data[section][field] = replacement
    with pytest.raises(ValueError, match=message):
        runner._validate_trial(data, frozen, case, 0, 0)


def test_source_and_config_drift_rejected_before_more_collection(fixture_study, monkeypatch):
    fixture = fixture_study
    _collect_fixture(fixture)
    before = len(fixture["state"]["calls"])
    monkeypatch.setattr(runner, "_sources", lambda domain: {"unit-fixture.py": "changed"})
    with pytest.raises(ValueError, match="config/source changed"):
        _collect_fixture(fixture)
    with pytest.raises(ValueError, match="sources changed"):
        runner.summarize_study(fixture["output"])
    monkeypatch.setattr(runner, "_sources", lambda domain: {"unit-fixture.py": "fixture-source"})
    changed = copy.deepcopy(fixture["config"])
    changed["generation"]["temperature"] = 0.3
    fixture["config_path"].write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="config/source changed"):
        _collect_fixture(fixture)
    assert len(fixture["state"]["calls"]) == before


def test_runtime_and_model_drift_rejected_before_resume(fixture_study, monkeypatch):
    fixture = fixture_study
    _collect_fixture(fixture)
    before = len(fixture["state"]["calls"])
    fixture["state"]["runtime"] = {"version": "upgraded-fixture-runtime"}
    with pytest.raises(ValueError, match="runtime version changed"):
        _collect_fixture(fixture)
    fixture["state"]["runtime"] = {"version": "unit-fixture-runtime"}
    monkeypatch.setattr(
        runner,
        "_model_metadata",
        lambda endpoint, names: {
            name: {"tag": {"digest": "changed-fixture-model"}} for name in names
        },
    )
    with pytest.raises(ValueError, match="model tag changed"):
        _collect_fixture(fixture)
    assert len(fixture["state"]["calls"]) == before


def test_transport_failure_keeps_unknown_tokens_missing(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("unit fixture transport failure")

    monkeypatch.setattr(ollama, "request_json", unavailable)
    final, stop, record = ollama.run_tool_loop(
        "unit fixture", [], lambda action: {}, model="fixture"
    )
    assert final == "" and stop == "error"
    assert record["prompt_tokens"] is None and record["completion_tokens"] is None
    assert len(record["requests"]) == 1 and record["responses"] == []
    assert "unit fixture transport failure" in record["error"]


def test_one_missing_token_field_does_not_invent_a_zero(monkeypatch):
    response = {
        "message": {"role": "assistant", "content": "fixture"},
        "done": True,
        "prompt_eval_count": 7,
    }
    monkeypatch.setattr(ollama, "request_json", lambda *args, **kwargs: response)
    _, stop, record = ollama.run_tool_loop("unit fixture", [], lambda action: {}, model="fixture")
    assert stop == "completed"
    assert record["prompt_tokens"] == 7 and record["completion_tokens"] is None
