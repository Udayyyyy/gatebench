"""Portable reports for actual model trials and their grader disagreements."""

from __future__ import annotations

import csv
import html
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from gatebench.experiments.analysis import summarize_trials


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _markdown_text(value: Any) -> str:
    return _escape(value).replace("|", "\\|").replace("`", "&#96;").replace("\n", " ")


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def _interval(value: list[float] | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    spec = "+.1f" if signed else ".1f"
    return f"[{100 * value[0]:{spec}}, {100 * value[1]:{spec}}]"


def _artifact_path(value: Any) -> str | None:
    """Evidence links stay inside the report's local trials directory."""
    if not isinstance(value, str) or not value:
        return None
    decoded = unquote(value)
    if any(ord(char) < 32 for char in decoded) or any(char in decoded for char in ("\\", "%")):
        return None
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    if "/" not in decoded:
        decoded = "trials/" + decoded
    path = PurePosixPath(decoded)
    if path.is_absolute() or ".." in path.parts or path.parts[0] != "trials":
        return None
    if len(path.parts) < 2 or not path.name.endswith(".json.gz"):
        return None
    return quote(str(path), safe="/-._")


def _validate_interval(value: Any, minimum: float = 0, maximum: float = 1) -> None:
    if value is None:
        return
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
            for item in value
        )
    ):
        raise ValueError("report interval must be two finite bounds or null")
    if not minimum <= value[0] <= value[1] <= maximum:
        raise ValueError("report interval bounds are invalid")


