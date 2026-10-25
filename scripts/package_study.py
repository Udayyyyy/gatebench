"""Publish a checked study with a manifest covering raw and derived files."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from gatebench.experiments.verification import verify_study
from gatebench.runner import write_json

_PROTOCOL = Path(__file__).resolve().parents[1] / "docs" / "retail-confirmation-protocol.md"
# Exact precollection rubric committed in 9d2a6b4.
_PROTOCOL_SHA256 = "3af670873199e9c53717efcccc1c13e1653a21d47f18ec9e9f7dd6d85cd10edc"
_NOTICE_START = "<!-- GATEBENCH_RETAIL_CONFIRMATION_NOTICE -->"
_NOTICE_END = "<!-- END_GATEBENCH_RETAIL_CONFIRMATION_NOTICE -->"


def _retail_reports(destination: Path) -> None:
    protocol = _PROTOCOL.read_bytes()
    if hashlib.sha256(protocol).hexdigest() != _PROTOCOL_SHA256:
        raise ValueError("retail confirmation rubric differs from its precollection commit")
    (destination / "confirmation-protocol.source.txt").write_bytes(protocol)
    explanation = (
        "No fresh user reply is available in this fixed-input protocol. Fully policy-compliant "
        "database-write completion is therefore impossible: the policy requires explicit "
        "confirmation after action details. Native ENV/DB and bounded-layer acceptance are "
        "diagnostics, not a ranking of tool-use ability or full-policy completion. "
        "A concrete confirmation request can be appropriate despite an incomplete database outcome."
    )
    links = [
        (
            "Predeclared behavior protocol",
            "https://github.com/Udayyyyy/gatebench/blob/"
            "9d2a6b45545624c2d21d885c41faed1e90d92bf0/docs/retail-confirmation-protocol.md",
        ),
        ("Frozen protocol source", "confirmation-protocol.source.txt"),
    ]
    if (destination / "review.json").is_file():
        links.append(("Behavior annotations (JSON)", "review.json"))
    if (destination / "review.html").is_file():
        links.append(("Behavior review", "review.html"))
    if (destination / "review.md").is_file():
        links.append(("Review source (Markdown)", "review.md"))
    markdown_links = " · ".join(f"[{label}]({path})" for label, path in links)
    html_links = " · ".join(f'<a href="{path}">{label}</a>' for label, path in links)
    reports = (
        (
            "real-model-report.md",
            "# GateBench — real-model study",
            "# GateBench — retail behavior without confirmation",
            f"\n\n> **Confirmation boundary.** {explanation}\n> {markdown_links}\n\n",
        ),
        (
            "real-model-report.html",
            "<h1>What changes when models act?</h1>",
            "<h1>Retail behavior without confirmation</h1>",
            f'<aside class="notice"><strong>Confirmation boundary.</strong> {explanation}'
            f"<p>{html_links}</p></aside>",
        ),
    )
    for name, old_title, title, notice in reports:
        path = destination / name
        text = path.read_text().replace(old_title, title, 1)
        if _NOTICE_START in text:
            before, _, rest = text.partition(_NOTICE_START)
            _, end, after = rest.partition(_NOTICE_END)
            if not end:
                raise ValueError(f"unterminated retail notice in {name}")
            text = before + _NOTICE_START + notice + _NOTICE_END + after
        else:
            before, heading, after = text.partition(title)
            if not heading:
                raise ValueError(f"expected report heading missing in {name}")
            text = before + heading + "\n" + _NOTICE_START + notice + _NOTICE_END + "\n" + after
        path.write_text(text)


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
    frozen = json.loads((destination / "frozen-study.json").read_text())
    if frozen["config"]["domain"] == "tau2-retail":
        _retail_reports(destination)
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
