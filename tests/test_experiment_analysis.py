from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from gatebench.experiments.analysis import summarize_trials


def trials(
    model="small", task="a", successes=(True, True, True), *, family="refund", domain="gatebench"
):
    return [
        {
            "trial_id": f"{domain}/{model}/{task}/{repeat}",
            "task_id": task,
            "family": family,
            "model": model,
            "domain": domain,
            "repeat": repeat,
            "decode_seed": [17, 29, 43][repeat],
            "stop_reason": "completed",
            "graders": {"goal": True, "hardened": passed},
            "elapsed_seconds": float(repeat + 1),
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }
        for repeat, passed in enumerate(successes)
    ]


def test_exact_repeated_success_is_not_any_of_three_or_power_of_mean():
    rows = trials(task="two", successes=(True, True, False))
    result = summarize_trials(rows, bootstrap_samples=10)
    metric = result["models"]["small"]["consistency"]["hardened"]
    assert metric["pass^1"] == {"estimate": 2 / 3, "ci": [2 / 3, 2 / 3]}
    assert metric["pass^2"] == {"estimate": 1 / 3, "ci": [1 / 3, 1 / 3]}
    assert metric["pass^3"] == {"estimate": 0.0, "ci": [0.0, 0.0]}


def test_success_and_consistency_average_whole_tasks():
    rows = trials(task="a") + trials(task="b", successes=(True, True, False))
    model = summarize_trials(rows, bootstrap_samples=20)["models"]["small"]
    assert model["graders"]["hardened"]["passed"] == 5
    assert model["graders"]["hardened"]["trials"] == 6
    assert model["graders"]["hardened"]["rate"] == 5 / 6
    assert model["consistency"]["hardened"]["pass^2"]["estimate"] == 2 / 3
    assert model["consistency"]["hardened"]["pass^3"]["estimate"] == 0.5


def test_model_trace_metrics_are_disagreements_not_claimed_error_rates():
    rows = trials(successes=(True, False, False))
    rows[0]["graders"]["goal"] = False
    model = summarize_trials(rows, bootstrap_samples=20)["models"]["small"]
    assert model["disagreements_vs_hardened"]["goal"] == {
        "grader_only_pass": 2,
        "hardened_only_pass": 1,
        "both_pass": 0,
        "both_fail": 0,
        "trials": 3,
        "rate": 2 / 3,
        "ci": [2 / 3, 2 / 3],
    }
    assert "false_positive" not in json.dumps(model)
    assert "false_acceptance" not in json.dumps(model)


def test_bootstrap_keeps_all_repetitions_and_paired_models_together():
    rows = []
    for model in ("a", "b"):
        rows += trials(model, "pass", (True, True, True))
        rows += trials(model, "fail", (False, False, False))
    result = summarize_trials(rows, bootstrap_samples=300, seed=5)
    assert result["models"]["a"]["graders"]["hardened"]["ci"] == [0.0, 1.0]
    assert result["paired_model_differences"] == [
        {
            "model_a": "a",
            "model_b": "b",
            "direction": "model_b minus model_a",
            "task_clusters": 2,
            "graders": {
                "goal": {"difference": 0.0, "ci": [0.0, 0.0]},
                "hardened": {"difference": 0.0, "ci": [0.0, 0.0]},
            },
        }
    ]


def test_paired_direction_is_explicit_and_task_coverage_is_shared():
    result = summarize_trials(
        trials("a", successes=(False, False, False)) + trials("b"),
        bootstrap_samples=10,
    )
    comparison = result["paired_model_differences"][0]
    assert comparison["graders"]["hardened"] == {"difference": 1.0, "ci": [1.0, 1.0]}


def test_bootstrap_and_input_order_are_reproducible():
    rows = trials("a", "a") + trials("a", "b", (True, False, False))
    rows += trials("b", "a", (True, True, False)) + trials("b", "b")
    expected = summarize_trials(rows, bootstrap_samples=50, seed=43)
    shuffled = copy.deepcopy(rows)
    random.Random(9).shuffle(shuffled)
    assert summarize_trials(shuffled, bootstrap_samples=50, seed=43) == expected


def test_disabling_bootstrap_does_not_invent_zero_uncertainty():
    result = summarize_trials(trials(), bootstrap_samples=0)
    model = result["models"]["small"]
    assert model["graders"]["goal"]["ci"] is None
    assert model["consistency"]["hardened"]["pass^3"]["ci"] is None


def test_consistency_above_available_repeat_count_is_undefined():
    result = summarize_trials(trials(successes=(True,)), repeats=1, bootstrap_samples=10)
    model = result["models"]["small"]
    assert model["consistency"]["hardened"]["pass^1"]["estimate"] == 1.0
    assert model["consistency"]["hardened"]["pass^2"] == {"estimate": None, "ci": None}
    assert model["consistency"]["hardened"]["pass^3"] == {"estimate": None, "ci": None}


def test_token_reporting_preserves_missing_data_and_coverage():
    rows = trials()
    rows[0]["prompt_tokens"] = None
    for row in rows:
        row["completion_tokens"] = None
    model = summarize_trials(rows, bootstrap_samples=0)["models"]["small"]
    assert model["tokens"] == {
        "prompt_tokens": {"total": 200, "reported_trials": 2},
        "completion_tokens": {"total": None, "reported_trials": 0},
    }
    assert model["latency_seconds"] == {"total": 6.0, "mean": 2.0, "median": 2.0, "p95": 2.9}


