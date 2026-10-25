from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from gatebench.report import write_report
from gatebench.statistics import summarize


def row(task, probe, expected, baseline, hardened=False, *, family="refund", split="dev"):
    return {
        "task_id": task,
        "family": family,
        "split": split,
        "probe": probe,
        "expected": expected,
        "graders": {"goal": baseline, "hardened": hardened},
        "rationale": "A separately specified policy witness.",
    }


def test_confusion_matrix_uses_correct_denominators():
    rows = [
        row("a", "valid", True, True, True),
        row("a", "alternative", True, False, True),
        row("a", "unsafe", False, True),
        row("a", "incomplete", False, False),
    ]
    result = summarize(rows, bootstrap_samples=20)
    metric = result["graders"]["goal"]
    assert metric["true_positive"] == 1
    assert metric["true_negative"] == 1
    assert metric["false_positive"] == 1
    assert metric["false_negative"] == 1
    assert metric["false_acceptance"] == 0.5
    assert metric["false_rejection"] == 0.5
    assert metric["accuracy"] == 0.5
    assert metric["false_acceptance_ci"] == [0.5, 0.5]
    assert result["corpus"] == {
        "episodes": 4,
        "tasks": 1,
        "positives": 2,
        "negatives": 2,
        "families": ["refund"],
        "splits": ["dev"],
    }


def test_cluster_bootstrap_keeps_all_correlated_siblings_together():
    rows = [row("all-wrong", f"mutation-{i}", False, True) for i in range(10)]
    rows.append(row("all-correct", "mutation-0", False, False))
    result = summarize(rows, bootstrap_samples=1000, seed=2)
    metric = result["graders"]["goal"]
    # The point estimate weights episodes. Whole-case draws can contain only
    # the correct cluster or only the incorrect cluster, so the CI spans 0..1.
    assert metric["false_acceptance"] == 10 / 11
    assert metric["false_acceptance_ci"] == [0.0, 1.0]
    paired = result["paired_false_acceptance_difference_vs_hardened"]["goal"]
    assert paired["difference"] == 10 / 11
    assert paired["ci"] == [0.0, 1.0]
    assert paired["tasks"] == 2


def test_paired_interval_uses_identical_draws_for_both_graders():
    rows = [row("a", "unsafe", False, True, True), row("b", "unsafe", False, False, False)]
    result = summarize(rows, bootstrap_samples=200, seed=77)
    assert result["graders"]["goal"]["false_acceptance_ci"] == [0.0, 1.0]
    assert result["paired_false_acceptance_difference_vs_hardened"]["goal"] == {
        "difference": 0.0,
        "ci": [0.0, 0.0],
        "tasks": 2,
    }


def test_absent_denominators_are_not_reported_as_zero_errors():
    result = summarize([row("a", "valid", True, False, True)], bootstrap_samples=25)
    for name in ("goal", "hardened"):
        assert result["graders"][name]["negative_count"] == 0
        assert result["graders"][name]["false_acceptance"] is None
        assert result["graders"][name]["false_acceptance_ci"] is None
        assert result["paired_false_acceptance_difference_vs_hardened"][name]["difference"] is None
    assert result["graders"]["goal"]["false_rejection"] == 1.0


def test_empty_corpus_and_disabled_bootstrap():
    empty = summarize([])
    assert empty["corpus"]["episodes"] == 0
    assert empty["corpus"]["tasks"] == 0
    assert empty["graders"] == {}
    assert empty["paired_false_acceptance_difference_vs_hardened"] == {}
    result = summarize([row("a", "unsafe", False, True)], bootstrap_samples=0)
    assert result["graders"]["goal"]["false_acceptance"] == 1.0
    assert result["graders"]["goal"]["false_acceptance_ci"] is None


def test_slices_preserve_denominators_and_pairing():
    rows = [
        row("a", "unsafe", False, True),
        row("b", "valid", True, True, True, family="exchange", split="eval"),
    ]
    result = summarize(rows, bootstrap_samples=20)
    assert result["slices"]["family"]["refund"]["graders"]["goal"]["negative_count"] == 1
    assert result["slices"]["family"]["exchange"]["graders"]["goal"]["negative_count"] == 0
    assert result["slices"]["split"]["eval"]["corpus"]["positives"] == 1
    assert result["slices"]["split"]["dev"]["corpus"]["negatives"] == 1


def test_reproducible_under_input_reordering():
    rows = [row(str(i), "unsafe", False, i % 3 == 0) for i in range(12)]
    assert summarize(rows, bootstrap_samples=100) == summarize(
        list(reversed(rows)), bootstrap_samples=100
    )


@pytest.mark.parametrize("samples", [-1, True, 2.5])
def test_invalid_bootstrap_sample_count(samples):
    with pytest.raises(ValueError, match="bootstrap_samples"):
        summarize([], bootstrap_samples=samples)


def test_duplicate_controls_cannot_silently_reweight_results():
    control = row("a", "unsafe", False, True)
    with pytest.raises(ValueError, match="Duplicate"):
        summarize([control, control])


def test_grader_names_must_be_paired_across_all_controls():
    controls = [row("a", "unsafe", False, True), row("b", "unsafe", False, False)]
    del controls[1]["graders"]["goal"]
    with pytest.raises(ValueError, match="same paired graders"):
        summarize(controls)


def test_task_cluster_cannot_silently_merge_different_splits():
    controls = [row("a", "one", False, True), row("a", "two", False, True, split="eval")]
    with pytest.raises(ValueError, match="cannot span"):
        summarize(controls)


@pytest.mark.parametrize("field", ["expected", "grader"])
def test_numeric_labels_are_rejected(field):
    control = row("a", "unsafe", False, True)
    if field == "expected":
        control["expected"] = 0
    else:
        control["graders"]["goal"] = 1
    with pytest.raises(ValueError, match="booleans"):
        summarize([control])


def test_report_artifacts_derive_counts_and_escape_untrusted_text(tmp_path):
    control = row("a", "<script>alert('probe')</script>", False, True)
    control["rationale"] = "</small><img src=x onerror=alert('rationale')>"
    summary = summarize([control], bootstrap_samples=10)
    write_report(summary, [control], tmp_path)
    markdown = (tmp_path / "report.md").read_text()
    page = (tmp_path / "report.html").read_text()
    assert "1 task instances, 1 executable controls; 0 valid and 1 invalid" in markdown
    assert "100.0% (1/1)" in page
    assert "scripted controls, not model benchmark results" in markdown
    assert "<script>alert('probe')</script>" not in page
    assert "<img src=x" not in page
    assert "&lt;script&gt;" in page
    assert "cdn" not in page.lower()
    assert "https://" not in page
    assert "http://" not in page.replace("http://www.w3.org/2000/svg", "")
    ET.fromstring((tmp_path / "error-rates.svg").read_text())
    assert json.loads((tmp_path / "report-data.json").read_text()) == summary


def test_empty_report_still_renders(tmp_path):
    summary = summarize([])
    write_report(summary, [], tmp_path)
    assert "No audit episodes were recorded" in (tmp_path / "report.html").read_text()
    ET.fromstring((tmp_path / "error-rates.svg").read_text())
