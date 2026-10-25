"""Render the primary model study without adding plotting to GateBench's dependencies.

Run from the repository root:
    uv run --no-project --with matplotlib python scripts/plot_model_study.py

The figure reads the published summary; it does not recompute or alter the study.
An adjacent metadata file records the input hash and the plotting environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

MODELS = (
    ("qwen3.5:2b-q4_K_M", "Qwen3.5 2B", "#0072B2", "o"),
    ("qwen3.5:4b-q4_K_M", "Qwen3.5 4B", "#D55E00", "s"),
)
GRADERS = (
    ("transcript", "Transcript wording"),
    ("goal", "Requested goal"),
    ("final_state", "Final state"),
    ("exact_trace", "Exact trace"),
    ("hardened", "Full checks"),
)


def interval(record: dict, field: str) -> tuple[float, float, float]:
    """Reject missing or malformed intervals rather than silently drawing them."""
    value = record[field]
    bounds = record["ci"]
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("the figure requires precomputed confidence intervals")
    lo, hi = bounds
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (lo, value, hi)):
        raise ValueError("estimates and confidence limits must be numeric")
    if not all(math.isfinite(x) for x in (lo, value, hi)) or not 0 <= lo <= value <= hi <= 1:
        raise ValueError("invalid estimate or confidence interval")
    return value * 100, lo * 100, hi * 100


def validate(summary: dict) -> None:
    corpus = summary["corpus"]
    if corpus["domains"] != ["gatebench"] or corpus["repeats"] != 3:
        raise ValueError("this figure is for the three-repeat primary GateBench study")
    if set(summary["models"]) != {item[0] for item in MODELS}:
        raise ValueError("expected the Qwen3.5 2B and 4B Q4_K_M comparison")
    bootstrap = summary["bootstrap"]
    if bootstrap["unit"] != "domain+task_id" or bootstrap["confidence"] != 0.95:
        raise ValueError("the figure requires task-cluster 95% confidence intervals")
    for key, *_ in MODELS:
        model = summary["models"][key]
        expected_trials = model["task_clusters"] * corpus["repeats"]
        if model["trials"] != expected_trials or model["task_clusters"] != corpus["task_clusters"]:
            raise ValueError("each model must have the complete repeated task matrix")
        for grader, _ in GRADERS:
            record = model["graders"][grader]
            passed, trials = record["passed"], record["trials"]
            if (
                type(passed) is not int
                or type(trials) is not int
                or trials != expected_trials
                or not 0 <= passed <= trials
                or not math.isclose(record["rate"], passed / trials, abs_tol=1e-12)
            ):
                raise ValueError("grader counts do not match the reported rate")
            interval(record, "rate")
        for k in range(1, 4):
            interval(model["consistency"]["hardened"][f"pass^{k}"], "estimate")
    if sum(m["trials"] for m in summary["models"].values()) != corpus["trials"]:
        raise ValueError("model trial counts do not match the corpus")


def style_axis(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#B7C0C7")
    ax.tick_params(colors="#44515B", length=0, pad=7)
    ax.set_axisbelow(True)


def draw(summary: dict, destination: Path) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "text.color": "#172B3A",
            "axes.labelcolor": "#44515B",
            "svg.hashsalt": "gatebench-model-study-v1",
            "svg.fonttype": "none",
            "savefig.facecolor": "white",
        }
    )
    corpus, bootstrap = summary["corpus"], summary["bootstrap"]
    tasks, repeats = corpus["task_clusters"], corpus["repeats"]
    trials = summary["models"][MODELS[0][0]]["trials"]
    fig = plt.figure(figsize=(12.4, 6.5), facecolor="white")
    ax = fig.add_axes((0.17, 0.29, 0.395, 0.45))
    consistency = fig.add_axes((0.765, 0.29, 0.205, 0.45))

    fig.text(
        0.035, 0.935, "What the verifier accepts changes the result", fontsize=19, weight="bold"
    )
    fig.text(
        0.035,
        0.885,
        f"GateBench primary study  ·  {corpus['trials']} local model trials  ·  "
        "same model family and Q4_K_M quantization",
        fontsize=10.5,
        color="#53636F",
    )
    legend = [
        Line2D(
            [0],
            [0],
            color=color,
            marker=marker,
            linestyle="none",
            markersize=6,
            label=f"{label}  (n = {summary['models'][key]['trials']})",
        )
        for key, label, color, marker in MODELS
    ]
    fig.legend(
        handles=legend,
        loc="upper left",
        bbox_to_anchor=(0.027, 0.852),
        ncol=2,
        frameon=False,
        handletextpad=0.45,
        columnspacing=2.3,
        fontsize=10,
    )

    style_axis(ax)
    ax.spines["left"].set_visible(False)
    ax.set_title("A   Acceptance by verifier", loc="left", pad=22)
    ax.set_xlim(0, 100)
    ax.set_xticks((0, 25, 50, 75, 100))
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    ax.set_xlabel("Accepted trials", labelpad=12)
    ax.set_yticks(range(len(GRADERS)), [label for _, label in GRADERS])
    ax.set_ylim(len(GRADERS) - 0.5, -0.5)
    ax.grid(axis="x", color="#E5E9ED", linewidth=0.8)
    ax.axhspan(3.56, 4.44, color="#F2F5F7", zorder=0)
    ax.text(1.065, 1.045, "Accepted / trials", transform=ax.transAxes, fontsize=9, color="#53636F")

    for index, (key, _, color, marker) in enumerate(MODELS):
        offset = -0.14 if index == 0 else 0.14
        for y, (grader, _) in enumerate(GRADERS):
            record = summary["models"][key]["graders"][grader]
            value, lo, hi = interval(record, "rate")
            ax.errorbar(
                value,
                y + offset,
                xerr=[[value - lo], [hi - value]],
                fmt=marker,
                color=color,
                markersize=6,
                elinewidth=1.6,
                capsize=3.3,
                capthick=1.2,
                clip_on=False,
                zorder=3,
            )
            ax.text(
                1.065,
                y + offset,
                f"{record['passed']:2d} / {record['trials']}",
                transform=ax.get_yaxis_transform(),
                va="center",
                color=color,
                fontsize=10,
                fontfamily="DejaVu Sans Mono",
            )

    style_axis(consistency)
    consistency.set_title("B   Repeat consistency", loc="left", pad=22)
    consistency.set_xlim(0.7, 3.3)
    consistency.set_ylim(0, 100)
    consistency.set_yticks((0, 25, 50, 75, 100))
    consistency.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    consistency.set_xticks((1, 2, 3), (r"pass$^1$", r"pass$^2$", r"pass$^3$"))
    consistency.set_xlabel("Full-check consistency", labelpad=12)
    consistency.grid(axis="y", color="#E5E9ED", linewidth=0.8)
    for index, (key, _, color, marker) in enumerate(MODELS):
        offset = -0.075 if index == 0 else 0.075
        xs, ys = [], []
        for k in range(1, 4):
            record = summary["models"][key]["consistency"]["hardened"][f"pass^{k}"]
            value, lo, hi = interval(record, "estimate")
            x = k + offset
            xs.append(x)
            ys.append(value)
            consistency.errorbar(
                x,
                value,
                yerr=[[value - lo], [hi - value]],
                fmt=marker,
                color=color,
                markersize=5.5,
                elinewidth=1.25,
                capsize=3,
                capthick=1,
                clip_on=False,
                zorder=3,
            )
            consistency.annotate(
                f"{value:.1f}",
                (x, value),
                xytext=(0, -16 if index == 0 else 9),
                textcoords="offset points",
                ha="center",
                color=color,
                fontsize=9,
            )
        consistency.plot(xs, ys, color=color, linewidth=1.1, alpha=0.6, zorder=2)

    fig.add_artist(Line2D([0.035, 0.97], [0.185, 0.185], color="#DCE2E7", linewidth=0.8))
    caption = (
        f"Each model: {tasks} tasks × {repeats} repeats = {trials} trials. Whiskers: task-cluster "
        f"95% percentile CIs ({bootstrap['samples']:,} resamples; seed {bootstrap['seed']}).\n"
        "Acceptance measures agreement with an encoded verifier, not independently established correctness. "
        "Zero-width intervals reflect this sample only.\n"
        r"pass$^k$ estimates acceptance on all $k$ repeats; pass$^3$ requires all three. "
        "Closure-resolution wording limits the interpretation of cancellation scores; see the case study."
    )
    fig.text(0.035, 0.135, caption, va="top", fontsize=9.0, color="#53636F", linespacing=1.65)

    destination.parent.mkdir(parents=True, exist_ok=True)
    description = (
        "GateBench primary-study verifier acceptance and full-check repeated-trial consistency. "
        f"Each model has {tasks} tasks and {repeats} repeats. "
        "Whiskers are task-cluster 95% confidence intervals. "
        "Verifier acceptance is not independent ground truth."
    )
    fig.savefig(
        destination.with_suffix(".svg"),
        metadata={
            "Title": "GateBench model-study acceptance",
            "Description": description,
            "Date": None,
        },
    )
    fig.savefig(
        destination.with_suffix(".png"),
        dpi=300,
        metadata={"Title": "GateBench model-study acceptance", "Description": description},
    )
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary", type=Path, default=Path("docs/studies/real-models-v1/summary.json")
    )
    parser.add_argument("--output", type=Path, default=Path("docs/figures/model-acceptance"))
    args = parser.parse_args()
    source = args.summary.read_bytes()
    summary = json.loads(source)
    validate(summary)
    draw(summary, args.output)
    metadata = {
        "schema_version": 1,
        "kind": "model_study_figure",
        "source_summary": str(args.summary),
        "source_summary_sha256": hashlib.sha256(source).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": platform.python_version(),
        "matplotlib_version": matplotlib.__version__,
        "plotting_environment": "optional; outside the frozen model-collection source closure",
        "corpus": summary["corpus"],
        "bootstrap": summary["bootstrap"],
        "grader_order": [key for key, _ in GRADERS],
        "outputs": {
            suffix: hashlib.sha256(args.output.with_suffix(suffix).read_bytes()).hexdigest()
            for suffix in (".svg", ".png")
        },
    }
    args.output.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
