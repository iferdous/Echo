"""Render evidence plots from verified data with the optional demo group."""

import os
from pathlib import Path


def plot_classifier(model: dict, out: Path, *, png: bool = True) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(out / ".matplotlib"))
    import matplotlib as mpl
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import PercentFormatter

    with mpl.rc_context({"svg.hashsalt": "echo-stage7", "font.family": "DejaVu Sans"}):
        paper, ink, muted = "#f5f4eb", "#142822", "#4d5b54"
        figure = Figure(figsize=(9.8, 4.9), dpi=135, facecolor=paper)
        FigureCanvasAgg(figure)
        axes = figure.add_axes((0.26, 0.23, 0.66, 0.49), facecolor=paper)
        scale = [model["comparison_accuracy"] * 100, model["exposed_accuracy"] * 100]
        axes.barh([1, 0], scale, height=0.47, color=["#526d7a", "#126751"], zorder=3)
        axes.set_xlim(0, 101)
        axes.set_yticks(
            [1, 0], ["Independent\ntraining crops", "Crops from test\nrecordings"]
        )
        axes.set_xticks(range(0, 101, 20))
        axes.xaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
        axes.grid(axis="x", color="#d5d9cf", zorder=0)
        axes.tick_params(length=0, colors=ink, labelsize=11)
        axes.tick_params(axis="y", pad=12)
        axes.spines[:].set_visible(False)
        for y, rate in zip((1, 0), scale, strict=True):
            axes.text(
                rate + 2,
                y,
                f"{rate:.1f}%",
                va="center",
                color=ink,
                fontsize=15,
                weight="bold",
            )
        figure.text(
            0.055,
            0.90,
            "Shared training audio raised the test score",
            fontsize=20,
            weight="bold",
            color=ink,
        )
        figure.text(
            0.055,
            0.81,
            f"Mean accuracy on the same {model['test_rows']} ESC-50 clips across {len(model['rates_by_seed'])} paired seeds",
            fontsize=12,
            color=muted,
        )
        figure.text(
            0.055,
            0.105,
            f"+{model['delta_points']:.2f} percentage points",
            fontsize=15,
            weight="bold",
            color="#126751",
        )
        low, high = model["delta_range_points"]
        figure.text(
            0.055,
            0.046,
            f"Per-seed gain {low:+.2f} to {high:+.2f} points  ·  Run {model['run_id'][:12]}",
            fontsize=9.5,
            color=muted,
        )
        chart = out / "leakage-accuracy.svg"
        figure.savefig(chart, metadata={"Date": None})
        lines = chart.read_text(encoding="utf-8").splitlines()
        chart.write_text(
            "".join(line.rstrip() + "\n" for line in lines),
            encoding="utf-8",
            newline="\n",
        )
        if png:
            figure.savefig(out / "leakage-accuracy.png")


def plot_timing(timing: dict, out: Path) -> None:
    import matplotlib as mpl
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    with mpl.rc_context(
        {"svg.hashsalt": "echo-stage8-timing", "font.family": "DejaVu Sans"}
    ):
        paper, ink = "#f5f4eb", "#142822"
        figure = Figure(figsize=(9.8, 4.9), dpi=135, facecolor=paper)
        FigureCanvasAgg(figure)
        axis = figure.add_axes((0.24, 0.20, 0.70, 0.55), facecolor=paper)
        workloads = ("stage2", "stage4")
        engines = ("tuned", "rust")
        max_median = max(
            timing[stage]["engines"][engine]["warm_connection"]["p50_ms"]
            for stage in workloads
            for engine in engines
        )
        for y, stage in zip((1, 0), workloads, strict=True):
            for offset, engine, color in (
                (0.16, "tuned", "#526d7a"),
                (-0.16, "rust", "#126751"),
            ):
                ms = timing[stage]["engines"][engine]["warm_connection"]["p50_ms"]
                axis.barh(
                    y + offset,
                    ms,
                    height=0.25,
                    color=color,
                    zorder=3,
                    label=engine if y == 1 else None,
                )
                axis.text(
                    ms + max_median * 0.02,
                    y + offset,
                    f"{ms:.0f}",
                    va="center",
                    color=ink,
                    fontsize=10,
                )
        axis.set(
            xlim=(0, max_median * 1.2),
            yticks=[1, 0],
            yticklabels=["ESC-50 crops", "ESC-50 → FSD50K"],
        )
        axis.set_xlabel(
            "Warm median time per query (ms)", fontsize=10, color=ink, labelpad=8
        )
        axis.grid(axis="x", color="#d5d9cf", zorder=0)
        axis.tick_params(length=0, colors=ink, labelsize=10)
        axis.spines[:].set_visible(False)
        handles, _ = axis.get_legend_handles_labels()
        figure.legend(
            handles,
            ["Tuned Python", "Rust"],
            loc="lower right",
            bbox_to_anchor=(0.94, 0.025),
            frameon=False,
            ncol=2,
        )
        figure.text(
            0.055,
            0.90,
            "Warm query latency by workload",
            fontsize=20,
            weight="bold",
            color=ink,
        )
        figure.text(
            0.055,
            0.81,
            "Apple M3 · One reused SQLite connection · Three timed passes",
            fontsize=11,
            color="#4d5b54",
        )
        chart = out / "timing.svg"
        figure.savefig(chart, metadata={"Date": None})
        lines = chart.read_text(encoding="utf-8").splitlines()
        chart.write_text(
            "".join(line.rstrip() + "\n" for line in lines),
            encoding="utf-8",
            newline="\n",
        )