def _validate(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    try:
        point = summarize_trials(
            rows,
            expected_models=summary["corpus"]["models"],
            repeats=summary["corpus"]["repeats"],
            bootstrap_samples=0,
        )
        if point["corpus"] != summary["corpus"]:
            raise ValueError("report corpus counts do not match the recorded trials")
        if set(point["models"]) != set(summary["models"]):
            raise ValueError("report model names do not match the recorded trials")
        for model, expected in point["models"].items():
            actual = summary["models"][model]
            for field in (
                "trials",
                "task_clusters",
                "stop_reasons",
                "latency_seconds",
                "tokens",
                "family",
                "domain",
            ):
                if actual[field] != expected[field]:
                    raise ValueError(f"report {model}/{field} does not match recorded trials")
            if set(actual["graders"]) != set(expected["graders"]):
                raise ValueError("report graders do not match the recorded trials")
            for name, metric in expected["graders"].items():
                for field in ("passed", "trials", "rate"):
                    if actual["graders"][name][field] != metric[field]:
                        raise ValueError("report acceptance counts/rates do not match trials")
                _validate_interval(actual["graders"][name]["ci"])
                for key, value in expected["disagreements_vs_hardened"][name].items():
                    if key != "ci" and actual["disagreements_vs_hardened"][name][key] != value:
                        raise ValueError("report disagreement counts do not match trials")
                _validate_interval(actual["disagreements_vs_hardened"][name]["ci"])
                for k, consistency in expected["consistency"][name].items():
                    if actual["consistency"][name][k]["estimate"] != consistency["estimate"]:
                        raise ValueError("report repeated-success estimates do not match trials")
                    _validate_interval(actual["consistency"][name][k]["ci"])
        comparisons = summary["paired_model_differences"]
        if len(comparisons) != len(point["paired_model_differences"]):
            raise ValueError("report paired comparisons do not match trials")
        for actual, expected in zip(comparisons, point["paired_model_differences"], strict=True):
            for field in ("model_a", "model_b", "direction", "task_clusters"):
                if actual[field] != expected[field]:
                    raise ValueError("report paired models do not match trials")
            if set(actual["graders"]) != set(expected["graders"]):
                raise ValueError("report paired graders do not match trials")
            for name, metric in expected["graders"].items():
                if actual["graders"][name]["difference"] != metric["difference"]:
                    raise ValueError("report paired differences do not match trials")
                _validate_interval(actual["graders"][name]["ci"], -1, 1)
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError("report summary has an invalid schema") from exc


def _reason(row: dict[str, Any]) -> str:
    reasons = row.get("reasons", {})
    selected = reasons.get("hardened", []) if isinstance(reasons, dict) else []
    if isinstance(selected, str):
        return selected
    if isinstance(selected, list):
        return "; ".join(str(reason) for reason in selected)
    return ""


def _evidence(row: dict[str, Any], *, markdown: bool = False) -> str:
    artifact = _artifact_path(row.get("artifact"))
    if artifact is None:
        return "not linked"
    if markdown:
        return f"[raw trial]({artifact})"
    return f'<a href="{_escape(artifact)}">raw trial</a>'


def _comparison_grader(summary: dict[str, Any]) -> str:
    names = next(iter(summary["models"].values()))["graders"]
    return next((name for name in ("final_state", "native", "goal") if name in names), "hardened")


def _scope(summary: dict[str, Any]) -> str:
    models = summary["corpus"]["models"]
    if all("qwen3.5:" in model.lower() and "q4_k_m" in model.lower() for model in models):
        return (
            "The listed Qwen3.5 packages share a model family and Q4_K_M quantization. "
            "This is a size comparison on the frozen tasks, not a broad model leaderboard. "
            "The study uses text inputs only."
        )
    return "Results apply to the listed model packages and fixed task matrix; this is not a broad model leaderboard."


def _markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    corpus = summary["corpus"]
    lines = [
        "# GateBench — real-model study",
        "",
        "Observed tool-use trials, kept separate from scripted verifier controls.",
        "",
        f"**Recorded matrix:** {corpus['trials']} trials; {len(corpus['models'])} model packages; "
        f"{corpus['task_clusters']} task clusters; {corpus['repeats']} repetitions per model/task.",
        f"**Domains:** {', '.join(_markdown_text(domain) for domain in corpus['domains'])}.",
        _scope(summary),
        "",
        "## Acceptance and repeated success",
        "",
        "Acceptance is the grader's decision over all scheduled trials, including budget/error "
        "terminations. Hardened acceptance requires completed, policy-compliant evidence. "
        "The hardened implementation is not independent ground truth. In a public-benchmark "
        "domain, native means the unchanged upstream environment/database component only; "
        "natural-language assertions and confirmation checks are not assessed by this adapter.",
        "",
        "| Model | Grader | Accepted | 95% interval (%) | pass^1 | pass^2 | pass^3 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model, result in summary["models"].items():
        for name, metric in result["graders"].items():
            consistency = result["consistency"][name]
            cells = " | ".join(_percent(consistency[f"pass^{k}"]["estimate"]) for k in (1, 2, 3))
            lines.append(
                f"| {_markdown_text(model)} | {_markdown_text(name)} | "
                f"{metric['passed']}/{metric['trials']} ({_percent(metric['rate'])}) | "
                f"{_interval(metric['ci'])} | {cells} |"
            )
    lines += [
        "",
        "`pass^k = mean_task(comb(successes, k) / comb(repetitions, k))`. "
        "With three repetitions, pass^3 requires all three to succeed. It is not any-of-three success.",
        "",
        "## Runtime and reporting coverage",
        "",
        "| Model | Stop reasons | Mean / median / p95 seconds | Prompt tokens (reported trials) | Completion tokens (reported trials) |",
        "|---|---|---:|---:|---:|",
    ]
    for model, result in summary["models"].items():
        timing = result["latency_seconds"]
        stops = ", ".join(f"{name}: {count}" for name, count in result["stop_reasons"].items())
        tokens = []
        for field in ("prompt_tokens", "completion_tokens"):
            metric = result["tokens"][field]
            tokens.append(
                f"{metric['total'] if metric['total'] is not None else 'not reported'} ({metric['reported_trials']}/{result['trials']})"
            )
        lines.append(
            f"| {_markdown_text(model)} | {stops} | {timing['mean']:.2f} / {timing['median']:.2f} / {timing['p95']:.2f} | {' | '.join(tokens)} |"
        )
    lines += [
        "",
        "## Paired model differences",
        "",
        "Difference is model B minus model A in acceptance percentage points. "
        "Every model uses the same bootstrap task draws.",
        "",
        "| Model A | Model B | Grader | Difference (pp) | 95% interval (pp) |",
        "|---|---|---|---:|---:|",
    ]
    for pair in summary["paired_model_differences"]:
        for name, metric in pair["graders"].items():
            lines.append(
                f"| {_markdown_text(pair['model_a'])} | {_markdown_text(pair['model_b'])} | "
                f"{_markdown_text(name)} | {100 * metric['difference']:+.1f} | {_interval(metric['ci'], signed=True)} |"
            )
    lines += [
        "",
        "## Workflow and domain slices",
        "",
        "Point estimates only; all repetitions remain in their task cluster.",
        "",
        "| Model | Dimension | Slice | Grader | Accepted |",
        "|---|---|---|---|---:|",
    ]
    for model, result in summary["models"].items():
        for dimension in ("domain", "family"):
            for value, group in result[dimension].items():
                for name, metric in group["graders"].items():
                    lines.append(
                        f"| {_markdown_text(model)} | {dimension} | {_markdown_text(value)} | "
                        f"{_markdown_text(name)} | {metric['passed']}/{metric['trials']} ({_percent(metric['rate'])}) |"
                    )
    comparison = _comparison_grader(summary)
    disagreements = [
        row for row in rows if row["graders"][comparison] and not row["graders"]["hardened"]
    ]
    lines += [
        "",
        f"## {comparison} acceptance disagreements",
        "",
        f"All {len(disagreements)} trials accepted by {comparison} and rejected by hardened are listed below. "
        "These are disagreements pending trace adjudication, not measured false-positive rates.",
        "",
        "| Trial | Model | Domain / workflow | Hardened reason | Evidence |",
        "|---|---|---|---|---|",
    ]
    for row in disagreements:
        lines.append(
            f"| {_markdown_text(row['trial_id'])} | {_markdown_text(row['model'])} | "
            f"{_markdown_text(row.get('domain', 'gatebench'))} / {_markdown_text(row['family'])} | "
            f"{_markdown_text(_reason(row)) or 'no reason recorded'} | {_evidence(row, markdown=True)} |"
        )
    lines += [
        "",
        "## Method and limits",
        "",
        f"- Bootstrap: {summary['bootstrap']['samples']} paired task-cluster draws, seed {summary['bootstrap']['seed']}; "
        "all repetitions retained. Intervals describe sensitivity to this fixed task mix.",
        "- Missing trials are rejected by the analyzer. Token counts that were not reported remain missing.",
        "- Model digests, generation settings, task/policy fingerprints, and raw responses belong in the accompanying run manifest and trial artifacts.",
        "- Model outputs can vary across runtime builds and hardware even when decoding seeds match.",
        "- Public benchmark domains retain their own protocol and upstream revision. A fixed-user subset is not an official full-benchmark leaderboard run.",
        "- A disagreement alone establishes neither a verifier error nor intentional reward hacking. Use separate evidence-backed annotations for adjudication.",
        "",
        "[Download the trial summary](trial-summary.tsv). Open `real-model-report.html` for the searchable complete trial table.",
        "",
    ]
    return "\n".join(lines)


_STYLE = """
:root{color-scheme:light;--ink:#202c39;--muted:#64707b;--line:#dce1e5;--paper:#fbfaf7;--blue:#285d98;--red:#a83e2c}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}
main{max-width:1440px;margin:auto;padding:44px 4.5vw 70px}h1{font-size:clamp(36px,5vw,62px);letter-spacing:-.045em;line-height:1.08;margin:18px 0}
h2{font-size:25px;letter-spacing:-.025em;margin:0 0 14px}h3{font-size:17px;margin:0 0 10px}p{max-width:1000px}.kicker,.tag{font:11px/1.4 ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase}.kicker{color:var(--muted);font-weight:600}
.lead{font-size:18px;color:var(--muted)}a{color:var(--blue)}nav{display:flex;gap:22px;margin:26px 0}.notice{border-left:3px solid var(--blue);padding:12px 16px;background:#edf1f5;max-width:1100px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:15px;margin:32px 0}.card{background:white;border:1px solid var(--line);padding:22px;overflow-wrap:anywhere}.score{font-size:38px;letter-spacing:-.04em;margin:10px 0}.muted{color:var(--muted)}.small{font-size:12px}section{border-top:1px solid var(--line);margin-top:40px;padding-top:30px}
.table-wrap{overflow:auto;background:white;border:1px solid var(--line)}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:12px 14px;vertical-align:top;border-bottom:1px solid var(--line)}th{font-size:11px;letter-spacing:.04em;text-transform:uppercase;background:#f1f3f4;white-space:nowrap}td{font-size:13px}tr:last-child td{border-bottom:0}.label{font-family:ui-monospace,monospace;overflow-wrap:anywhere}.accept{color:#2b674d}.reject{color:var(--red)}.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:20px 0}input[type=search],select{padding:10px 12px;border:1px solid #bfc7cf;background:white;border-radius:3px;color:var(--ink)}input[type=search]{min-width:280px;flex:1}summary{cursor:pointer}details{padding:10px 0}code{font-family:ui-monospace,monospace}footer{margin-top:40px;color:var(--muted);font-size:12px}ul{padding-left:20px}.reason{max-width:620px;overflow-wrap:anywhere}tr[hidden]{display:none}td.tight{white-space:nowrap}
@media(max-width:700px){main{padding:28px 18px}.cards{grid-template-columns:1fr}h1{font-size:42px}nav{gap:14px;flex-wrap:wrap}th,td{padding:10px}.controls{display:block}.controls>*{margin:6px 0}input[type=search],select{width:100%;min-width:0}}
"""


def _table(headers: list[str], body: list[str]) -> str:
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join(f"<th>{_escape(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _html(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    corpus = summary["corpus"]
    cards, acceptance, runtime, paired, slices = [], [], [], [], []
    for model, result in summary["models"].items():
        hardened = result["graders"]["hardened"]
        reliable = result["consistency"]["hardened"]["pass^3"]
        cards.append(
            f'<article class="card"><h3 class="label">{_escape(model)}</h3><div class="score">{_percent(hardened["rate"])}</div><div class="tag">Hardened acceptance · {hardened["passed"]}/{hardened["trials"]}</div><p class="small muted">95% interval (%) {_interval(hardened["ci"])}<br>All-three consistency: {_percent(reliable["estimate"])} · {_interval(reliable["ci"])}</p></article>'
        )
        for name, metric in result["graders"].items():
            consistency = result["consistency"][name]
            values = "".join(
                f'<td>{_percent(consistency[f"pass^{k}"]["estimate"])}<br><span class="small muted">{_interval(consistency[f"pass^{k}"]["ci"])}</span></td>'
                for k in (1, 2, 3)
            )
            acceptance.append(
                f'<tr><td class="label">{_escape(model)}</td><td class="label">{_escape(name)}</td><td>{metric["passed"]}/{metric["trials"]} ({_percent(metric["rate"])})</td><td>{_interval(metric["ci"])}</td>{values}</tr>'
            )
        latency = result["latency_seconds"]
        token_cells = []
        for field in ("prompt_tokens", "completion_tokens"):
            token = result["tokens"][field]
            token_cells.append(
                f'<td>{token["total"] if token["total"] is not None else "not reported"}<br><span class="small muted">{token["reported_trials"]}/{result["trials"]} trials</span></td>'
            )
        stop = ", ".join(f"{name}: {count}" for name, count in result["stop_reasons"].items())
        runtime.append(
            f'<tr><td class="label">{_escape(model)}</td><td>{_escape(stop)}</td><td>{latency["mean"]:.2f} / {latency["median"]:.2f} / {latency["p95"]:.2f}</td>{"".join(token_cells)}</tr>'
        )
        for dimension in ("domain", "family"):
            for value, group in result[dimension].items():
                for name, metric in group["graders"].items():
                    slices.append(
                        f'<tr><td class="label">{_escape(model)}</td><td>{dimension}</td><td>{_escape(value)}</td><td class="label">{_escape(name)}</td><td>{metric["passed"]}/{metric["trials"]} ({_percent(metric["rate"])})</td></tr>'
                    )
    for pair in summary["paired_model_differences"]:
        for name, metric in pair["graders"].items():
            paired.append(
                f'<tr><td class="label">{_escape(pair["model_a"])}</td><td class="label">{_escape(pair["model_b"])}</td><td class="label">{_escape(name)}</td><td>{100 * metric["difference"]:+.1f}</td><td>{_interval(metric["ci"], signed=True)}</td></tr>'
            )
    comparison = _comparison_grader(summary)
    disagreements = [
        row for row in rows if row["graders"][comparison] and not row["graders"]["hardened"]
    ]
    disagreement_rows = [
        f'<tr><td class="label">{_escape(row["trial_id"])}</td><td class="label">{_escape(row["model"])}</td><td>{_escape(row.get("domain", "gatebench"))} / {_escape(row["family"])}</td><td class="reason">{_escape(_reason(row)) or "no reason recorded"}</td><td>{_evidence(row)}</td></tr>'
        for row in disagreements
    ]
    trial_rows = []
    for row in rows:
        disagreement = row["graders"][comparison] and not row["graders"]["hardened"]
        search = (
            " ".join(
                str(row.get(field, ""))
                for field in ("trial_id", "task_id", "model", "family", "domain", "stop_reason")
            )
            + " "
            + _reason(row)
        )
        digest = row.get("model_digest")
        digest_cell = (
            f'<span class="small muted" title="{_escape(digest)}">{_escape(str(digest)[:16])}</span>'
            if digest
            else ""
        )
        verdicts = "; ".join(
            f"{name}: {'accept' if passed else 'reject'}" for name, passed in row["graders"].items()
        )
        trial_rows.append(
            f'<tr data-search="{_escape(search.lower())}" data-model="{_escape(row["model"])}" data-disagreement="{int(disagreement)}"><td class="label">{_escape(row["trial_id"])}</td><td class="label">{_escape(row["model"])}<br>{digest_cell}</td><td>{_escape(row.get("domain", "gatebench"))}<br>{_escape(row["family"])}</td><td class="tight">{row["repeat"] + 1} / seed {row["decode_seed"]}</td><td>{_escape(row["stop_reason"])}</td><td>{_escape(verdicts)}<details><summary>Hardened reasons</summary><span class="reason">{_escape(_reason(row)) or "none"}</span></details></td><td>{row["elapsed_seconds"]:.2f}s</td><td>{_evidence(row)}</td></tr>'
        )
    options = "".join(
        f'<option value="{_escape(model)}">{_escape(model)}</option>' for model in corpus["models"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GateBench · Real-model study</title><style>{_STYLE}</style></head>
<body><main><div class="kicker">GateBench / Empirical study / Actual model trials</div><h1>What changes when models act?</h1><p class="lead">Observed tool use, repeated-task consistency, and the effect of choosing a grader.</p><div class="tag">{corpus["trials"]:,} trials · {len(corpus["models"])} model packages · {corpus["task_clusters"]} task clusters · {corpus["repeats"]} repetitions</div>
<nav aria-label="Study sections"><a href="#results">Results</a><a href="#disagreements">Disagreements</a><a href="#trials">Inspect trials</a><a href="#method">Method</a></nav>
<p class="notice">These are actual model trials, separate from scripted controls. Grader disagreement is not an independently established error rate. {_escape(_scope(summary))}</p><div class="cards">{"".join(cards)}</div>
<section id="results"><h2>Acceptance and reliable repetition</h2><p>Every grader sees the same episode. Counts include all scheduled trials. <code>pass^k = mean_task(comb(successes, k) / comb(repetitions, k))</code>; with three repetitions, pass^3 requires all three to pass. Intervals are in percent.</p><p>For public-benchmark trials, <code>native</code> means the unchanged upstream environment/database evaluator component. Natural-language assertions and confirmation checks are not assessed here; this is not the full upstream benchmark score.</p>{_table(["Model", "Grader", "Accepted", "95% interval (%)", "pass^1", "pass^2", "pass^3"], acceptance)}</section>
<section><h2>Latency, terminations, and token coverage</h2><p>Elapsed time includes the recorded trial's transport and tool loop. Missing token counts stay missing; warm-up and load conditions belong in the run manifest.</p>{_table(["Model", "Stop reasons", "Mean / median / p95 seconds", "Prompt tokens", "Completion tokens"], runtime)}<details><summary>Paired model differences</summary><p>Model B minus model A in acceptance percentage points, with shared task-cluster draws.</p>{_table(["Model A", "Model B", "Grader", "Difference (pp)", "95% interval (pp)"], paired)}</details><details><summary>Workflow and domain slices</summary><p>Point estimates only. Each domain retains its own task definition and protocol.</p>{_table(["Model", "Dimension", "Slice", "Grader", "Accepted"], slices)}</details></section>
<section id="disagreements"><h2>{_escape(comparison)} acceptance disagreements</h2><p>All {len(disagreements)} trials accepted by {_escape(comparison)} and rejected by hardened. Reasons identify the verifier obligation; independent trace annotations must establish whether that decision is correct.</p>{_table(["Trial", "Model", "Domain / workflow", "Hardened reason", "Evidence"], disagreement_rows)}</section>
<section id="trials"><h2>Inspect every recorded trial</h2><p>Trial numbers are one-based here; stored repeat indices are zero-based. Evidence links open the compressed raw trial record.</p><div class="controls"><input type="search" aria-label="Search trials" id="search" placeholder="Find a task, model, stop reason, or policy obligation"><select aria-label="Model filter" id="model"><option value="">All models</option>{options}</select><label><input type="checkbox" id="only-disagreements" aria-label="Disagreements only"> Disagreements only</label><span id="row-count" class="small muted" aria-live="polite">{len(rows)} trials</span></div>{_table(["Trial", "Model / digest", "Domain / workflow", "Repetition", "Stop", "Grader decisions", "Elapsed", "Evidence"], trial_rows)}<p><a href="trial-summary.tsv">Download trial-summary.tsv</a></p></section>
<section id="method"><h2>Method and limits</h2><ul><li><strong>Complete matrix.</strong> Missing or duplicated repetitions, mismatched model/task coverage, and inconsistent grader sets are rejected by the analyzer.</li><li><strong>Paired task clusters.</strong> {summary["bootstrap"]["samples"]:,} bootstrap draws, seed {summary["bootstrap"]["seed"]}, retain all repetitions of each sampled domain/task pair and use the same draws for models and graders.</li><li><strong>Bounded evidence.</strong> Intervals describe sensitivity to this fixed task mix. Small local models, one model family, and a limited number of seeds do not support broad capability or deployment-risk claims.</li><li><strong>Separate adjudication.</strong> The hardened verifier is not independent ground truth. A disagreement alone does not establish a false positive, false negative, or intentional reward hacking.</li><li><strong>Protocol provenance.</strong> Model digests, quantization, runtime/template settings, task/policy hashes, warm-up conditions, and raw outputs belong in the accompanying run manifest. Matching seeds do not guarantee identical inference on different runtimes or hardware.</li><li><strong>Public benchmark scope.</strong> External domains retain their own source revision, native evaluator, task selection, and protocol departures. A fixed-user subset is not an official full-benchmark leaderboard run.</li></ul></section><footer>Generated from recorded model-trial rows and their validated summary. No remote scripts, fonts, or chart services are required.</footer></main>
<script>
const search=document.querySelector('#search'), model=document.querySelector('#model'), only=document.querySelector('#only-disagreements');
const rows=Array.from(document.querySelectorAll('#trials tbody tr'));
function filter(){{let count=0;const query=search.value.toLowerCase();for(const row of rows){{const show=row.dataset.search.includes(query)&&(!model.value||row.dataset.model===model.value)&&(!only.checked||row.dataset.disagreement==='1');row.hidden=!show;if(show)count++;}}document.querySelector('#row-count').textContent=count+' / '+rows.length+' trials';}}
search.addEventListener('input',filter);model.addEventListener('change',filter);only.addEventListener('change',filter);
</script></body></html>"""


def _tsv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def write_study_report(summary: dict[str, Any], rows: list[dict[str, Any]], output: Path) -> None:
    """Write self-contained HTML/Markdown and a compact TSV for recorded trials."""
    _validate(summary, rows)
    ordered = sorted(
        rows,
        key=lambda row: (
            row["model"],
            row.get("domain", "gatebench"),
            row["task_id"],
            row["repeat"],
        ),
    )
    markdown, page = _markdown(summary, ordered), _html(summary, ordered)
    output.mkdir(parents=True, exist_ok=True)
    (output / "real-model-report.md").write_text(markdown)
    (output / "real-model-report.html").write_text(page)
    fields = [
        "trial_id",
        "task_id",
        "domain",
        "family",
        "model",
        "model_digest",
        "repeat",
        "decode_seed",
        "stop_reason",
        "elapsed_seconds",
        "prompt_tokens",
        "completion_tokens",
        "graders",
        "hardened_reasons",
        "artifact",
    ]
    with (output / "trial-summary.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        for row in ordered:
            values = {
                **row,
                "domain": row.get("domain", "gatebench"),
                "graders": json.dumps(row["graders"], sort_keys=True),
                "hardened_reasons": _reason(row),
                "artifact": _artifact_path(row.get("artifact")),
            }
            writer.writerow([_tsv_cell(values.get(field)) for field in fields])
