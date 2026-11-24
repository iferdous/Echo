"""Run the public Echo walkthrough and generate charts from published evidence."""

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import copyfile
from statistics import mean

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.fixtures import CROP_SAMPLES, CROP_START, SAMPLE_RATE

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs" / "results"


def evidence() -> dict:
    stages = {
        "benchmark": "stage-3-test-summary.json",
        "cross_dataset": "stage-4-summary.json",
        "classifier": "stage-5-summary.json",
        "profiling": "stage-6/comparison.json",
    }
    summaries = {
        name: json.loads((RESULTS / path).read_text(encoding="utf-8"))
        for name, path in stages.items()
    }
    match = summaries["benchmark"]["metrics"]["match"]
    cross = summaries["cross_dataset"]
    ml = summaries["classifier"]
    timings = summaries["profiling"]["workloads"]
    inputs = {
        "stage-3-test-queries.csv": summaries["benchmark"]["results_sha256"],
        "stage-4-audit-queries.csv": cross["queries_sha256"],
        "stage-4-reviews.csv": cross["reviews_sha256"],
        "stage-5-predictions.csv": ml["files"]["predictions.csv"],
        "stage-5-design/test.csv": ml["test_manifest_sha256"],
    }
    for name, digest in inputs.items():
        if sha256_file(RESULTS / name) != digest:
            raise ValueError(
                f"{name}: saved evidence differs from its published digest"
            )

    with (RESULTS / "stage-4-audit-queries.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        miss = next(
            row
            for row in csv.DictReader(file)
            if row["outcome"] == "confirmed_audio_matcher_miss"
        )
    with (RESULTS / "stage-4-reviews.csv").open(newline="", encoding="utf-8") as file:
        checked = next(
            row
            for row in csv.DictReader(file)
            if row["query_id"] == miss["query_id"]
            and row["reference_id"] == miss["expected_reference"]
            and row["verdict"] == "confirmed"
        )
    test_accuracy = ml["slices"]["all"]
    with (RESULTS / "stage-5-design/test.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        test = [
            (row["asset_id"], row["label"], row["sha256"])
            for row in csv.DictReader(file)
        ]
    with (RESULTS / "stage-5-predictions.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        predictions = list(csv.DictReader(file))
    seeds = ml["seeds"]
    rates = {}
    for seed in seeds:
        selected = [row for row in predictions if int(row["seed"]) == seed]
        if [
            (row["asset_id"], row["label"], row["wav_sha256"]) for row in selected
        ] != test:
            raise ValueError(
                f"seed {seed}: prediction rows disagree with the fixed test manifest"
            )
        rates[seed] = {
            arm: mean(row[f"{arm}_prediction"] == row["label"] for row in selected)
            for arm in ("comparison", "exposed")
        }
    if len(predictions) != len(seeds) * len(test) or any(
        not np.isclose(
            mean(row[arm] for row in rates.values()),
            test_accuracy[f"{arm}_mean_accuracy"],
        )
        for arm in ("comparison", "exposed")
    ):
        raise ValueError("saved predictions disagree with published model accuracy")

    return {
        "source_sha256": {
            **inputs,
            **{path: sha256_file(RESULTS / path) for path in stages.values()},
        },
        "benchmark": {
            "correct_accepts": match["correct_accepts"],
            "matching_trials": match["positives"],
            "accepted_absent": match["false_accepts"],
            "absent_trials": match["absent"],
            "positive_sources": summaries["benchmark"]["metrics"]["source_groups"][
                "positive_source_groups"
            ],
            "absent_sources": summaries["benchmark"]["metrics"]["source_groups"][
                "absent_source_groups"
            ],
        },
        "cross_dataset": {
            "queries": cross["batch"]["query_count"],
            "references": cross["batch"]["indexed_assets"],
            "confirmed_pairs": cross["review"]["by_reason"]["known_source"][
                "confirmed"
            ],
            "known_source_pairs": cross["full_metadata"]["esc50_shared_fsd_eval"],
            "matched_with_agreeing_offset": cross["coverage"]["outcomes"][
                "confirmed_audio_matched"
            ]["query_rows"],
            "failure": {
                "query_id": miss["query_id"],
                "reference_id": miss["expected_reference"],
                "decision": miss["matcher_decision"],
                "matcher_offset_s": float(miss["top_offset_seconds"]),
                "waveform_offset_s": float(checked["offset_seconds"]),
                "waveform_windows": int(checked["aligned_windows"]),
                "review_source": checked["reference_source_url"],
            },
        },
        "classifier": {
            "run_id": ml["run_id"],
            "comparison_accuracy": test_accuracy["comparison_mean_accuracy"],
            "exposed_accuracy": test_accuracy["exposed_mean_accuracy"],
            "delta_points": test_accuracy["mean_delta_accuracy_pp"],
            "delta_range_points": [
                test_accuracy["min_delta_accuracy_pp"],
                test_accuracy["max_delta_accuracy_pp"],
            ],
            "direct_delta_points": ml["slices"]["directly_exposed"][
                "mean_delta_accuracy_pp"
            ],
            "direct_rows": ml["slices"]["directly_exposed"]["test_rows"],
            "test_rows": test_accuracy["test_rows"],
            "rates_by_seed": rates,
        },
        "profiling": {
            "esc50_reduction_percent": timings["stage2"][
                "warm_median_reduction_percent"
            ],
            "cross_dataset_reduction_percent": timings["stage4"][
                "warm_median_reduction_percent"
            ],
            "full_audit_equivalence": summaries["profiling"]["full_stage4_equivalence"][
                "equal_complete_match_results"
            ],
        },
    }


def plot_classifier(model: dict, out: Path) -> None:
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
            "".join(line.rstrip() + "\n" for line in lines), encoding="utf-8"
        )
        figure.savefig(out / "leakage-accuracy.png")


