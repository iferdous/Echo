"""Build the HyperFrames source directory from a verified Stage 7 walkthrough."""

import argparse
import json
import os
from pathlib import Path
from shutil import copyfile

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory

DEMO = Path(__file__).resolve().parents[1] / "docs" / "demo"


def plot_alignment(run: Path, assets: Path, start: float) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(run / ".matplotlib"))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    paper, ink = "#f5f4eb", "#142822"
    figure = Figure(figsize=(6.1, 3.05), dpi=135, facecolor=paper)
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 1, sharex=True)
    for axis, track, color, origin, title in zip(
        axes,
        ("train/reference.wav", "test/renamed-crop.wav"),
        ("#526d7a", "#126751"),
        (0, start),
        ("Reference timeline", "Copied excerpt at its true position"),
        strict=True,
    ):
        samples, rate = sf.read(run / track)
        chunks = samples.reshape(-1, 100)
        times = np.arange(len(chunks)) * 100 / rate + origin
        axis.fill_between(times, chunks.min(axis=1), chunks.max(axis=1), color=color)
        axis.axvspan(start, start + 2, color="#dfece0", zorder=0)
        axis.set(xlim=(0, 4), ylim=(-0.6, 0.6), yticks=[], facecolor=paper)
        axis.set_title(title, loc="left", fontsize=11, color=ink)
        axis.spines[["left", "right", "top"]].set_visible(False)
        axis.tick_params(axis="x", length=0, colors=ink)
    axes[-1].set_xticks(range(5), [f"{i} s" for i in range(5)])
    figure.subplots_adjust(left=0.04, right=0.97, top=0.86, bottom=0.15, hspace=0.63)
    figure.savefig(assets / "alignment.png")


def prepare(run: Path, gsap: Path, out: Path) -> None:
    data = json.loads((run / "evidence.json").read_text(encoding="utf-8"))
    walk = data["walkthrough"]
    commands = walk["commands"]
    cross = data["cross_dataset"]
    failure = cross["failure"]
    bench = data["benchmark"]
    expected = walk["expected_offset_seconds"]
    values = {
        "matchCommand": "$ echo-audit " + " ".join(commands["match_text"]["args"]),
        "matchResult": commands["match_text"]["stdout"],
        "controlCommand": "$ echo-audit " + " ".join(commands["control_text"]["args"]),
        "controlResult": commands["control_text"]["stdout"],
        "expected": f"{expected:.3f} s",
        "failurePair": f"{failure['query_id']} → {failure['reference_id']}",
        "missOffset": f"{failure['matcher_offset_s']:+.3f} s",
        "verifiedOffset": f"{failure['waveform_offset_s']:+.3f} s",
        "verifiedWindows": f"{failure['waveform_windows']} half-second windows supported the shared signal.",
        "directDelta": f"+{data['classifier']['direct_delta_points']:.2f} points",
        "benchmark": f"{bench['correct_accepts']} / {bench['matching_trials']}",
        "benchmarkNegative": f"{bench['accepted_absent']} accepted among {bench['absent_trials']} absent-source trials in this benchmark.",
        "crossMatches": f"{cross['matched_with_agreeing_offset']} / {cross['confirmed_pairs']}",
        "crossScope": f"Waveform-confirmed pairs within the {cross['queries']}-query audit of {cross['references']} references.",
        "speedup": f"{data['profiling']['cross_dataset_reduction_percent']:.0f}%",
    }
    with new_output_directory(out):
        assets = out / "assets"
        assets.mkdir()
        copyfile(DEMO / "video/index.html", out / "index.html")
        copyfile(DEMO / "review-preview.png", assets / "review-preview.png")
        copyfile(gsap, assets / "gsap.min.js")
        copyfile(run / "leakage-accuracy.png", assets / "leakage-accuracy.png")
        for name in (
            "train/reference.wav",
            "test/renamed-crop.wav",
            "test/similar-control.wav",
        ):
            copyfile(run / name, assets / Path(name).name)
        plot_alignment(run, assets, expected)
        (assets / "evidence.js").write_text(
            "window.ECHO_EVIDENCE = " + json.dumps(values, ensure_ascii=True) + ";\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("--walkthrough", "--gsap", "--out"):
        parser.add_argument(name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.walkthrough, args.gsap, args.out)


if __name__ == "__main__":
    main()
