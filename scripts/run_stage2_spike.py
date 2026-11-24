"""Run the Stage 1 development corpus through both Stage 2 index backends."""

import argparse
import csv
import platform
import sqlite3
import subprocess
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.datasets import csv_rows
from echo.fingerprint import read_config
from echo.index import MemoryIndex, build_index, fingerprint_manifest, open_index
from echo.matcher import DEFAULT_LIMIT, DEFAULT_POLICY, match_audio

TOLERANCE_SECONDS = 0.050
QUERY_COLUMNS = (
    "query_id",
    "query_path",
    "label",
    "stratum",
    "expected_asset_id",
    "crop_start_sample",
    "source_sample_rate",
    "sha256",
)
RESULT_COLUMNS = (
    "query_id",
    "label",
    "stratum",
    "expected_asset_id",
    "best_asset_id",
    "status",
    "expected_rank_in_top_five",
    "expected_offset_seconds",
    "best_offset_seconds",
    "correct_offset_error_seconds",
    "best_score",
    "best_anchor_frames",
    "best_distinct_hashes",
    "best_coverage",
    "best_support_fraction",
    "sqlite_query_ms",
    "backend_agreement",
    "message",
)


def score_query(row, spike, memory, sqlite):
    asset_id = row["expected_asset_id"]
    expected_offset = None
    result = {
        "query_id": row["query_id"],
        "label": row["label"],
        "stratum": row["stratum"],
        "expected_asset_id": asset_id,
    }

    try:
        if asset_id:
            start_sample = int(row["crop_start_sample"])
            source_rate = int(row["source_sample_rate"])
            if start_sample < 0 or source_rate <= 0:
                raise ValueError("invalid crop offset or sample rate")
            expected_offset = start_sample / source_rate
        result["expected_offset_seconds"] = expected_offset
        path = (spike / row["query_path"]).resolve()
        if (
            not path.is_relative_to(spike.resolve())
            or sha256_file(path) != row["sha256"]
        ):
            raise ValueError("query path or checksum differs from the manifest")
        start = perf_counter()
        from_sqlite = match_audio(path, sqlite, limit=DEFAULT_LIMIT)
        elapsed = (perf_counter() - start) * 1000
        from_memory = match_audio(path, memory, limit=DEFAULT_LIMIT)
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        return {**result, "status": "input_error", "message": str(error)}

    result.update(
        status=from_sqlite.status,
        sqlite_query_ms=round(elapsed, 3),
        backend_agreement=from_sqlite == from_memory,
    )
    if from_sqlite.candidates:
        best = from_sqlite.candidates[0]
        result.update(
            best_asset_id=best.asset_id,
            best_offset_seconds=best.offset_seconds,
            best_score=best.score,
            best_anchor_frames=best.anchor_frames,
            best_distinct_hashes=best.distinct_hashes,
            best_coverage=round(best.coverage, 5),
            best_support_fraction=round(best.support_fraction, 5),
        )
        if asset_id:
            result["expected_rank_in_top_five"] = next(
                (
                    candidate.rank
                    for candidate in from_sqlite.candidates
                    if candidate.asset_id == asset_id
                ),
                None,
            )
            if best.asset_id == asset_id:
                result["correct_offset_error_seconds"] = round(
                    abs(best.offset_seconds - expected_offset), 6
                )
    return result


def summarize(rows):
    positives = [row for row in rows if row["expected_asset_id"]]
    negatives = [row for row in rows if not row["expected_asset_id"]]
    offsets = [
        row["correct_offset_error_seconds"]
        for row in positives
        if "correct_offset_error_seconds" in row
    ]
    times = [row["sqlite_query_ms"] for row in rows if "sqlite_query_ms" in row]
    return {
        "positive_queries": len(positives),
        "correct_top_one": len(offsets),
        "correct_accepted": sum(
            row["status"] == "matched" and "correct_offset_error_seconds" in row
            for row in positives
        ),
        "correct_top_one_within_50ms": sum(
            offset <= TOLERANCE_SECONDS for offset in offsets
        ),
        "max_correct_top_one_offset_error_seconds": max(offsets, default=None),
        "absent_source_queries": len(negatives),
        "absent_source_accepted": sum(row["status"] == "matched" for row in negatives),
        "backend_agreements": sum(row.get("backend_agreement", False) for row in rows),
        "input_errors": sum(row["status"] == "input_error" for row in rows),
        "sqlite_query_median_ms": round(median(times), 3) if times else None,
        "sqlite_query_p95_ms": round(quantiles(times, n=20, method="inclusive")[18], 3)
        if len(times) > 1
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="ESC-50 audio root")
    parser.add_argument("--spike", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config = read_config(args.config)
    index_manifest = args.spike / "index.csv"
    queries = args.spike / "queries.csv"
    repository = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=repository)
    )

    with new_output_directory(args.out):
        database = args.out / "index.sqlite"
        start = perf_counter()
        build = build_index(index_manifest, args.root, database, config)
        build_ms = (perf_counter() - start) * 1000
        memory = MemoryIndex(
            config, fingerprint_manifest(index_manifest, args.root, config)
        )
        with (
            open_index(database, config) as index,
            queries.open(encoding="utf-8", newline="") as file,
        ):
            if index.tracks != memory.tracks:
                raise RuntimeError("SQLite and memory disagree on the indexed tracks")
            rows = [
                score_query(row, args.spike, memory, index)
                for row in csv_rows(file, QUERY_COLUMNS, name=str(queries))
            ]

        with (args.out / "queries.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, RESULT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        summary = {
            "schema_version": 1,
            "scope": "Stage 2 ESC-50 development spike",
            "source_commit": commit,
            "tracked_or_untracked_changes_at_start": dirty,
            "environment": {
                "machine": platform.machine(),
                "system": platform.platform(),
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "numpy": version("numpy"),
                "scipy": version("scipy"),
                "soundfile": version("soundfile"),
            },
            "input_queries_sha256": sha256_file(queries),
            "result_queries_sha256": sha256_file(args.out / "queries.csv"),
            "fingerprint_config": asdict(config),
            "match_policy": asdict(DEFAULT_POLICY),
            "index": {**build, "sqlite_build_ms": round(build_ms, 3)},
            "timing_boundary": "build includes decode, SHA-256, features and publication. "
            "Each SQLite query includes decode, fingerprinting, lookup and ranking on one open connection.",
            "results": summarize(rows),
        }
        write_json(args.out / "summary.json", summary)
    print(summary["results"])
    return int(summary["results"]["backend_agreements"] != len(rows))


if __name__ == "__main__":
    raise SystemExit(main())