def test_domain_and_workflow_slices_do_not_mix_same_named_tasks():
    rows = trials(task="same", domain="gatebench") + trials(
        task="same", domain="tau", family="cancel", successes=(False, False, False)
    )
    result = summarize_trials(rows, bootstrap_samples=0)
    assert result["corpus"]["task_clusters"] == 2
    assert result["corpus"]["domains"] == ["gatebench", "tau"]
    model = result["models"]["small"]
    assert model["domain"]["gatebench"]["graders"]["hardened"]["rate"] == 1.0
    assert model["domain"]["tau"]["graders"]["hardened"]["rate"] == 0.0
    assert model["family"]["cancel"]["trials"] == 3


def test_missing_repetition_is_an_error_instead_of_dropped_task():
    with pytest.raises(ValueError, match="repeat|incomplete"):
        summarize_trials(trials()[:-1])


def test_missing_model_task_pair_is_an_error():
    rows = trials("a", "a") + trials("a", "b") + trials("b", "a")
    with pytest.raises(ValueError, match="incomplete trial matrix"):
        summarize_trials(rows)


def test_wholly_missing_planned_model_or_task_is_detected():
    with pytest.raises(ValueError, match="model matrix"):
        summarize_trials(trials(), expected_models=["small", "missing"])
    with pytest.raises(ValueError, match="task matrix"):
        summarize_trials(trials(), expected_task_ids=["a", "missing"])
    summarize_trials(
        trials(), expected_models=["small"], expected_task_ids=["a"], bootstrap_samples=0
    )


def test_duplicate_trial_id_and_repeated_slot_are_both_rejected():
    rows = trials()
    with pytest.raises(ValueError, match="duplicate trial_id"):
        summarize_trials(rows + [copy.deepcopy(rows[0])])
    duplicate = copy.deepcopy(rows[0])
    duplicate["trial_id"] = "different-id"
    with pytest.raises(ValueError, match="duplicate model/task/repeat"):
        summarize_trials(rows + [duplicate])


@pytest.mark.parametrize(
    "field,value",
    [
        ("trial_id", ""),
        ("repeat", True),
        ("repeat", 3),
        ("repeat", -1),
        ("decode_seed", -1),
        ("decode_seed", True),
        ("elapsed_seconds", float("nan")),
        ("elapsed_seconds", float("inf")),
        ("elapsed_seconds", -1),
        ("elapsed_seconds", True),
        ("prompt_tokens", True),
        ("completion_tokens", -1),
        ("stop_reason", "unknown"),
        ("graders", {"goal": 1, "hardened": False}),
        ("graders", {"goal": False}),
        ("domain", ""),
    ],
)
def test_malformed_trial_rows_fail_clearly(field, value):
    rows = trials()
    rows[0][field] = value
    with pytest.raises(ValueError):
        summarize_trials(rows)


def test_seed_schedule_must_be_distinct_and_match_every_task():
    rows = trials(task="a") + trials(task="b")
    rows[-1]["decode_seed"] = 999
    with pytest.raises(ValueError, match="same decode seed"):
        summarize_trials(rows)
    rows = trials()
    rows[-1]["decode_seed"] = 17
    with pytest.raises(ValueError, match="distinct decode seed"):
        summarize_trials(rows)


def test_family_and_grader_sets_must_be_consistent():
    rows = trials()
    rows[0]["family"] = "exchange"
    with pytest.raises(ValueError, match="same workflow"):
        summarize_trials(rows)
    rows = trials()
    rows[0]["graders"]["extra"] = False
    with pytest.raises(ValueError, match="same paired graders"):
        summarize_trials(rows)


def test_budget_with_complete_business_goal_remains_failed_completion():
    rows = trials()
    rows[0]["stop_reason"] = "budget"
    with pytest.raises(ValueError, match="unfinished trial"):
        summarize_trials(rows)
    rows[0]["graders"]["hardened"] = False
    result = summarize_trials(rows, bootstrap_samples=0)
    model = result["models"]["small"]
    assert model["stop_reasons"] == {"budget": 1, "completed": 2}
    assert model["disagreements_vs_hardened"]["goal"]["grader_only_pass"] == 1


@pytest.mark.parametrize(
    "argument,value", [("repeats", 0), ("repeats", True), ("bootstrap_samples", -1), ("seed", True)]
)
def test_invalid_analysis_configuration_is_rejected(argument, value):
    with pytest.raises(ValueError):
        summarize_trials(trials(), **{argument: value})


def test_empty_study_is_not_a_successful_run():
    with pytest.raises(ValueError, match="must contain"):
        summarize_trials([])


def test_checked_in_primary_plan_has_a_complete_fixed_matrix():
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "configs/real-model-study.json").read_text()
    )
    selection = config["task_selection"]
    assert (
        len(config["models"])
        * len(selection["families"])
        * len(selection["seeds"])
        * len(config["repetitions"]["decode_seeds"])
        == 72
    )
    assert config["pilot"]["seed"] not in selection["seeds"]
    assert config["generation"]["temperature"] > 0
    assert config["generation"]["think"] is False
    assert all("q4_K_M" in model for model in config["models"])
