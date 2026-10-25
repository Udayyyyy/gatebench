"""Paired, case-cluster summaries for the verifier audit.

Probes derived from one task are correlated. Resampling individual rows would
make the uncertainty look smaller simply by adding more mutations of one case.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _quantile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _interval(values: Iterable[float | None]) -> list[float] | None:
    finite = sorted(value for value in values if value is not None)
    if not finite:
        return None
    return [_quantile(finite, 0.025), _quantile(finite, 0.975)]


def _validate(rows: list[dict[str, Any]]) -> list[str]:
    names: set[str] | None = None
    seen: set[tuple[str, str]] = set()
    task_metadata: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Each audit row must be a mapping")
        for field in ("task_id", "family", "split", "probe"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"Row field {field!r} must be a nonempty string")
        if type(row.get("expected")) is not bool:
            raise ValueError("Expected labels must be booleans")
        graders = row.get("graders")
        if not isinstance(graders, Mapping) or not graders:
            raise ValueError("Each row needs at least one grader verdict")
        if any(not isinstance(name, str) or not name for name in graders):
            raise ValueError("Grader names must be nonempty strings")
        if any(type(value) is not bool for value in graders.values()):
            raise ValueError("Grader verdicts must be booleans")
        current_names = set(graders)
        if names is None:
            names = current_names
        elif names != current_names:
            raise ValueError("All rows must contain the same paired graders")
        key = (row["task_id"], row["probe"])
        if key in seen:
            raise ValueError(f"Duplicate task/probe pair: {key}")
        seen.add(key)
        metadata = (row["family"], row["split"])
        previous = task_metadata.setdefault(row["task_id"], metadata)
        if previous != metadata:
            raise ValueError("A task_id cannot span different families or splits")
    return sorted(names or ())


def _counts(rows: list[dict[str, Any]], names: list[str]) -> dict[str, list[int]]:
    # Tuple order: true positive, true negative, false positive, false negative.
    result = {name: [0, 0, 0, 0] for name in names}
    for row in rows:
        for name in names:
            passed = row["graders"][name]
            expected = row["expected"]
            cell = (
                0
                if expected and passed
                else 1
                if not expected and not passed
                else 2
                if passed
                else 3
            )
            result[name][cell] += 1
    return result


def _metrics(counts: list[int]) -> dict[str, Any]:
    true_positive, true_negative, false_positive, false_negative = counts
    positive_count = true_positive + false_negative
    negative_count = true_negative + false_positive
    return {
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "false_acceptance": _ratio(false_positive, negative_count),
        "false_rejection": _ratio(false_negative, positive_count),
        "false_acceptance_ci": None,
        "false_rejection_ci": None,
        "accuracy": _ratio(true_positive + true_negative, positive_count + negative_count),
    }


def _corpus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episodes": len(rows),
        "tasks": len({row["task_id"] for row in rows}),
        "positives": sum(row["expected"] for row in rows),
        "negatives": sum(not row["expected"] for row in rows),
        "families": sorted({row["family"] for row in rows}),
        "splits": sorted({row["split"] for row in rows}),
    }


def _point_summary(rows: list[dict[str, Any]], names: list[str]) -> dict[str, Any]:
    return {
        "corpus": _corpus(rows),
        "graders": {name: _metrics(count) for name, count in _counts(rows, names).items()},
    }


def summarize(
    rows: list[dict[str, Any]], *, bootstrap_samples: int = 2000, seed: int = 17
) -> dict[str, Any]:
    """Summarize independently labeled controls, resampling whole task IDs.

    Estimates are episode-weighted ratios, not a mean of task-level rates. The
    same sampled task IDs are used for every grader and its paired difference.
    The intervals describe sensitivity to this generated case mix; they are not
    confidence intervals for real-world agent failure rates.
    """
    if type(bootstrap_samples) is not int or bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be a nonnegative integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    names = _validate(rows)
    summary = _point_summary(rows, names)
    summary["schema_version"] = 1
    summary["bootstrap"] = {
        "unit": "task_id",
        "samples": bootstrap_samples,
        "seed": seed,
        "confidence": 0.95,
        "method": "paired case-cluster percentile; episode-weighted ratio of counts",
    }
    summary["slices"] = {}
    for dimension in ("family", "split"):
        slices: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            slices[row[dimension]].append(row)
        summary["slices"][dimension] = {
            value: _point_summary(group, names) for value, group in sorted(slices.items())
        }

    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        clusters[row["task_id"]].append(row)
    cluster_counts = [_counts(clusters[key], names) for key in sorted(clusters)]
    draws: dict[str, dict[str, list[float | None]]] = {
        name: {"acceptance": [], "rejection": [], "paired": []} for name in names
    }
    rng = random.Random(seed)
    if cluster_counts:
        for _ in range(bootstrap_samples):
            totals = {name: [0, 0, 0, 0] for name in names}
            for _cluster in range(len(cluster_counts)):
                sampled = cluster_counts[rng.randrange(len(cluster_counts))]
                for name in names:
                    for cell in range(4):
                        totals[name][cell] += sampled[name][cell]
            rates: dict[str, float | None] = {}
            for name, count in totals.items():
                acceptance = _ratio(count[2], count[1] + count[2])
                draws[name]["acceptance"].append(acceptance)
                draws[name]["rejection"].append(_ratio(count[3], count[0] + count[3]))
                rates[name] = acceptance
            if "hardened" in rates:
                reference = rates["hardened"]
                for name, rate in rates.items():
                    paired = (
                        rate - reference if rate is not None and reference is not None else None
                    )
                    draws[name]["paired"].append(paired)

    for name in names:
        summary["graders"][name]["false_acceptance_ci"] = _interval(draws[name]["acceptance"])
        summary["graders"][name]["false_rejection_ci"] = _interval(draws[name]["rejection"])
    summary["paired_false_acceptance_difference_vs_hardened"] = {}
    if "hardened" in names:
        reference = summary["graders"]["hardened"]["false_acceptance"]
        for name in names:
            rate = summary["graders"][name]["false_acceptance"]
            difference = rate - reference if rate is not None and reference is not None else None
            summary["paired_false_acceptance_difference_vs_hardened"][name] = {
                "difference": difference,
                "ci": _interval(draws[name]["paired"]),
                "tasks": len(cluster_counts),
            }
    return summary
