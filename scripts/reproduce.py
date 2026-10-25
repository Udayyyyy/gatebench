"""Regenerate the checked-in study, checking two complete runs before replacing it."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from gatebench.integrity import audit_integrity
from gatebench.runner import audit, verify_manifest, write_json


def generate(destination: Path) -> None:
    audit(destination)
    audit_integrity(destination)
    raw = destination / "episodes.jsonl"
    with (destination / "episodes.jsonl.gz").open("wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", mtime=0, filename="") as archive:
            archive.write(raw.read_bytes())
    raw.unlink()
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = {
        str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(destination.rglob("*"))
        if p.is_file() and p != manifest_path
    }
    write_json(manifest_path, manifest)
    assert not verify_manifest(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/results"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gatebench-") as temporary:
        root = Path(temporary)
        first, second = root / "first", root / "second"
        generate(first)
        generate(second)
        for path in first.rglob("*"):
            if path.is_file():
                other = second / path.relative_to(first)
                if path.read_bytes() != other.read_bytes():
                    raise RuntimeError(f"nonreproducible artifact: {path.relative_to(first)}")
        if {str(p.relative_to(first)) for p in first.rglob("*")} != {
            str(p.relative_to(second)) for p in second.rglob("*")
        }:
            raise RuntimeError("runs emitted different artifact sets")
        # Only this generator's destination is replaced, after both runs agree.
        if args.output.exists():
            existing_manifest = args.output / "manifest.json"
            if not existing_manifest.is_file():
                raise RuntimeError("refusing to replace a directory without a GateBench manifest")
            data = json.loads(existing_manifest.read_text())
            if data.get("kind") != "scripted_verifier_audit":
                raise RuntimeError("destination is not a generated GateBench audit")
            shutil.rmtree(args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(first, args.output)
    print(f"Two runs matched byte for byte. Evidence: {args.output}")


if __name__ == "__main__":
    main()
