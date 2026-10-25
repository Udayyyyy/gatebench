"""Inspect a captured trial after checking its compressed-file SHA-256 sidecar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gatebench.experiments.runner import read_trial


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path, help="captured .json.gz trial with its .sha256 sidecar")
    parser.add_argument("--final", action="store_true", help="also print the captured final answer")
    args = parser.parse_args()
    artifact = read_trial(args.trial)
    row, episode = artifact["row"], artifact["episode"]

    print(f"Trial: {row['trial_id']}")
    print(f"Model: {row['model']}")
    print(f"Stop:  {row['stop_reason']}")
    if error := artifact["model_record"].get("error"):
        print(f"Error: {error}")

    print("\nActions (zero-based event indices):")
    for index, event in enumerate(episode["events"]):
        action = event["action"]
        arguments = json.dumps(action["arguments"], sort_keys=True, ensure_ascii=False)
        success = json.dumps(event["result"]["ok"])
        print(f"  [{index}] {action['name']} {arguments} -> ok={success}")
    if not episode["events"]:
        print("  No executed tool calls.")

    print("\nCaptured grader decisions:")
    for name, passed in row["graders"].items():
        print(f"  {name}: {'accept' if passed else 'reject'}")
        for reason in row["reasons"][name]:
            print(f"    {reason}")

    if args.final:
        print(f"\nFinal answer:\n{episode['final_answer']}")


if __name__ == "__main__":
    main()
