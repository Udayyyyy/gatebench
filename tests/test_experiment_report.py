from __future__ import annotations

import copy
import csv
import html
from html.parser import HTMLParser

import pytest

from gatebench.experiments.analysis import summarize_trials
from gatebench.experiments.report import write_study_report


def recorded_fixture():
    """Synthetic renderer fixture; these rows are never published as model results."""
    rows = []
    for model_index, model in enumerate(("qwen3.5:2b-q4_K_M", "qwen3.5:4b-q4_K_M")):
        for task_index, family in enumerate(("refund", "exchange")):
            for repeat, seed in enumerate((17, 29, 43)):
                passed = (
                    repeat == 0
                    or (model_index == 0 and task_index == 1)
                    or (model_index == 1 and (repeat == 1 or task_index == 0))
                )
                rows.append(
                    {
                        "trial_id": f"model-{model_index}-task-{task_index}-repeat-{repeat}",
                        "task_id": f"task-{task_index}",
                        "family": family,
                        "model": model,
                        "repeat": repeat,
                        "decode_seed": seed,
                        "stop_reason": "completed",
                        "graders": {"goal": True, "final_state": True, "hardened": passed},
                        "elapsed_seconds": float(repeat + 1),
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "model_digest": "sha256:" + str(model_index) * 64,
                        "reasons": {
                            "hardened": []
                            if passed
                            else ["history.event[2].authentication: write preceded verification"]
                        },
                        "artifact": f"trials/model-{model_index}-task-{task_index}-repeat-{repeat}.json.gz",
                    }
                )
    return rows


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href"))
        if tag == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)


def test_reports_show_observed_counts_and_complete_repeated_success(tmp_path):
    rows = recorded_fixture()
    summary = summarize_trials(rows, bootstrap_samples=20)
    write_study_report(summary, rows, tmp_path)
    markdown = (tmp_path / "real-model-report.md").read_text()
    page = (tmp_path / "real-model-report.html").read_text()
    assert "12 trials; 2 model packages; 2 task clusters; 3 repetitions" in markdown
    assert "12 trials · 2 model packages · 2 task clusters · 3 repetitions" in page
    assert "4/6 (66.7%)" in markdown
    assert "5/6 (83.3%)" in markdown
    assert "pass^1" in markdown and "pass^2" in markdown and "pass^3" in markdown
    assert "not any-of-three success" in markdown
    assert "Q4_K_M quantization" in page
    assert "not a broad model leaderboard" in markdown
    assert (
        "false-positive rates" in markdown
    )  # The qualification is explicit, not a metric heading.


def test_every_outcome_acceptance_disagreement_is_listed_with_evidence(tmp_path):
    rows = recorded_fixture()
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    page = (tmp_path / "real-model-report.html").read_text()
    section = page.split('<section id="disagreements">', 1)[1].split("</section>", 1)[0]
    disagreements = [
        row for row in rows if row["graders"]["final_state"] and not row["graders"]["hardened"]
    ]
    assert f"All {len(disagreements)} trials" in section
    for row in disagreements:
        assert row["trial_id"] in section
        assert row["artifact"] in section
        assert row["reasons"]["hardened"][0] in section
    assert "no reason recorded" not in section


def test_native_domain_reports_the_environment_component_without_claiming_full_score(tmp_path):
    rows = recorded_fixture()
    for row in rows:
        row["domain"] = "tau2-retail"
        row["graders"] = {"native": True, "hardened": row["graders"]["hardened"]}
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    page = (tmp_path / "real-model-report.html").read_text()
    markdown = (tmp_path / "real-model-report.md").read_text()
    assert "native acceptance disagreements" in page
    assert "unchanged upstream environment/database evaluator component" in page
    assert "not the full upstream benchmark score" in page
    assert "natural-language assertions and confirmation checks are not assessed" in markdown
    assert "tau2-retail" in markdown


def test_labels_reasons_and_digest_attributes_are_escaped(tmp_path):
    rows = recorded_fixture()
    malicious = '<script>alert("model")</script>|`name`'
    for row in rows:
        if row["model"] == "qwen3.5:2b-q4_K_M":
            row["model"] = malicious
        row["model_digest"] = '" onmouseover="alert(1)'
        row["reasons"] = {"hardened": ['<img src=x onerror="alert(2)"> | reason']}
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    page = (tmp_path / "real-model-report.html").read_text()
    markdown = (tmp_path / "real-model-report.md").read_text()
    parsed = Links()
    parsed.feed(page)
    assert '<script>alert("model")' not in page
    assert "<img src=x" not in page
    assert html.escape(malicious, quote=True) in page
    assert "\\|&#96;name&#96;" in markdown
    assert all("alert" not in source for source in parsed.scripts)
    assert 'onmouseover="alert' not in page


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://example.com/private.json.gz",
        "javascript:alert(1)",
        "//example.com/private.json.gz",
        "/trials/private.json.gz",
        "trials/../private.json.gz",
        "trials/%2e%2e/private.json.gz",
        "trials/%252e%252e/private.json.gz",
        "trials\\..\\private.json.gz",
        "trials/a.json.gz?secret=x",
        "trials/a.json.gz#fragment",
        "trials/a.json",
        "trials/\nprivate.json.gz",
        "trials/",
        None,
    ],
)
def test_evidence_links_cannot_escape_the_local_trials_directory(tmp_path, unsafe):
    rows = recorded_fixture()
    for row in rows:
        row["artifact"] = unsafe
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    page = (tmp_path / "real-model-report.html").read_text()
    parsed = Links()
    parsed.feed(page)
    assert not any(href and href.endswith(".json.gz") for href in parsed.hrefs)
    assert "not linked" in page
    assert "[raw trial]" not in (tmp_path / "real-model-report.md").read_text()


