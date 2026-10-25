"""Freeze, collect, resume, and regrade a complete local-model study."""

from __future__ import annotations

import gzip
import hashlib
import json
import platform
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gatebench.experiments.analysis import summarize_trials
from gatebench.graders import GRADERS, grade
from gatebench.models import Episode, canonical_json, digest
from gatebench.ollama import request_json, run_model, run_tool_loop
from gatebench.runner import write_json
from gatebench.tasks import make_task

_PACKAGE = Path(__file__).resolve().parents[1]
_SOURCES = (
    "models.py",
    "tasks.py",
    "tooling.py",
    "environment.py",
    "verifier.py",
    "replay.py",
    "baselines.py",
    "graders.py",
    "ollama.py",
    "experiments/runner.py",
    "experiments/analysis.py",
    "experiments/report.py",
)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources(domain: str) -> dict[str, str]:
    paths = list(_SOURCES)
    if domain == "tau2-retail":
        paths.extend(["integrations/tau_retail.py", "integrations/tau2_manifest.json"])
    return {name: file_hash(_PACKAGE / name) for name in paths}


def _cases(config: dict[str, Any]) -> list[Any]:
    selection = config["task_selection"]
    if config["domain"] == "gatebench":
        return [
            make_task(family, seed, selection["split"])
            for family in selection["families"]
            for seed in selection["seeds"]
        ]
    if config["domain"] == "tau2-retail":
        from gatebench.integrations.tau_retail import load_suite

        return load_suite(per_family=selection["per_family"])
    raise ValueError("unknown study domain")


def _case_dict(case: Any) -> dict[str, Any]:
    return case.to_dict() if hasattr(case, "to_dict") else asdict(case)


def _hardware() -> dict[str, Any]:
    result = {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    if platform.system() == "Darwin":
        for key, setting in (
            ("processor", "machdep.cpu.brand_string"),
            ("ram_bytes", "hw.memsize"),
        ):
            result[key] = subprocess.check_output(["sysctl", "-n", setting], text=True).strip()
    return result


def _trial_id(model_index: int, task_id: str, repeat: int) -> str:
    if any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in task_id
    ):
        raise ValueError("unsafe task ID")
    return f"m{model_index}-{task_id}-r{repeat}"


