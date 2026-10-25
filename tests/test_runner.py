from __future__ import annotations

import json
from pathlib import Path

import pytest

from gatebench.cli import main
from gatebench.integrity import audit_integrity
from gatebench.models import Episode, canonical_json
from gatebench.runner import audit, verify_manifest


def test_same_run_reproduces_every_artifact_byte_for_byte(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    for path in (first, second):
        audit(path, per_family=1, bootstrap_samples=25)
        assert not verify_manifest(path)
    a = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    b = {str(p.relative_to(second)): p.read_bytes() for p in second.rglob("*") if p.is_file()}
    assert a == b


def test_manifest_detects_modified_evidence(tmp_path: Path) -> None:
    audit(tmp_path, split="dev", per_family=1, bootstrap_samples=20)
    path = tmp_path / "rows.json"
    path.write_text("[]")
    assert verify_manifest(tmp_path) == ["missing or changed artifact: rows.json"]


def test_manifest_rejects_parent_path(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {"../outside": "0" * 64}}))
    assert verify_manifest(tmp_path) == ["unsafe manifest path: ../outside"]


def test_nonempty_output_is_never_silently_reused(tmp_path: Path) -> None:
    marker = tmp_path / "existing.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="not empty"):
        audit(tmp_path, per_family=1)
    assert marker.read_text() == "keep"


def test_integrity_suite_separates_corruption_from_executable_controls(tmp_path: Path) -> None:
    result = audit_integrity(tmp_path)
    assert result["rejected"] == result["controls"] == 21
    assert result["no_replay_accepted"] > 0
    assert result["kind"] == "serialized_evidence_integrity"


def test_cli_replays_saved_evidence_with_json_key_order_changed(tmp_path: Path) -> None:
    audit(tmp_path, split="dev", per_family=1, bootstrap_samples=20)
    first = json.loads((tmp_path / "episodes.jsonl").read_text().splitlines()[0])
    path = tmp_path / "one-episode.json"
    path.write_text(canonical_json(first["episode"]))
    assert Episode.from_dict(json.loads(path.read_text())).to_dict() == first["episode"]
    assert main(["replay", str(tmp_path / "tasks" / f"{first['task_id']}.json"), str(path)]) == 0
    assert main(["check-manifest", str(tmp_path)]) == 0


def test_cli_invalid_json_fails_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = tmp_path / "bad.json"
    task.write_text("{")
    assert main(["replay", str(task), str(task)]) == 2
    assert "gatebench:" in capsys.readouterr().err
