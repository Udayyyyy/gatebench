"""Analyze a complete repeated-trial study without treating a grader as truth."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import combinations
from statistics import mean, median
from typing import Any

Cluster = tuple[str, str]
Metric = tuple[str, str]


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _interval(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [_percentile(values, 0.025), _percentile(values, 0.975)]


def _validate(
    rows: list[dict[str, Any]],
    expected_models: Sequence[str] | None,
    expected_task_ids: Sequence[str] | None,
    repeats: int,
) -> tuple[list[str], list[str], list[Cluster]]:
    if not rows:
        raise ValueError("a model study must contain trials")
    seen_trials: set[str] = set()
    groups: dict[tuple[str, Cluster], set[int]] = defaultdict(set)
    families: dict[Cluster, str] = {}
    repeat_seeds: dict[int, int] = {}
    grader_names: set[str] | None = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("trial rows must be objects")
        for field in ("trial_id", "task_id", "family", "model", "stop_reason"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"trial field {field!r} must be a nonempty string")
        domain = row.get("domain", "gatebench")
        if not isinstance(domain, str) or not domain:
            raise ValueError("domain must be a nonempty string")
        if row["trial_id"] in seen_trials:
            raise ValueError(f"duplicate trial_id: {row['trial_id']}")
        seen_trials.add(row["trial_id"])
        repeat = row.get("repeat")
        if type(repeat) is not int or not 0 <= repeat < repeats:
            raise ValueError(f"repeat must be an integer in 0..{repeats - 1}")
        decode_seed = row.get("decode_seed")
        if type(decode_seed) is not int or decode_seed < 0:
            raise ValueError("decode_seed must be a nonnegative integer")
        prior_seed = repeat_seeds.setdefault(repeat, decode_seed)
        if prior_seed != decode_seed:
            raise ValueError("each repeat index must use the same decode seed across the study")
        cluster = (domain, row["task_id"])
        group = (row["model"], cluster)
        if repeat in groups[group]:
            raise ValueError(f"duplicate model/task/repeat: {group}/{repeat}")
        groups[group].add(repeat)
        prior_family = families.setdefault(cluster, row["family"])
        if prior_family != row["family"]:
            raise ValueError("a task must have the same workflow across all models/repeats")
        if row["stop_reason"] not in ("completed", "budget", "error"):
            raise ValueError("unknown stop_reason")
        elapsed = row.get("elapsed_seconds")
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError("elapsed_seconds must be finite and nonnegative")
        for field in ("prompt_tokens", "completion_tokens"):
            value = row.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field} must be a nonnegative integer or null")
        graders = row.get("graders")
        if not isinstance(graders, dict) or not graders:
            raise ValueError("each trial requires grader verdicts")
        if any(not isinstance(name, str) or not name for name in graders):
            raise ValueError("grader names must be nonempty strings")
        if any(type(verdict) is not bool for verdict in graders.values()):
            raise ValueError("grader verdicts must be booleans")
        if "hardened" not in graders:
            raise ValueError("hardened reference verdict is required for disagreement analysis")
        names = set(graders)
        if grader_names is None:
            grader_names = names
        elif grader_names != names:
            raise ValueError("all trials must contain the same paired graders")
        if row["stop_reason"] != "completed" and graders["hardened"]:
            raise ValueError("an unfinished trial cannot pass the hardened verifier")
    if len(repeat_seeds) != repeats:
        raise ValueError("incomplete repetition schedule")
    if len(set(repeat_seeds.values())) != repeats:
        raise ValueError("each repetition needs a distinct decode seed")

    models = sorted({model for model, _ in groups})
    clusters = sorted(families)
    if expected_models is not None:
        if len(set(expected_models)) != len(expected_models) or set(models) != set(expected_models):
            raise ValueError("trial models do not match the prespecified model matrix")
    if expected_task_ids is not None:
        if len(set(expected_task_ids)) != len(expected_task_ids) or {
            task_id for _, task_id in clusters
        } != set(expected_task_ids):
            raise ValueError("trial tasks do not match the prespecified task matrix")
    wanted_repeats = set(range(repeats))
    for model in models:
        for cluster in clusters:
            if groups.get((model, cluster)) != wanted_repeats:
                raise ValueError(f"incomplete trial matrix for {model}/{cluster}")
    return models, sorted(grader_names or ()), clusters


def _values(rows: list[dict[str, Any]], names: list[str], repeats: int) -> dict[Metric, float]:
    values: dict[Metric, float] = {}
    reference = [row["graders"]["hardened"] for row in rows]
    for name in names:
        passes = [row["graders"][name] for row in rows]
        successes = sum(passes)
        values[("success", name)] = successes / repeats
        values[("disagreement", name)] = (
            sum(passed and not hardened for passed, hardened in zip(passes, reference, strict=True))
            / repeats
        )
        for k in range(1, min(3, repeats) + 1):
            values[(f"pass^{k}", name)] = math.comb(successes, k) / math.comb(repeats, k)
    return values


def _point_summary(rows: list[dict[str, Any]], names: list[str], repeats: int) -> dict[str, Any]:
    groups: dict[Cluster, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row.get("domain", "gatebench"), row["task_id"])].append(row)
    vectors = [_values(group, names, repeats) for _, group in sorted(groups.items())]
    reference = [row["graders"]["hardened"] for row in rows]
    graders: dict[str, Any] = {}
    consistency: dict[str, Any] = {}
    disagreements: dict[str, Any] = {}
    for name in names:
        passes = [row["graders"][name] for row in rows]
        graders[name] = {
            "passed": sum(passes),
            "trials": len(rows),
            "rate": sum(passes) / len(rows),
            "ci": None,
        }
        consistency[name] = {
            f"pass^{k}": {
                "estimate": mean(vector[(f"pass^{k}", name)] for vector in vectors)
                if k <= repeats
                else None,
                "ci": None,
            }
            for k in range(1, 4)
        }
        cells = Counter(zip(passes, reference, strict=True))
        disagreements[name] = {
            "grader_only_pass": cells[(True, False)],
            "hardened_only_pass": cells[(False, True)],
            "both_pass": cells[(True, True)],
            "both_fail": cells[(False, False)],
            "trials": len(rows),
            "rate": cells[(True, False)] / len(rows),
            "ci": None,
        }
    elapsed = [float(row["elapsed_seconds"]) for row in rows]
    tokens = {}
    for field in ("prompt_tokens", "completion_tokens"):
        known = [row[field] for row in rows if row.get(field) is not None]
        tokens[field] = {"total": sum(known) if known else None, "reported_trials": len(known)}
    return {
        "trials": len(rows),
        "task_clusters": len(groups),
        "graders": graders,
        "consistency": consistency,
        "disagreements_vs_hardened": disagreements,
        "stop_reasons": dict(sorted(Counter(row["stop_reason"] for row in rows).items())),
        "latency_seconds": {
            "total": sum(elapsed),
            "mean": mean(elapsed),
            "median": median(elapsed),
            "p95": _percentile(elapsed, 0.95),
        },
        "tokens": tokens,
    }


def summarize_trials(
    rows: list[dict[str, Any]],
    *,
    expected_models: Sequence[str] | None = None,
    expected_task_ids: Sequence[str] | None = None,
    repeats: int = 3,
    bootstrap_samples: int = 2000,
    seed: int = 17,
) -> dict[str, Any]:
    """Summarize a complete, paired model × task × repetition matrix.

    Rates describe grader decisions on actual model traces. They are not false
    acceptance rates: a reference verifier is not independent ground truth.
    Every bootstrap draw retains all repetitions of a sampled task and uses
    the same task IDs for every model and grader.
    """
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if type(bootstrap_samples) is not int or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer")
    if type(seed) is not int:
        raise ValueError("bootstrap seed must be an integer")
    models, names, clusters = _validate(rows, expected_models, expected_task_ids, repeats)
    ordered = sorted(
        rows, key=lambda r: (r["model"], r.get("domain", "gatebench"), r["task_id"], r["repeat"])
    )
    by_model = {model: [row for row in ordered if row["model"] == model] for model in models}
    summary: dict[str, Any] = {
        "schema_version": 1,
        "kind": "real_model_study",
        "corpus": {
            "trials": len(rows),
            "models": models,
            "task_clusters": len(clusters),
            "domains": sorted({domain for domain, _ in clusters}),
            "repeats": repeats,
            "decode_seeds_by_repeat": {str(row["repeat"]): row["decode_seed"] for row in ordered},
        },
        "bootstrap": {
            "unit": "domain+task_id",
            "samples": bootstrap_samples,
            "seed": seed,
            "confidence": 0.95,
            "method": "paired case-cluster percentile; all repetitions retained",
        },
        "models": {
            model: _point_summary(group, names, repeats) for model, group in by_model.items()
        },
        "paired_model_differences": [],
    }
    vectors: dict[str, list[dict[Metric, float]]] = {}
    for model, group in by_model.items():
        grouped: dict[Cluster, list[dict[str, Any]]] = defaultdict(list)
        for row in group:
            grouped[(row.get("domain", "gatebench"), row["task_id"])].append(row)
        vectors[model] = [_values(grouped[cluster], names, repeats) for cluster in clusters]
        for dimension in ("family", "domain"):
            slices: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in group:
                slices[row.get(dimension, "gatebench")].append(row)
            summary["models"][model][dimension] = {
                value: _point_summary(selected, names, repeats)
                for value, selected in sorted(slices.items())
            }

    metrics = list(vectors[models[0]][0])
    draws: dict[str, dict[Metric, list[float]]] = {
        model: {metric: [] for metric in metrics} for model in models
    }
    pairs = list(combinations(models, 2))
    paired_draws: dict[tuple[str, str], dict[str, list[float]]] = {
        pair: {name: [] for name in names} for pair in pairs
    }
    rng = random.Random(seed)
    for _ in range(bootstrap_samples):
        sampled = [rng.randrange(len(clusters)) for _ in clusters]
        estimates = {
            model: {
                metric: mean(vectors[model][index][metric] for index in sampled)
                for metric in metrics
            }
            for model in models
        }
        for model in models:
            for metric in metrics:
                draws[model][metric].append(estimates[model][metric])
        for first, second in pairs:
            for name in names:
                paired_draws[(first, second)][name].append(
                    estimates[second][("success", name)] - estimates[first][("success", name)]
                )

    for model in models:
        current = summary["models"][model]
        for name in names:
            current["graders"][name]["ci"] = _interval(draws[model][("success", name)])
            current["disagreements_vs_hardened"][name]["ci"] = _interval(
                draws[model][("disagreement", name)]
            )
            for k in range(1, min(3, repeats) + 1):
                current["consistency"][name][f"pass^{k}"]["ci"] = _interval(
                    draws[model][(f"pass^{k}", name)]
                )
    for first, second in pairs:
        summary["paired_model_differences"].append(
            {
                "model_a": first,
                "model_b": second,
                "direction": "model_b minus model_a",
                "task_clusters": len(clusters),
                "graders": {
                    name: {
                        "difference": summary["models"][second]["graders"][name]["rate"]
                        - summary["models"][first]["graders"][name]["rate"],
                        "ci": _interval(paired_draws[(first, second)][name]),
                    }
                    for name in names
                },
            }
        )
    return summary