def _model_metadata(endpoint: str, names: list[str]) -> dict[str, Any]:
    installed = {row["name"]: row for row in request_json(endpoint, "/api/tags")["models"]}
    result = {}
    for name in names:
        if name not in installed:
            raise ValueError(f"model not installed: {name}")
        show = request_json(endpoint, "/api/show", {"model": name})
        if installed[name].get("details", {}).get("quantization_level") != "Q4_K_M":
            raise ValueError(f"expected Q4_K_M model: {name}")
        result[name] = {
            "tag": installed[name],
            "show": show,
            "template_sha256": hashlib.sha256(show.get("template", "").encode()).hexdigest(),
        }
    return result


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("kind") != "real_model_study" or config.get("schema_version") != 1:
        raise ValueError("unsupported study configuration")
    if not config.get("models") or len(set(config["models"])) != len(config["models"]):
        raise ValueError("study model names must be nonempty and unique")
    seeds = config["repetitions"]["decode_seeds"]
    if (
        not seeds
        or any(type(s) is not int or s < 0 for s in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("decoding repetitions require unique nonnegative integer seeds")
    generation = config["generation"]
    # These are explicit in both the request builder and the frozen protocol.
    required = {"top_k": 20, "top_p": 0.95, "presence_penalty": 0, "repeat_penalty": 1}
    if any(generation.get(k) != value for k, value in required.items()):
        raise ValueError("generation defaults differ from the implemented frozen transport")


def freeze_study(config: dict[str, Any], output: Path, endpoint: str) -> dict[str, Any]:
    _validate_config(config)
    cases = _cases(config)
    expected = [
        _trial_id(model_index, case.id, repeat)
        for model_index, _ in enumerate(config["models"])
        for case in cases
        for repeat, _ in enumerate(config["repetitions"]["decode_seeds"])
    ]
    sources = _sources(config["domain"])
    path = output / "frozen-study.json"
    if path.exists():
        frozen = json.loads(path.read_text())
        if frozen["config"] != config or frozen["sources"] != sources:
            raise ValueError("study config/source changed; start a new study directory")
        if frozen["expected_trials"] != expected or frozen["tasks_digest"] != digest(
            [_case_dict(c) for c in cases]
        ):
            raise ValueError("study task matrix changed")
        return frozen
    if output.exists() and any(output.iterdir()):
        raise ValueError("new study directory must be empty")
    model_metadata = _model_metadata(endpoint, config["models"])
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_PACKAGE, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    frozen = {
        "schema_version": 1,
        "kind": "frozen_real_model_study",
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "config": config,
        "config_sha256": digest(config),
        "sources": sources,
        "git_revision": revision,
        "tasks_digest": digest([_case_dict(c) for c in cases]),
        "expected_trials": expected,
        "model_metadata": model_metadata,
        "runtime": request_json(endpoint, "/api/version"),
        "hardware": _hardware(),
        "limitations": [
            "same model family, two quantized checkpoints",
            "seed does not guarantee bitwise inference reproducibility",
        ],
    }
    for case in cases:
        write_json(output / "tasks" / f"{case.id}.json", _case_dict(case))
    write_json(path, frozen)
    return frozen


def _options(config: dict[str, Any], seed: int) -> dict[str, Any]:
    generation = config["generation"]
    return {
        **config["budgets"],
        "seed": seed,
        "temperature": generation["temperature"],
        "thinking": generation["think"],
        "context_window": generation["num_ctx"],
        "num_predict": generation["num_predict"],
    }


def _collect(
    case: Any, config: dict[str, Any], model: str, endpoint: str, seed: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if config["domain"] == "gatebench":
        episode, record = run_model(case, model=model, endpoint=endpoint, **_options(config, seed))
        verdicts = {name: grade(name, case, episode).to_dict() for name in GRADERS}
        return episode.to_dict(), record, verdicts
    from gatebench.integrations.tau_retail import TauRetailEnvironment, evaluate

    with TauRetailEnvironment(case) as env:
        final, stop, record = run_tool_loop(
            case.prompt,
            env.tool_schemas,
            env.execute,
            model=model,
            endpoint=endpoint,
            task_fingerprint=case.fingerprint,
            **_options(config, seed),
        )
        evidence = env.episode(final, stop)
    evaluation = evaluate(case, evidence)
    verdicts = {
        "native": {
            "passed": evaluation["native_environment"]["reward"] == 1,
            "reasons": [],
            "details": evaluation["native_environment"],
        },
        "hardened": {
            "passed": evaluation["hardened_passed"],
            "reasons": evaluation["policy"]["reasons"],
            "details": evaluation,
        },
    }
    return evidence, record, verdicts


def _write_trial(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write((canonical_json(value) + "\n").encode())
    temporary.replace(path)
    path.with_suffix(path.suffix + ".sha256").write_text(file_hash(path) + "\n")


def read_trial(path: Path) -> dict[str, Any]:
    if file_hash(path) != path.with_suffix(path.suffix + ".sha256").read_text().strip():
        raise ValueError(f"trial artifact changed: {path.name}")
    with gzip.open(path, "rt") as stream:
        data = json.load(stream)
    return data


def _validate_trial(
    data: dict[str, Any], frozen: dict[str, Any], case: Any, model_index: int, repeat: int
) -> None:
    config = frozen["config"]
    model = config["models"][model_index]
    seed = config["repetitions"]["decode_seeds"][repeat]
    expected = {
        "trial_id": _trial_id(model_index, case.id, repeat),
        "task_id": case.id,
        "family": case.family,
        "domain": config["domain"],
        "model": model,
        "model_digest": frozen["model_metadata"][model]["tag"]["digest"],
        "repeat": repeat,
        "decode_seed": seed,
        "config_sha256": frozen["config_sha256"],
    }
    if any(data["row"].get(key) != value for key, value in expected.items()):
        raise ValueError("trial identity/configuration differs from frozen schedule")
    record = data["model_record"]
    if (
        record.get("task_fingerprint") != case.fingerprint
        or record.get("model") != model
        or record.get("seed") != seed
        or record.get("runtime") != frozen["runtime"]
    ):
        raise ValueError("trial model record differs from frozen identity/runtime")
    generation = config["generation"]
    expected_options = {"seed": seed, **{k: v for k, v in generation.items() if k != "think"}}
    if record.get("options") != expected_options or record.get("thinking") != generation["think"]:
        raise ValueError("trial generation settings differ from frozen schedule")
    budgets = {
        "max_steps": "max_steps",
        "max_turns": "max_turns",
        "timeout": "timeout_seconds",
        "deadline": "deadline_seconds",
    }
    if any(record.get(name) != config["budgets"][key] for key, name in budgets.items()):
        raise ValueError("trial budgets differ from frozen schedule")
    row = data["row"]
    if any(
        row.get(key) != record.get(key)
        for key in ("elapsed_seconds", "prompt_tokens", "completion_tokens", "tool_calls")
    ):
        raise ValueError("trial metrics differ from captured model record")
    if row["stop_reason"] != data["episode"]["stop_reason"]:
        raise ValueError("trial termination differs from captured episode")


def collect_study(
    config_path: Path, output: Path, *, endpoint: str = "http://127.0.0.1:11434"
) -> dict[str, Any]:
    config = json.loads(config_path.read_text())
    frozen = freeze_study(config, output, endpoint)
    if request_json(endpoint, "/api/version") != frozen["runtime"]:
        raise ValueError("runtime version changed since study freeze")
    cases = _cases(config)
    for model_index, model in enumerate(config["models"]):
        current = _model_metadata(endpoint, [model])[model]["tag"]["digest"]
        expected = frozen["model_metadata"][model]["tag"]["digest"]
        if current != expected:
            raise ValueError(f"model tag changed since study freeze: {model}")
        pending = [
            case
            for case in cases
            if any(
                not (output / "trials" / f"{_trial_id(model_index, case.id, r)}.json.gz").exists()
                for r, _ in enumerate(config["repetitions"]["decode_seeds"])
            )
        ]
        if pending:
            # Load/compile the model outside measured task trials. Keep this response too.
            warmup = request_json(
                endpoint,
                "/api/chat",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "stream": False,
                    "think": False,
                    "options": {
                        "num_predict": 8,
                        "num_ctx": config["generation"]["num_ctx"],
                        "seed": 17,
                    },
                },
                timeout=180,
            )
            warmup_number = 0
            while (output / "warmups" / f"m{model_index}-{warmup_number}.json").exists():
                warmup_number += 1
            write_json(output / "warmups" / f"m{model_index}-{warmup_number}.json", warmup)
        for case in cases:
            for repeat, seed in enumerate(config["repetitions"]["decode_seeds"]):
                trial_id = _trial_id(model_index, case.id, repeat)
                path = output / "trials" / f"{trial_id}.json.gz"
                if path.exists():
                    saved = read_trial(path)
                    _validate_trial(saved, frozen, case, model_index, repeat)
                    continue
                evidence, record, verdicts = _collect(case, config, model, endpoint, seed)
                record["runtime"] = frozen["runtime"]
                row = {
                    "trial_id": trial_id,
                    "task_id": case.id,
                    "family": case.family,
                    "domain": config["domain"],
                    "model": model,
                    "model_digest": expected,
                    "repeat": repeat,
                    "decode_seed": seed,
                    "stop_reason": evidence["stop_reason"],
                    "graders": {name: v["passed"] for name, v in verdicts.items()},
                    "reasons": {name: v["reasons"] for name, v in verdicts.items()},
                    "elapsed_seconds": record["elapsed_seconds"],
                    "prompt_tokens": record["prompt_tokens"],
                    "completion_tokens": record["completion_tokens"],
                    "tool_calls": record["tool_calls"],
                    "artifact": f"trials/{path.name}",
                    "config_sha256": frozen["config_sha256"],
                }
                _write_trial(
                    path,
                    {"row": row, "episode": evidence, "model_record": record, "verdicts": verdicts},
                )
                print(
                    f"{trial_id}: {row['stop_reason']}, hardened={row['graders']['hardened']}, {row['elapsed_seconds']:.1f}s",
                    flush=True,
                )
    return summarize_study(output)


def summarize_study(output: Path) -> dict[str, Any]:
    frozen = json.loads((output / "frozen-study.json").read_text())
    config = frozen["config"]
    if frozen["sources"] != _sources(config["domain"]):
        raise ValueError(
            "study sources changed since collection; keep its pinned version or explicitly regrade"
        )
    rows = []
    for model_index, _ in enumerate(config["models"]):
        for case in _cases(config):
            for repeat, _ in enumerate(config["repetitions"]["decode_seeds"]):
                trial_id = _trial_id(model_index, case.id, repeat)
                path = output / "trials" / f"{trial_id}.json.gz"
                if not path.is_file():
                    raise ValueError(f"study incomplete: missing {trial_id}")
                data = read_trial(path)
                _validate_trial(data, frozen, case, model_index, repeat)
                rows.append(data["row"])
    summary = summarize_trials(
        rows,
        expected_models=config["models"],
        expected_task_ids=[case.id for case in _cases(config)],
        repeats=len(config["repetitions"]["decode_seeds"]),
        bootstrap_samples=config["analysis"]["bootstrap_samples"],
        seed=config["analysis"]["seed"],
    )
    write_json(output / "rows.json", rows)
    write_json(output / "summary.json", summary)
    from gatebench.experiments.report import write_study_report

    write_study_report(summary, rows, output)
    return summary


def regrade_gatebench_trial(task: Any, artifact: dict[str, Any]) -> dict[str, bool]:
    episode = Episode.from_dict(artifact["episode"])
    if artifact["model_record"]["task_fingerprint"] != task.fingerprint:
        raise ValueError("trial fingerprint differs from trusted task")
    return {name: grade(name, task, episode).passed for name in GRADERS}
