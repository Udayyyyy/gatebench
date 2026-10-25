"""Publish a checked study with a manifest covering raw and derived files."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from gatebench.experiments.verification import verify_study
from gatebench.runner import write_json


def package_study(source: Path, destination: Path, review: Path | None = None) -> None:
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("destination must be outside the source study")
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    result = verify_study(source)
    if not result["valid"]:
        raise ValueError(f"study evidence failed verification: {result['problems']}")
    required = ("rows.json", "summary.json", "real-model-report.html", "real-model-report.md")
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise ValueError(f"study is missing publication outputs: {missing}")
    shutil.copytree(source, destination)
    if review is not None:
        shutil.copyfile(review, destination / "review.json")
    write_json(destination / "offline-verification.json", result)
    files = sorted(
        path
        for path in destination.rglob("*")
        if path.is_file() and path != destination / "manifest.json"
    )
    manifest = {
        "schema_version": 1,
        "kind": "captured_study_publication",
        "scope": "Byte identity relative to this manifest, not proof of authorship or origin.",
        "files": {
            str(path.relative_to(destination)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    write_json(destination / "manifest.json", manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    package_study(args.source, args.destination, args.review)


if __name__ == "__main__":
    main()