def test_bare_evidence_filename_is_scoped_and_url_encoded(tmp_path):
    rows = recorded_fixture()
    rows[0]["artifact"] = "trial one.json.gz"
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    page = (tmp_path / "real-model-report.html").read_text()
    assert 'href="trials/trial%20one.json.gz"' in page


@pytest.mark.parametrize(
    "corruption",
    ["counts", "rate", "consistency", "disagreement", "paired", "interval", "interval_nan"],
)
def test_stale_or_invalid_summary_is_rejected_before_files_are_written(tmp_path, corruption):
    rows = recorded_fixture()
    summary = summarize_trials(rows, bootstrap_samples=0)
    model = summary["models"][summary["corpus"]["models"][0]]
    if corruption == "counts":
        summary["corpus"]["trials"] += 1
    elif corruption == "rate":
        model["graders"]["hardened"]["rate"] = 0.123
    elif corruption == "consistency":
        model["consistency"]["hardened"]["pass^3"]["estimate"] = 0.123
    elif corruption == "disagreement":
        model["disagreements_vs_hardened"]["final_state"]["grader_only_pass"] += 1
    elif corruption == "paired":
        summary["paired_model_differences"][0]["graders"]["hardened"]["difference"] = 0.123
    elif corruption == "interval":
        model["graders"]["hardened"]["ci"] = [0.9, 0.1]
    else:
        model["graders"]["hardened"]["ci"] = [float("nan"), 1.0]
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        write_study_report(summary, rows, output)
    assert not output.exists()


def test_missing_summary_field_and_missing_trial_cannot_produce_a_report(tmp_path):
    rows = recorded_fixture()
    summary = summarize_trials(rows, bootstrap_samples=0)
    broken = copy.deepcopy(summary)
    del broken["models"]
    with pytest.raises(ValueError, match="invalid schema"):
        write_study_report(broken, rows, tmp_path)
    with pytest.raises(ValueError, match="incomplete"):
        write_study_report(summary, rows[:-1], tmp_path)


def test_missing_tokens_remain_missing_and_tsv_round_trips_fields(tmp_path):
    rows = recorded_fixture()
    for row in rows:
        row["prompt_tokens"] = None
        row["completion_tokens"] = None
    rows[0]["reasons"] = {"hardened": ["reason with a tab\tand a newline\nfor audit"]}
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    page = (tmp_path / "real-model-report.html").read_text()
    assert "not reported" in page
    with (tmp_path / "trial-summary.tsv").open(newline="") as stream:
        exported = list(csv.DictReader(stream, delimiter="\t"))
    assert len(exported) == len(rows)
    assert exported[0]["prompt_tokens"] == ""
    assert exported[0]["completion_tokens"] == ""
    assert exported[0]["hardened_reasons"] == "reason with a tab\tand a newline\nfor audit"
    assert exported[0]["decode_seed"] == "17"


def test_tsv_labels_are_text_instead_of_spreadsheet_formulas(tmp_path):
    rows = recorded_fixture()
    rows[0]["trial_id"] = '=HYPERLINK("https://example.com")'
    write_study_report(summarize_trials(rows, bootstrap_samples=0), rows, tmp_path)
    with (tmp_path / "trial-summary.tsv").open(newline="") as stream:
        exported = list(csv.DictReader(stream, delimiter="\t"))
    assert exported[0]["trial_id"].startswith("'=HYPERLINK")


def test_rendered_outputs_are_order_independent_and_have_no_remote_dependencies(tmp_path):
    rows = recorded_fixture()
    summary = summarize_trials(rows, bootstrap_samples=20)
    first, second = tmp_path / "first", tmp_path / "second"
    write_study_report(summary, rows, first)
    write_study_report(summary, list(reversed(rows)), second)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    page = (first / "real-model-report.html").read_text()
    assert "<script src=" not in page
    assert '<link rel="stylesheet"' not in page
    assert "@import" not in page
    assert "addEventListener('input',filter)" in page
    assert "row.dataset.disagreement" in page
