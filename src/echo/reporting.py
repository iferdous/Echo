"""Generate, check, and export Echo reports from already measured evidence."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from echo.artifacts import new_output_directory, new_output_file
from echo.evidence import (
    Evidence,
    json_bytes,
    published_evidence,
    require,
    sha256,
    unpack_bundle,
)
from echo.evidence_metrics import aggregate
from echo.plots import plot_classifier, plot_timing

START = "<!-- echo-evidence:start -->"
END = "<!-- echo-evidence:end -->"
GENERATED = {
    "REPORT.md": "docs/results/stage-8.md",
    "metrics.json": "docs/results/stage-8-metrics.json",
    "model-accuracy.svg": "docs/demo/leakage-accuracy.svg",
    "timing.svg": "docs/results/stage-8-timing.svg",
}
BUNDLE = "docs/results/echo-evidence.zip"
REFS = "https://github.com/iferdous/Echo/blob/main"


def table(columns, rows) -> str:
    return "\n".join(
        "| " + " | ".join(map(str, values)) + " |"
        for values in (columns, ["---"] * len(columns), *rows)
    )


def pct(value: float) -> str:
    return f"{value:.1%}"


def points(value: float) -> str:
    return f"{value:+.2f}"


def headline(metrics: dict) -> str:
    m = metrics["matcher"]["test"]
    match = m["match"]
    audit = metrics["audit"]
    model = metrics["classifier"]
    overall = model["slices"]["all"]
    cross = metrics["timing"]["stage4"]
    return table(
        ("Measured result", "Scope", "Run"),
        [
            (
                f"**{match['correct_accepts']} of {match['positives']}** matching trials accepted correctly",
                f"Held-out trials across {m['source_groups']['positive_source_groups']} positive recordings. {match['false_accepts']} of {match['absent']} absent-source trials were accepted on this benchmark.",
                "[Stage 3](docs/results/stage-3.md)",
            ),
            (
                f"**{audit['outcomes']['confirmed_audio_matched']['query_rows']} of {audit['known_source_confirmed']}** confirmed pairs found at the supported offset",
                f"Independent waveform checks within the {audit['queries']}-query ESC-50/FSD50K eval audit.",
                "[Stage 4](docs/results/stage-4.md)",
            ),
            (
                f"**{points(overall['mean_delta_accuracy_pp'])} percentage points** from deliberate training exposure",
                f"Mean accuracy rose from {pct(overall['comparison_mean_accuracy'])} to {pct(overall['exposed_mean_accuracy'])} on the same {overall['test_rows']} test files across {len(model['seeds'])} paired runs.",
                "[Stage 5](docs/results/stage-5.md)",
            ),
            (
                f"**{cross['warm_median_reduction_percent']:.0f}% less** warm median query time",
                "Rust voting versus tuned Python on the measured ESC-50/FSD50K sample on Apple M3.",
                "[Stage 6](docs/results/stage-6.md)",
            ),
        ],
    )


def replace_headline(text: str, metrics: dict) -> str:
    require(
        text.count(START) == text.count(END) == 1,
        "README needs exactly one Echo evidence block",
    )
    before, rest = text.split(START)
    _, after = rest.split(END)
    return f"{before}{START}\n{headline(metrics)}\n{END}{after}"


def fixture_report(metrics: dict) -> str:
    smoke = metrics["fixture"]
    return (
        "\n\n".join(
            (
                "# Echo fixture benchmark",
                f"Run `{metrics['run_id']}` · Audit `{smoke['audit_run_id']}`.",
                "Generated fixture. The cutoff checks clip alignment and expected behavior on this fixture.",
                f"The known crop starts at **+{smoke['expected_offset_seconds']:.3f} s** in the reference.",
                table(
                    ("Query", "Decision", "Top reference", "Offset"),
                    [
                        (
                            row["query_id"],
                            row["decision"],
                            row["best_reference"] or "—",
                            f"{float(row['offset_seconds']):+.3f} s"
                            if row["offset_seconds"]
                            else "—",
                        )
                        for row in smoke["queries"]
                    ],
                ),
            )
        )
        + "\n"
    )


def matcher_tables(metrics: dict) -> list[str]:
    matcher = metrics["matcher"]
    test = matcher["test"]
    group = test["source_groups"]
    low, high = group["positive_group_bootstrap_95"]
    upper = group["absent_group_wilson_95"][1]
    tests = []
    for name, row in (*test["variants"].items(), ("All", test["match"])):
        tests.append(
            (
                name,
                f"{row['top_1']}/{row['positives']}",
                f"{row['top_5']}/{row['positives']}",
                f"{row['correct_accepts']}/{row['positives']}",
                f"{row['false_accepts']}/{row['absent']}",
            )
        )
    comparisons = [
        (
            title,
            f"{row['correct_top_1']}/{row['positive_queries']}",
            row["available"],
            row["unavailable"],
        )
        for title, row in test["baselines"].items()
    ]
    cal = matcher["calibration"]["match"]
    return [
        "## Held-out matcher benchmark",
        f"Canonical run `{matcher['name']}` · Test summary SHA-256 `{matcher['summary_sha256']}`.",
        f"Calibration accepted {cal['correct_accepts']}/{cal['positives']} positives and {cal['false_accepts']}/{cal['absent']} absent-source trials. The table below uses the separate held-out split.",
        table(
            (
                "Variant",
                "Correct top 1",
                "Correct top 5",
                "Correct accepted",
                "Accepted absent-source",
            ),
            tests,
        ),
        f"The bootstrap interval across {group['positive_source_groups']} matching source groups was {pct(low)} to {pct(high)}. The absent-source trials came from {group['absent_source_groups']} recordings. The Wilson 95% upper bound for a recording having any accepted trial was {pct(upper)}.",
        table(
            ("Baseline", "Correct top 1", "Available trials", "Unavailable trials"),
            comparisons,
        ),
        table(
            ("Source ID visibility", "Correct accepted", "Accepted absent-source"),
            [
                (
                    name,
                    f"{row['correct_accepts']}/{row['positives']}",
                    f"{row['false_accepts']}/{row['absent']}",
                )
                for name, row in test["id_visibility"].items()
            ],
        ),
    ]


def audit_tables(metrics: dict) -> list[str]:
    audit = metrics["audit"]
    labels = {
        "confirmed_audio_matched": "Confirmed, accepted at supported offset",
        "confirmed_audio_matcher_miss": "Confirmed, matcher abstained",
        "confirmed_audio_offset_disagreement": "Confirmed, offset differed",
        "control_accepted_audio_unresolved": "Control accepted, audio unresolved",
        "control_not_accepted": "Control declined",
        "same_source_audio_unresolved": "Known source, overlap unresolved",
    }
    return [
        "## Cross-dataset audit",
        f"Run `{audit['run_id']}` scanned {audit['queries']} ESC-50 clips against {audit['references']} official FSD50K eval recordings. Waveform review covered {audit['reviewed_pairs']} pairs and independently confirmed {audit['known_source_confirmed']} of {audit['eligible_known_source_pairs']} eligible known-source pairs.",
        table(("Query cohort", "Clips"), list(audit["queried_by_cohort"].items())),
        table(
            ("Indexed reference cohort", "Clips"),
            list(audit["indexed_references_by_cohort"].items()),
        ),
        table(
            ("Outcome", "Query rows", "Distinct query sources"),
            [
                (
                    labels.get(name, name),
                    counts["query_rows"],
                    counts["unique_query_sources"],
                )
                for name, counts in audit["outcomes"].items()
            ],
        ),
        "Distinct sources can appear in more than one outcome. An unresolved control is a candidate for review. These counts represent the selected audit cohort.",
    ]


def classifier_tables(metrics: dict) -> list[str]:
    model = metrics["classifier"]
    rows = []
    for name, slice_ in model["slices"].items():
        low, high = slice_["paired_test_source_bootstrap"][
            "percentile_95_interval_accuracy_pp"
        ]
        rows.append(
            (
                name.replace("_", " "),
                slice_["test_rows"],
                pct(slice_["comparison_mean_accuracy"]),
                pct(slice_["exposed_mean_accuracy"]),
                points(slice_["mean_delta_accuracy_pp"]),
                f"{points(low)} to {points(high)}",
                f"{slice_['comparison_mean_macro_f1']:.3f} / {slice_['exposed_mean_macro_f1']:.3f}",
            )
        )
    seeds = [
        (
            seed["seed"],
            seed["all"]["comparison"]["correct"],
            seed["all"]["exposed"]["correct"],
            points(seed["all"]["delta_accuracy_pp"]),
            points(seed["directly_exposed"]["delta_accuracy_pp"]),
            points(seed["unexposed"]["delta_accuracy_pp"]),
        )
        for seed in model["seeds"]
    ]
    split = model["split_validation"]
    overall = model["slices"]["all"]
    return [
        "## Controlled leakage experiment",
        f"Run `{model['run_id']}` used {split['training_rows_per_arm']:,} examples per arm and the same ordered test clips. The comparison arm shared zero recording groups with the test set. The exposed arm shared {len(split['confirmation']['intentional_exposure_groups'])} declared groups.",
        table(
            (
                "Slice",
                "Clips",
                "Comparison",
                "Exposed",
                "Δ points",
                "Source bootstrap 95% interval",
                "Macro F1 comparison / exposed",
            ),
            rows,
        ),
        table(
            (
                "Seed",
                "Comparison correct",
                "Exposed correct",
                "All Δ points",
                "Direct Δ points",
                "Unexposed Δ points",
            ),
            seeds,
        ),
        f"Across-seed sample SD on the full test was {overall['sample_sd_delta_accuracy_pp']:.2f} points. The bootstrap interval resamples test sources conditional on the trained models.",
    ]


def timing_tables(metrics: dict) -> list[str]:
    rows = []
    phases = []
    builds = []
    for note in metrics["timing"].values():
        for engine, record in note["engines"].items():
            warm = record["warm_connection"]
            fresh = record["fresh_connection"]
            phase = record["warm_phase_medians_ms"]
            phases.append(
                (
                    note["workload"],
                    engine,
                    *(
                        f"{phase[name]:.1f}"
                        for name in (
                            "decode_ns",
                            "spectral_peaks_ns",
                            "pair_hashes_ns",
                            "retrieve_ns",
                            "vote_rank_decide_ns",
                        )
                    ),
                )
            )
            rows.append(
                (
                    note["workload"],
                    engine,
                    warm["count"],
                    f"{warm['p50_ms']:.1f}",
                    f"{warm['p95_ms']:.1f}",
                    fresh["count"],
                    f"{fresh['p50_ms']:.1f}",
                    f"{fresh['p95_ms']:.1f}",
                    f"{record['peak_rss_bytes'] / 2**20:.1f}",
                )
            )
        build = note["build"]
        builds.append(
            (
                note["workload"],
                build["index"]["indexed_assets"],
                f"{build['index']['bytes'] / 2**20:.1f}",
                f"{build['latency']['p50_ms'] / 1000:.2f}",
                f"{build['median_tracks_per_second']:.2f}",
            )
        )
    return [
        "## Matcher profiling",
        "Apple M3. Warm runs reuse a SQLite connection after a full warmup pass. Fresh runs open a connection per query. The filesystem cache was uncontrolled. The bundle preserves the noisy first ESC-50 timing pair and the repeated comparison used here.",
        table(
            (
                "Workload",
                "Engine",
                "Warm n",
                "Warm median ms",
                "Warm p95 ms",
                "Fresh n",
                "Fresh median ms",
                "Fresh p95 ms",
                "Peak MiB",
            ),
            rows,
        ),
        table(
            ("Workload", "Indexed files", "Index MiB", "Median build s", "Tracks/s"),
            builds,
        ),
        table(
            (
                "Workload",
                "Engine",
                "Decode ms",
                "Peaks ms",
                "Pair ms",
                "SQLite ms",
                "Vote and rank ms",
            ),
            phases,
        ),
    ]


def public_report(
    metrics: dict, chart_name: str, timing_name: str = "timing.svg"
) -> str:
    metadata = metrics["metadata"]
    stages = [
        "# Echo benchmark evidence",
        f"Profile **{metrics['profile']}** · Evidence run `{metrics['run_id']}`.",
        "The tables below regenerate from the saved per-query and per-item evidence. Corpus-specific match rates and performance measurements depend on the recorded workloads.",
        f"![Mean accuracy for the independent and exposed training arms.]({chart_name})",
        "## Corpus metadata and development",
        table(
            (
                "FSD50K partition",
                "FSD50K clips",
                "ESC-50 rows sharing a source ID",
                "Shared IDs",
            ),
            [
                (
                    name,
                    row["fsd50k_rows"],
                    row["shared_esc50_rows"],
                    row["shared_source_ids"],
                )
                for name, row in metadata["partitions"].items()
            ],
        ),
        table(
            (
                "Stage 2 fingerprint floor",
                "Correct top 1",
                "Correct accepted",
                "Accepted absent-source",
            ),
            [
                (
                    name,
                    f"{row['correct_top_one']}/{row['positive_queries']}",
                    f"{row['correct_accepted']}/{row['positive_queries']}",
                    f"{row['absent_source_accepted']}/{row['absent_source_queries']}",
                )
                for name, row in metrics["development"].items()
            ],
        ),
        *matcher_tables(metrics),
        *audit_tables(metrics),
        *classifier_tables(metrics),
        *timing_tables(metrics),
        f"![Warm median query time in Python and Rust by workload.]({timing_name})",
        f"[Reproduction guide]({REFS}/docs/reproduce-evidence.md) · [Engineer workflow]({REFS}/docs/demo/ENGINEER-GUIDE.md)",
    ]
    if replay := metrics.get("local_replay"):
        counts = replay["audio_sha256_verified"]
        stages.insert(
            3,
            f"The local replay verified {counts['esc50']:,} ESC-50 and {counts['fsd50k_eval']:,} FSD50K file digests. "
            f"The {replay['replay_engine']} engine reproduced all {replay['equal_query_rows']} decisions and {replay['equal_candidate_rows']:,} ranked candidates.",
        )
    return "\n\n".join(stages) + "\n"


def charts(metrics: dict, workspace: Path) -> dict[str, bytes]:
    model = metrics["classifier"]
    overall = model["slices"]["all"]
    data = {
        "run_id": model["run_id"],
        "comparison_accuracy": overall["comparison_mean_accuracy"],
        "exposed_accuracy": overall["exposed_mean_accuracy"],
        "delta_points": overall["mean_delta_accuracy_pp"],
        "delta_range_points": [
            overall["min_delta_accuracy_pp"],
            overall["max_delta_accuracy_pp"],
        ],
        "test_rows": overall["test_rows"],
        "rates_by_seed": model["seeds"],
    }
    try:
        plot_classifier(data, workspace, png=False)
        plot_timing(metrics["timing"], workspace)
    except ModuleNotFoundError as error:
        if error.name != "matplotlib":
            raise
        raise ValueError(
            "install the plotting dependency with uv sync --locked --group demo"
        ) from error
    return {
        "model-accuracy.svg": (workspace / "leakage-accuracy.svg").read_bytes(),
        "timing.svg": (workspace / "timing.svg").read_bytes(),
    }


def render(metrics: dict, scratch: Path) -> dict[str, bytes]:
    fixture = metrics["profile"] == "fixture"
    guide = (
        "# Reproduce this evidence\n\n"
        f"Use Echo’s [reproduction guide]({REFS}/docs/reproduce-evidence.md). "
        "The ZIP contains verified text and report figures. "
        "The saved measurements can be rendered from this ZIP with `echo-audit report BUNDLE.zip --out report`.\n"
    )
    outputs = {
        "REPORT.md": (
            fixture_report(metrics)
            if fixture
            else public_report(metrics, "model-accuracy.svg")
        ).encode(),
        "REPRODUCE.md": guide.encode(),
        "metrics.json": json_bytes(metrics),
    }
    if not fixture:
        # Keep the font cache under the output parent, even when rendering directly from a ZIP.
        outputs.update(charts(metrics, scratch))
    return outputs


def report(source: Evidence, output: Path) -> None:
    with new_output_directory(output), TemporaryDirectory(dir=output) as directory:
        for name, data in render(aggregate(source), Path(directory)).items():
            (output / name).write_bytes(data)


def write_bundle(evidence: Evidence, outputs: dict[str, bytes], path: Path) -> None:
    payload = {
        "manifest.json": json_bytes(evidence.manifest),
        **evidence.payload,
        **outputs,
    }
    payload["checksums.json"] = json_bytes(
        {name: sha256(data) for name, data in payload.items()}
    )
    with ZipFile(path, "w") as zip_file:
        for name in sorted(payload):
            info = ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zip_file.writestr(
                info, payload[name], compress_type=ZIP_DEFLATED, compresslevel=9
            )


def bundle(evidence: Evidence, output: Path) -> None:
    with new_output_file(output) as temporary:
        outputs = render(aggregate(evidence), temporary.parent)
        write_bundle(evidence, outputs, temporary)


def publish(repo: Path, *, check: bool, scratch_root: Path) -> str:
    evidence = published_evidence(repo)
    readme = repo / "README.md"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=scratch_root) as directory:
        scratch = Path(directory)
        data = aggregate(evidence)
        outputs = render(data, scratch)
        headline_content = replace_headline(readme.read_text(encoding="utf-8"), data)
        generated = {repo / path: outputs[key] for key, path in GENERATED.items()}
        generated[repo / GENERATED["REPORT.md"]] = public_report(
            data, "../demo/leakage-accuracy.svg", "stage-8-timing.svg"
        ).encode()
        generated[readme] = headline_content.encode()
        if check:
            for path, content in generated.items():
                require(
                    path.is_file() and path.read_bytes() == content,
                    f"{path.relative_to(repo)} has drifted; regenerate with scripts/publish_stage8.py",
                )
            archived, content = unpack_bundle(repo / BUNDLE)
            require(
                archived == evidence and content == outputs,
                "published bundle has drifted; regenerate with scripts/publish_stage8.py",
            )
        else:
            write_bundle(evidence, outputs, scratch / "bundle.zip")
            for i, (path, content) in enumerate(generated.items()):
                staged = scratch / f"output-{i}"
                staged.write_bytes(content)
                os.replace(staged, path)
            os.replace(scratch / "bundle.zip", repo / BUNDLE)
    return evidence.run_id
