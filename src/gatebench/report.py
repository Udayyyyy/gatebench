"""Portable audit reports; all numbers come from the recorded controls."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

_ORDER = (
    "transcript",
    "goal",
    "final_state",
    "exact_trace",
    "hardened",
    "no_history",
    "no_frame",
    "no_replay",
)
_DESCRIPTIONS = {
    "transcript": "Trusts a completion claim in the final response.",
    "goal": "Checks requested final fields without the full preservation contract.",
    "final_state": "Checks goal and unrelated-state preservation, without action-time policy or replay.",
    "exact_trace": "Requires the canonical action plan, including its ordering.",
    "hardened": "Checks outcome, state preservation, action-time policy and evidence consistency.",
    "no_history": "Ablation: removes action-time policy checks.",
    "no_frame": "Ablation: removes unrelated-state preservation checks.",
    "no_replay": "Ablation: removes independent evidence-consistency checks.",
}


def _names(summary: dict[str, Any]) -> list[str]:
    available = summary["graders"]
    return [name for name in _ORDER if name in available] + sorted(set(available) - set(_ORDER))


def _percent(rate: float | None) -> str:
    return "—" if rate is None else f"{100 * rate:.1f}%"


def _ci(interval: list[float] | None, *, signed: bool = False) -> str:
    if interval is None:
        return "—"
    spec = "+.1f" if signed else ".1f"
    return f"[{100 * interval[0]:{spec}}, {100 * interval[1]:{spec}}]"


def _rate_cell(metric: dict[str, Any], kind: str) -> str:
    numerator = metric["false_positive" if kind == "false_acceptance" else "false_negative"]
    denominator = metric["negative_count" if kind == "false_acceptance" else "positive_count"]
    return f"{_percent(metric[kind])} ({numerator}/{denominator})"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _error_plot(summary: dict[str, Any]) -> str:
    names = _names(summary)
    height = max(180, 142 + 40 * len(names))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 {height}" role="img" '
        'aria-labelledby="chart-title chart-description">',
        '<title id="chart-title">Verifier errors on independently labeled scripted controls</title>',
        '<desc id="chart-description">Dots are episode-weighted error rates. Bars are 95 percent '
        "case-cluster bootstrap intervals. Exact counts are given in the results table.</desc>",
        "<style>text{font-family:system-ui,sans-serif;fill:#273342;font-size:13px}"
        ".heading{font-size:16px;font-weight:650}.axis{fill:#687380;font-size:11px}</style>",
    ]
    for offset, key, title, color in (
        (190, "false_acceptance", "Invalid controls accepted", "#ac432f"),
        (735, "false_rejection", "Valid controls rejected", "#285d98"),
    ):
        width = 340
        parts.append(f'<text class="heading" x="{offset}" y="28">{title}</text>')
        for tick in (0, 25, 50, 75, 100):
            x = offset + width * tick / 100
            parts.append(
                f'<line x1="{x}" y1="54" x2="{x}" y2="{height - 42}" '
                'stroke="#e3e5e8"/>'
                f'<text class="axis" x="{x}" y="{height - 20}" text-anchor="middle">'
                f"{tick}%</text>"
            )
        for index, name in enumerate(names):
            y = 76 + index * 40
            if offset == 190:
                parts.append(f'<text x="12" y="{y + 4}">{_escape(name)}</text>')
            metric = summary["graders"][name]
            rate = metric[key]
            if rate is None:
                parts.append(f'<text class="axis" x="{offset}" y="{y + 4}">No denominator</text>')
                continue
            interval = metric[f"{key}_ci"]
            if interval is not None:
                low = offset + interval[0] * width
                high = offset + interval[1] * width
                parts.append(
                    f'<path d="M {low} {y - 5} V {y + 5} M {low} {y} H {high} '
                    f'M {high} {y - 5} V {y + 5}" stroke="{color}" stroke-width="1.5"/>'
                )
            parts.append(
                f'<circle cx="{offset + rate * width}" cy="{y}" r="4" fill="{color}"/>'
                f'<text x="{offset + width + 18}" y="{y + 4}">{_percent(rate)}</text>'
            )
    if not names:
        parts.append('<text x="12" y="70">No audit episodes were recorded.</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _markdown(summary: dict[str, Any]) -> str:
    corpus = summary["corpus"]
    bootstrap = summary["bootstrap"]
    lines = [
        "# GateBench — verifier audit",
        "",
        "A controlled study of grader mistakes in a synthetic, stateful support environment.",
        "These are **scripted controls, not model benchmark results**. Expected labels are",
        "assigned by probe constructors from explicit workflow obligations; they are not",
        "computed by the hardened verifier.",
        "",
        f"**Corpus:** {corpus['tasks']} task instances, {corpus['episodes']} executable controls; "
        f"{corpus['positives']} valid and {corpus['negatives']} invalid.",
        f"**Splits:** {', '.join(corpus['splits']) or 'none'}. "
        f"**Families:** {', '.join(corpus['families']) or 'none'}.",
        "",
        "## Results",
        "",
        "False acceptance = invalid controls accepted / all invalid controls. False rejection =",
        "valid controls rejected / all valid controls. Neither metric implies an agent's intent.",
        "",
        "| Grader | False acceptance | 95% interval | False rejection | 95% interval | TP / TN / FP / FN |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in _names(summary):
        metric = summary["graders"][name]
        confusion = " / ".join(
            str(metric[cell])
            for cell in ("true_positive", "true_negative", "false_positive", "false_negative")
        )
        lines.append(
            f"| `{name}` | {_rate_cell(metric, 'false_acceptance')} "
            f"| {_ci(metric['false_acceptance_ci'])} "
            f"| {_rate_cell(metric, 'false_rejection')} "
            f"| {_ci(metric['false_rejection_ci'])} | {confusion} |"
        )
    lines += [
        "",
        "![False acceptance and false rejection with case-cluster intervals](error-rates.svg)",
        "",
        "## Paired false-acceptance difference",
        "",
        "Difference = grader minus hardened, in percentage points. Positive values mean the",
        "grader accepted more invalid controls. Each bootstrap draw uses the same case IDs for both.",
        "",
        "| Grader | Difference (pp) | 95% interval (pp) | Task clusters |",
        "|---|---:|---:|---:|",
    ]
    for name in _names(summary):
        paired = summary["paired_false_acceptance_difference_vs_hardened"].get(name)
        if paired is None:
            continue
        difference = paired["difference"]
        rendered = "—" if difference is None else f"{100 * difference:+.1f}"
        lines.append(
            f"| `{name}` | {rendered} | {_ci(paired['ci'], signed=True)} | {paired['tasks']} |"
        )
    for dimension, heading in (("family", "Workflow slices"), ("split", "Split slices")):
        lines += [
            "",
            f"## {heading}",
            "",
            "| Slice | Grader | Invalid accepted | Valid rejected |",
            "|---|---|---:|---:|",
        ]
        for value, group in summary["slices"][dimension].items():
            for name in _names(summary):
                metric = group["graders"][name]
                lines.append(
                    f"| {value} | `{name}` | {_rate_cell(metric, 'false_acceptance')} "
                    f"| {_rate_cell(metric, 'false_rejection')} |"
                )
    lines += [
        "",
        "## Method and interpretation",
        "",
        f"- Bootstrap: {bootstrap['samples']} draws; seed {bootstrap['seed']}; "
        "resampling unit is the complete task instance, including all sibling probes.",
        "- Point estimates are episode-weighted ratios of counts. Intervals are percentile",
        "  intervals over whole-case resamples, not independent-probe intervals.",
        "- Intervals describe sensitivity to the generated task mix. They do not estimate",
        "  real-world agent failure rates, and zero observed error does not prove completeness.",
        "- Slice tables show point estimates only. A missing denominator is shown as an em dash.",
        "- Multiple graders see exactly the same controls; the relative frequencies of curated",
        "  mutations affect aggregate error rates. Inspect failure families before comparing designs.",
        "- The eval split changes task parameters and includes designated composition probes.",
        "  Public generation code and labels do not constitute a secret or contamination-proof holdout.",
        "- Replay checks evidence consistency. It cannot authenticate a wholesale coherent forgery",
        "  or protect a compromised runner. Serialized corruption tests are separate from this corpus.",
        "- Success on this corpus is regression evidence for these explicit obligations, not",
        "  a general guarantee against reward hacking or evidence of any model's intent.",
        "",
        "## Grader definitions",
        "",
    ]
    for name in _names(summary):
        lines.append(f"- `{name}`: {_DESCRIPTIONS.get(name, 'Additional configured grader.')}")
    lines += [
        "",
        "Open `report.html` for the searchable control table, including independently assigned",
        "labels, rationales, and every grader's verdict. Raw evidence and run configuration are",
        "stored alongside this report by the audit runner.",
        "",
    ]
    return "\n".join(lines)


_STYLE = """
:root{color-scheme:light;--ink:#202c39;--muted:#64707b;--line:#dce1e5;--paper:#fbfaf7;
--red:#a83e2c;--blue:#285d98;--green:#2b674d}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,sans-serif}
main{max-width:1240px;margin:auto;padding:44px 36px 72px}a{color:var(--blue)}
.eyebrow,th,.label{font-size:11px;letter-spacing:.09em;text-transform:uppercase;font-weight:700}
.eyebrow{color:var(--muted)}h1{font-size:clamp(32px,5vw,54px);line-height:1.12;letter-spacing:-.04em;margin:15px 0}
h2{font-size:24px;letter-spacing:-.02em;margin:0 0 12px}p{max-width:850px}header p{font-size:17px;color:var(--muted)}
nav{display:flex;gap:22px;font-size:13px;margin:25px 0}section{margin-top:42px;padding-top:28px;border-top:1px solid var(--line)}
.badge{display:inline-block;border:1px solid var(--line);border-radius:3px;padding:3px 8px;font:11px/1.5 ui-monospace,monospace}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:28px 0}.card{border:1px solid var(--line);padding:18px;background:white}
.number{font-size:32px;line-height:1.25;letter-spacing:-.025em;font-variant-numeric:tabular-nums}.label{color:var(--muted);margin-top:6px}
.note{border-left:3px solid var(--blue);padding:10px 18px;background:#edf2f6;font-size:13px;max-width:950px}
.muted{color:var(--muted)}.small{font-size:12px}.scroll{overflow:auto}.chart{background:white;border:1px solid var(--line);padding:15px;margin:24px 0}.chart svg{display:block;width:100%;min-width:700px}
table{border-collapse:collapse;width:100%;font-size:13px;background:white}th{text-align:left;color:var(--muted);background:#f0f2f3;white-space:nowrap}td,th{padding:11px 13px;border-bottom:1px solid var(--line);vertical-align:top}td.numeric{font-variant-numeric:tabular-nums;white-space:nowrap}
code{font:12px ui-monospace,SFMono-Regular,monospace}.error{color:var(--red);font-weight:650}.correct{color:var(--green)}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:16px;margin:20px 0}input[type=search],select{padding:10px 12px;border:1px solid #bbc4cd;border-radius:3px;background:white;font:inherit;color:inherit}input[type=search]{min-width:300px;flex:1}label{font-size:13px}
.probe-name{font-weight:650}.rationale{max-width:480px;min-width:250px}.rationale small{display:block;color:var(--muted);margin-top:5px}#control-table th{position:sticky;top:0}.control-scroll{max-height:620px;overflow:auto;border:1px solid var(--line)}
.definitions{display:grid;grid-template-columns:1fr 1fr;gap:6px 30px;font-size:13px}.definitions p{margin:5px 0}.method li{margin:9px 0;max-width:930px}footer{margin-top:48px;color:var(--muted);font-size:12px}
@media(max-width:700px){main{padding:24px 16px}.cards{grid-template-columns:1fr 1fr}.definitions{grid-template-columns:1fr}.controls{display:block}.controls>*{display:block;margin:10px 0}input[type=search]{width:100%;min-width:0}.card{padding:12px}.number{font-size:27px}}
@media print{body{background:white}.controls,.control-scroll,nav{display:none}main{max-width:none;padding:0}section{break-inside:avoid}.cards{grid-template-columns:repeat(4,1fr)}}
"""


def _html(summary: dict[str, Any], rows: list[dict[str, Any]], plot: str) -> str:
    corpus = summary["corpus"]
    names = _names(summary)
    metric_rows = []
    for name in names:
        metric = summary["graders"][name]
        confusion = " / ".join(
            str(metric[key])
            for key in ("true_positive", "true_negative", "false_positive", "false_negative")
        )
        metric_rows.append(
            f"<tr><td><code>{_escape(name)}</code></td>"
            f"<td class='numeric'>{_rate_cell(metric, 'false_acceptance')}</td>"
            f"<td class='numeric'>{_ci(metric['false_acceptance_ci'])}</td>"
            f"<td class='numeric'>{_rate_cell(metric, 'false_rejection')}</td>"
            f"<td class='numeric'>{_ci(metric['false_rejection_ci'])}</td>"
            f"<td class='numeric'>{confusion}</td></tr>"
        )
    paired_rows = []
    for name in names:
        paired = summary["paired_false_acceptance_difference_vs_hardened"].get(name)
        if paired is None:
            continue
        difference = paired["difference"]
        rendered = "—" if difference is None else f"{100 * difference:+.1f}"
        paired_rows.append(
            f"<tr><td><code>{_escape(name)}</code></td><td class='numeric'>{rendered}</td>"
            f"<td class='numeric'>{_ci(paired['ci'], signed=True)}</td>"
            f"<td class='numeric'>{paired['tasks']}</td></tr>"
        )
    slices = []
    for family, group in summary["slices"]["family"].items():
        for name in names:
            metric = group["graders"][name]
            slices.append(
                f"<tr><td>{_escape(family)}</td><td><code>{_escape(name)}</code></td>"
                f"<td class='numeric'>{_rate_cell(metric, 'false_acceptance')}</td>"
                f"<td class='numeric'>{_rate_cell(metric, 'false_rejection')}</td></tr>"
            )
    controls = []
    for row in rows:
        expected = row["expected"]
        disagreement = any(value != expected for value in row["graders"].values())
        search = " ".join(
            str(row.get(key, ""))
            for key in ("task_id", "family", "split", "probe", "category", "rationale")
        )
        cells = []
        for name in names:
            passed = row["graders"][name]
            incorrect = passed != expected
            label = "accept" if passed else "reject"
            if incorrect:
                label += " · FP" if passed else " · FN"
            cells.append(f"<td class='{'error' if incorrect else 'correct'}'>{label}</td>")
        controls.append(
            f"<tr data-search='{_escape(search.lower())}' data-family='{_escape(row['family'])}' "
            f"data-disagreement='{str(disagreement).lower()}'>"
            f"<td class='rationale'><span class='probe-name'>{_escape(row['probe'])}</span>"
            f"<small>{_escape(row['task_id'])} · {_escape(row['split'])}</small>"
            f"<small>{_escape(row.get('rationale', ''))}</small></td>"
            f"<td>{_escape(row['family'])}</td><td>{'valid' if expected else 'invalid'}</td>"
            + "".join(cells)
            + "</tr>"
        )
    options = "".join(f"<option>{_escape(family)}</option>" for family in corpus["families"])
    definitions = "".join(
        f"<p><code>{_escape(name)}</code><br>{_escape(_DESCRIPTIONS.get(name, 'Additional configured grader.'))}</p>"
        for name in names
    )
    bootstrap = summary["bootstrap"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GateBench · Verifier audit</title><style>{_STYLE}</style></head>
<body><main><header><div class="eyebrow">GateBench / Research artifact / v0.1</div>
<h1>Can you trust the score?</h1><p>A controlled audit of what tool-agent graders accept, what they miss, and which valid alternatives they reject.</p>
<span class="badge">SCRIPTED CONTROLS · SYNTHETIC WORKFLOWS</span>
<nav aria-label="Report sections"><a href="#results">Results</a><a href="#controls">Inspect controls</a><a href="#method">Method</a></nav></header>
<div class="cards"><div class="card"><div class="number">{corpus["tasks"]:,}</div><div class="label">Task instances</div></div>
<div class="card"><div class="number">{corpus["episodes"]:,}</div><div class="label">Executed controls</div></div>
<div class="card"><div class="number">{corpus["positives"]:,}</div><div class="label">Valid controls</div></div>
<div class="card"><div class="number">{corpus["negatives"]:,}</div><div class="label">Invalid controls</div></div></div>
<p class="note">This is a verifier regression study, not a model leaderboard. Labels come from independently specified workflow obligations. No model capability, intent, or real-world exploit rate is inferred.</p>
<section id="results"><h2>Two ways a grader can be wrong</h2><p class="muted">False acceptance counts invalid controls that pass. False rejection counts valid controls that fail. Points are observed rates; bars show 95% case-cluster bootstrap intervals.</p>
<div class="chart scroll">{plot}</div><div class="scroll"><table><thead><tr><th>Grader</th><th>Invalid accepted</th><th>95% interval (%)</th><th>Valid rejected</th><th>95% interval (%)</th><th>TP / TN / FP / FN</th></tr></thead><tbody>{"".join(metric_rows)}</tbody></table></div>
<p class="small muted">Rates show exact numerator / denominator. An em dash means there was no applicable denominator or no bootstrap draw.</p>
<details><summary>Paired difference from hardened</summary><p class="small">Grader minus hardened, in percentage points. Identical task clusters are sampled for both graders in every bootstrap draw.</p><div class="scroll"><table><thead><tr><th>Grader</th><th>Difference (pp)</th><th>95% interval (pp)</th><th>Task clusters</th></tr></thead><tbody>{"".join(paired_rows)}</tbody></table></div></details>
<details><summary>Results by workflow</summary><div class="scroll"><table><thead><tr><th>Workflow</th><th>Grader</th><th>Invalid accepted</th><th>Valid rejected</th></tr></thead><tbody>{"".join(slices)}</tbody></table></div></details></section>
<section id="controls"><h2>Inspect the disagreements</h2><p class="muted">Each row is an executable plan run against a fresh SQLite environment. FP and FN mark disagreement with its independently assigned label.</p>
<div class="controls"><input type="search" id="search" placeholder="Find a task, probe, or policy rationale" aria-label="Search controls"><select id="family" aria-label="Workflow filter"><option value="">All workflows</option>{options}</select><label><input id="disagreements" type="checkbox"> Errors only</label><span class="small muted" id="row-count" aria-live="polite">{len(rows)} controls</span></div>
<div class="control-scroll"><table id="control-table"><thead><tr><th>Control / rationale</th><th>Workflow</th><th>Expected</th>{"".join(f"<th>{_escape(name)}</th>" for name in names)}</tr></thead><tbody>{"".join(controls)}</tbody></table></div></section>
<section><h2>What each grader sees</h2><div class="definitions">{definitions}</div></section>
<section id="method" class="method"><h2>Method and limits</h2><ul>
<li><strong>Paired case clusters.</strong> {bootstrap["samples"]:,} bootstrap draws, seed {bootstrap["seed"]}. A draw resamples whole task IDs with all their sibling probes. Estimates are episode-weighted ratios of counts. Family slices show point estimates only.</li>
<li><strong>Curated control frequencies.</strong> Aggregate rates depend on how often each mutation appears in this corpus. The intervals describe sensitivity to the generated task mix; they do not estimate real-world agent failure rates.</li>
<li><strong>Public procedural splits.</strong> Splits: {_escape(", ".join(corpus["splits"]) or "none")}. The eval split changes parameters and includes designated composition probes. Public generators and labels are not a secret or contamination-proof holdout.</li>
<li><strong>Executable violations and evidence corruption are separate.</strong> These controls change actual tool actions. Serialized input-corruption tests belong to a separate integrity suite.</li>
<li><strong>Consistency is not authenticity.</strong> Independent replay checks recorded state transitions and evidence consistency. It does not authenticate a wholesale coherent forgery or secure a compromised runner. The trusted runner must own journal collection.</li>
<li><strong>Bounded claims.</strong> Zero observed error means these specified controls passed. It does not prove verifier completeness or general resistance to reward hacking. No model result or intentional exploit is implied.</li>
</ul></section><footer>Generated from the audit's recorded controls. This report is self-contained and works offline. The Markdown report and SVG are available beside it.</footer>
</main><script>
const search=document.getElementById('search');
const family=document.getElementById('family');
const errors=document.getElementById('disagreements');
const rows=Array.from(document.querySelectorAll('#control-table tbody tr'));
function filterRows(){{
  const query=search.value.toLocaleLowerCase().trim(); let shown=0;
  rows.forEach(row=>{{const visible=row.dataset.search.includes(query)&&(!family.value||row.dataset.family===family.value)&&(!errors.checked||row.dataset.disagreement==='true');row.hidden=!visible;if(visible)shown++;}});
  document.getElementById('row-count').textContent=shown+' / '+rows.length+' controls';
}}
search.addEventListener('input',filterRows);family.addEventListener('change',filterRows);errors.addEventListener('change',filterRows);
</script></body></html>"""


def write_report(summary: dict[str, Any], rows: list[dict[str, Any]], output_dir: Path) -> None:
    """Write a portable HTML report, Markdown interpretation, and an SVG figure."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plot = _error_plot(summary)
    (output_dir / "error-rates.svg").write_text(plot + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(_markdown(summary), encoding="utf-8")
    (output_dir / "report.html").write_text(_html(summary, rows, plot) + "\n", encoding="utf-8")
    # This small sidecar makes the figure's exact source data easy to inspect.
    (output_dir / "report-data.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
