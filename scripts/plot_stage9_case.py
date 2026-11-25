"""Chart the recorded split decision and the dog-bark alignment."""

import os
from pathlib import Path


def plot_case(case, output: Path, scratch: Path):
    os.environ.setdefault("MPLCONFIGDIR", str(scratch / ".matplotlib"))
    import matplotlib as mpl
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    paper, ink, muted = "#f5f4eb", "#142822", "#4d5b54"
    with mpl.rc_context({"svg.hashsalt": "echo-stage9", "font.family": "DejaVu Sans"}):
        figure = Figure(figsize=(9.8, 4.8), dpi=130, facecolor=paper)
        FigureCanvasAgg(figure)
        figure.text(
            0.06,
            0.91,
            "Reviewing an audio evaluation split",
            color=ink,
            fontsize=21,
            weight="bold",
        )
        total = case["initial_audit"]["query_count"]
        references = case["initial_audit"]["indexed_assets"]
        figure.text(
            0.06,
            0.83,
            f"{total} proposed ESC-50 test clips against {references} indexed FSD50K eval clips",
            color=muted,
            fontsize=11,
        )

        split = figure.add_axes((0.06, 0.62, 0.88, 0.12), facecolor=paper)
        start = 0
        for action, label, color in (
            ("quarantine", "quarantined", "#763627"),
            ("hold", "held", "#745722"),
            ("retain", "retained", "#126751"),
        ):
            count = case["release_actions"][action]
            split.barh(0, count, left=start, height=0.68, color=color)
            split.text(
                start + count / 2,
                0,
                f"{count} {label}",
                ha="center",
                va="center",
                color="white",
                fontsize=10,
                weight="bold",
            )
            start += count
        split.set(xlim=(0, total), ylim=(-0.5, 0.5))
        split.axis("off")

        example = case["examples"][0]
        query = example["matcher_query_interval_seconds"]
        reference = example["matcher_reference_interval_seconds"]
        offset = float(example["matcher_offset_seconds"])
        waveform_offset = float(example["waveform_offset_seconds"])
        figure.text(
            0.06,
            0.51,
            "One dog bark, two different files",
            color=ink,
            fontsize=14,
            weight="bold",
        )
        figure.text(
            0.06,
            0.453,
            f"Echo offset {offset:+.3f} s  ·  waveform check {waveform_offset:+.3f} s",
            color=muted,
            fontsize=10,
        )
        axis = figure.add_axes((0.25, 0.14, 0.68, 0.25), facecolor=paper)
        axis.set_axisbelow(True)
        for y, (lo, hi), color in ((1, query, "#526d7a"), (0, reference, "#126751")):
            axis.barh(y, hi - lo, left=lo, height=0.42, color=color)
            axis.text(
                (lo + hi) / 2,
                y,
                f"{lo:.3f}–{hi:.3f} s",
                ha="center",
                va="center",
                color="white",
                fontsize=11,
            )
        axis.set(
            xlim=(0, 6),
            yticks=[1, 0],
            yticklabels=["ESC-50", "FSD50K"],
            xticks=range(7),
        )
        axis.grid(axis="x", color="#d6d9d0")
        axis.tick_params(axis="both", length=0, labelsize=10, colors=ink)
        axis.spines[:].set_visible(False)
        axis.set_xlabel(
            "Seconds in each source file", fontsize=10, labelpad=6, color=muted
        )
        figure.savefig(output, metadata={"Date": None})
        lines = output.read_text(encoding="utf-8").splitlines()
        output.write_text(
            "".join(line.rstrip() + "\n" for line in lines),
            encoding="utf-8",
            newline="\n",
        )