def run_walkthrough(out: Path) -> dict:
    commands = {}

    def cli(name: str, *args: str, expected_code: int = 0) -> str:
        run = subprocess.run(
            [sys.executable, "-m", "echo", *args],
            cwd=out,
            capture_output=True,
            text=True,
            check=False,
        )
        if run.returncode != expected_code:
            raise ValueError(
                f"{name}: expected exit {expected_code}, got {run.returncode}: {run.stderr.strip()}"
            )
        commands[name] = {
            "args": list(args),
            "stdout": run.stdout.strip(),
            "stderr": run.stderr.strip(),
            "exit_code": run.returncode,
        }
        return run.stdout

    cli("fixture", "fixture", "--out", "generated")
    train, test = out / "train", out / "test"
    train.mkdir()
    test.mkdir()
    copyfile(out / "generated/reference.wav", train / "reference.wav")
    copyfile(out / "generated/query.wav", test / "renamed-crop.wav")
    # A second sweep in the same band, synthesized independently.
    t = np.arange(CROP_SAMPLES) / SAMPLE_RATE
    sweep = 0.30 * np.sin(2 * np.pi * (371 * t + 93 * t**2))
    sf.write(test / "similar-control.wav", sweep, SAMPLE_RATE, subtype="PCM_16")
    sf.write(
        test / "silence.wav", np.zeros(CROP_SAMPLES), SAMPLE_RATE, subtype="PCM_16"
    )

    cli(
        "reference_manifest",
        "data",
        "manifest",
        "train",
        "--dataset",
        "train",
        "--role",
        "reference",
        "--out",
        "train.csv",
    )
    cli(
        "query_manifest",
        "data",
        "manifest",
        "test",
        "--dataset",
        "test",
        "--role",
        "query",
        "--out",
        "test.csv",
    )
    cli("index", "index", "train.csv", "--root", "train", "--out", "reference.sqlite")
    cli("match_text", "match", "test/renamed-crop.wav", "--index", "reference.sqlite")
    cli(
        "control_text",
        "match",
        "test/similar-control.wav",
        "--index",
        "reference.sqlite",
    )
    match = json.loads(
        cli(
            "match",
            "match",
            "test/renamed-crop.wav",
            "--index",
            "reference.sqlite",
            "--json",
        )
    )
    control = json.loads(
        cli(
            "control",
            "match",
            "test/similar-control.wav",
            "--index",
            "reference.sqlite",
            "--json",
        )
    )
    batch = json.loads(
        cli(
            "audit",
            "audit",
            "test.csv",
            "--root",
            "test",
            "--index",
            "reference.sqlite",
            "--out",
            "audit",
        )
    )
    cli("review", "review", "audit", "--out", "audit/review.html")
    expected = CROP_START / SAMPLE_RATE
    if (
        match["status"] != "matched"
        or match["candidates"][0]["asset_id"] != "train:reference.wav"
        or abs(match["candidates"][0]["offset_seconds"] - expected) > 0.008
        or control["status"] != "no_match"
        or batch["decisions"]
        != {"matched": 1, "no_match": 1, "insufficient_evidence": 1}
    ):
        raise ValueError(
            "walkthrough did not reproduce the declared match, control, and silence cases"
        )
    return {
        "commands": commands,
        "expected_offset_seconds": expected,
        "match": match,
        "control": control,
        "batch": batch,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        with new_output_directory(args.out):
            result = evidence()
            result["walkthrough"] = run_walkthrough(args.out.resolve())
            plot_classifier(result["classifier"], args.out.resolve())
            write_json(args.out / "evidence.json", result)
    except (KeyError, OSError, ValueError) as error:
        print(f"echo walkthrough: {error}", file=sys.stderr)
        return 1
    print(
        f"Generated and verified the walkthrough, offline audit, and chart in {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
