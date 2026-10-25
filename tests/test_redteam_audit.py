"""The assessment must expose errors and reject changes to the frozen labels."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from gatebench import redteam_audit
from gatebench.models import Verdict

FREEZE = Path(__file__).resolve().parents[1] / "data" / "redteam" / "v1"


def _copy_freeze(tmp_path):
    target = tmp_path / "freeze"
    shutil.copytree(FREEZE, target)
    return target


def test_changed_frozen_actions_rejected_before_creating_results(tmp_path):
    freeze = _copy_freeze(tmp_path)
    with (freeze / "cases.jsonl").open("ab") as changed:
        changed.write(b"\n")
    output = tmp_path / "audit"
    with pytest.raises(ValueError, match="frozen cases changed"):
        redteam_audit.audit_redteam(output, freeze)
    assert not output.exists()


def test_rebinding_manifest_cannot_hide_a_changed_freeze(tmp_path):
    freeze = _copy_freeze(tmp_path)
    cases = freeze / "cases.jsonl"
    cases.write_bytes(cases.read_bytes() + b"\n")
    manifest_path = freeze / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["cases_sha256"] = hashlib.sha256(cases.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="committed v1 case digest"):
        redteam_audit.audit_redteam(tmp_path / "audit", freeze)


def test_observed_hardened_mismatches_are_reported_without_relabeling(tmp_path, monkeypatch):
    # This intentionally faulty grader accepts every invalid episode. The audit
    # must report all 180 errors instead of assuming its strongest grader is right.
    monkeypatch.setattr(redteam_audit, "GRADERS", ("hardened",))
    monkeypatch.setattr(redteam_audit, "grade", lambda name, task, episode: Verdict(True))
    output = tmp_path / "audit"
    summary = redteam_audit.audit_redteam(output, FREEZE)
    assert summary["graders"]["hardened"]["false_positive"] == 180
    assert len(summary["hardened_mismatches"]) == 180
    mismatches = json.loads((output / "mismatches.json").read_text())
    assert len(mismatches) == 180
    assert all(item["expected"] is False and item["observed"] is True for item in mismatches)
    assert all(item["label_review"]["frozen_label_preserved"] for item in mismatches)
    assert "disagrees with frozen labels" in (output / "report.md").read_text()
    assert hashlib.sha256((output / "frozen_cases.jsonl").read_bytes()).hexdigest() == (
        redteam_audit.FROZEN_V1_SHA256
    )


def test_current_eight_graders_and_bounded_timing_are_recorded(tmp_path):
    output = tmp_path / "audit"
    summary = redteam_audit.audit_redteam(output, FREEZE)
    assert summary["records"] == 332
    assert summary["valid"] == 152 and summary["invalid"] == 180
    assert len(summary["graders"]) == 8
    assert summary["graders"]["hardened"] == {
        "true_positive": 152,
        "true_negative": 180,
        "false_positive": 0,
        "false_negative": 0,
    }
    assert summary["graders"]["goal"]["false_positive"] == 136
    assert summary["graders"]["final_state"]["false_positive"] == 88
    assert summary["graders"]["no_frame"]["false_positive"] == 12
    assert summary["graders"]["transcript"]["false_negative"] == 152
    assert summary["graders"]["exact_trace"]["false_negative"] == 152
    assert summary["label_review"]["mismatch_records"] == 628
    for distribution in summary["timing"]["by_grader"].values():
        assert distribution["samples"] == 332 * redteam_audit.TIMING_REPETITIONS
        assert 0 < distribution["min_ns"] <= distribution["median_ns"] <= distribution["max_ns"]
    rows = json.loads((output / "rows.json").read_text())
    assert all(set(row["reasons"]) == set(summary["graders"]) for row in rows)
    assert any(row["graders"]["hardened"] != row["graders"]["goal"] for row in rows)
    manifest = json.loads((output / "manifest.json").read_text())
    for name, expected_hash in manifest["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected_hash
