"""Measure Echo's build and query phases on frozen manifests."""

import argparse
import hashlib
import json
import platform
import sqlite3
import sys
from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter_ns

import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.audio import load_audio
from echo.datasets import read_manifest
from echo.evaluation import run_info
from echo.fingerprint import pair_peaks, read_config, spectral_peaks
from echo.index import build_index, open_index
from echo.matcher import (
    DEFAULT_LIMIT,
    DEFAULT_POLICY,
    align_tracks,
    decide,
    rank_postings,
    read_policy,
    resolve_alignment_engine,
)

PHASES = (
    "decode_ns",
    "spectral_peaks_ns",
    "pair_hashes_ns",
    "retrieve_ns",
    "vote_rank_decide_ns",
)
QUERY_COLUMNS = (
    "condition",
    "repeat",
    "query_id",
    "role",
    "status",
    "result_sha256",
    "landmarks",
    "postings_returned",
    "candidate_count",
    "open_ns",
    *PHASES,
    "match_ns",
    "total_ns",
)
BUILD_COLUMNS = (
    "repeat",
    "build_ns",
    "indexed_assets",
    "postings",
    "bytes",
    "tracks_per_second",
    "postings_per_second",
)


def profile_match(audio_path, index, policy, aligner=align_tracks):
    started = perf_counter_ns()
    audio = load_audio(audio_path, target_rate=index.config.sample_rate)
    decoded = perf_counter_ns()
    peaks = spectral_peaks(audio.samples, index.config)
    extracted = perf_counter_ns()
    query = sorted(set(pair_peaks(peaks, index.config)))
    features = perf_counter_ns()
    postings = (
        index.lookup({point.key for point in query}, policy.max_postings_per_hash)
        if query
        else {}
    )
    retrieved = perf_counter_ns()
    ranked = rank_postings(
        query,
        len(audio.samples),
        index,
        postings,
        radius=policy.offset_radius_frames,
        limit=DEFAULT_LIMIT,
        aligner=aligner,
    )
    result = decide(ranked, policy)
    ended = perf_counter_ns()
    return result, {
        "decode_ns": decoded - started,
        "spectral_peaks_ns": extracted - decoded,
        "pair_hashes_ns": features - extracted,
        "retrieve_ns": retrieved - features,
        "vote_rank_decide_ns": ended - retrieved,
        "match_ns": ended - started,
        "landmarks": result.query_landmarks,
        "postings_returned": sum(map(len, postings.values())),
        "candidate_count": len(result.candidates),
    }


def result_digest(result) -> str:
    payload = json.dumps(asdict(result), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def query_row(asset, path, index, policy, aligner, condition, repeat, opened=0):
    result, timing = profile_match(path, index, policy, aligner)
    return {
        "query_id": asset.asset_id,
        "role": asset.role,
        "condition": condition,
        "repeat": repeat,
        "status": result.status,
        "result_sha256": result_digest(result),
        "open_ns": opened,
        "total_ns": opened + timing["match_ns"],
        **timing,
    }


def latency(rows, column):
    times = [row[column] / 1_000_000 for row in rows]
    return {
        "p50_ms": median(times),
        "p95_ms": quantiles(times, n=100, method="inclusive")[94]
        if len(times) > 1
        else times[0],
    }


def query_summary(rows):
    result = {}
    for condition in dict.fromkeys(row["condition"] for row in rows):
        selected = [row for row in rows if row["condition"] == condition]
        total_match = sum(row["match_ns"] for row in selected)
        result[condition] = {
            "observations": len(selected),
            "statuses_per_observation": dict(
                Counter(row["status"] for row in selected)
            ),
            "latency": {
                column: latency(selected, column)
                for column in ("total_ns", "match_ns", "open_ns", *PHASES)
            },
            "percent_of_measured_match_time": {
                column: 100 * sum(row[column] for row in selected) / total_match
                for column in PHASES
            },
        }
    return result


def environment():
    return {
        **run_info(),
        "system": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "numpy": version("numpy"),
        "scipy": version("scipy"),
        "soundfile": version("soundfile"),
        "libsndfile": sf.__libsndfile_version__,
        "peak_rss_scope": "whole fresh Python process, OS high-water mark",
    }


def run_query(args):
    policy = read_policy(args.policy) if args.policy else DEFAULT_POLICY
    aligner = resolve_alignment_engine(args.engine)
    manifest_sha = sha256_file(args.manifest)
    planned = []
    for asset in read_manifest(args.manifest):
        path = asset.local_path(args.root)
        if not asset.sha256 or sha256_file(path) != asset.sha256:
            raise ValueError(f"{asset.asset_id}: query checksum missing or changed")
        planned.append((asset, path))
    if not planned:
        raise ValueError("the benchmark requires at least one query")
    if sha256_file(args.manifest) != manifest_sha:
        raise ValueError("query manifest changed while it was read")

    with new_output_directory(args.out):
        rows = []
        with open_index(args.index) as index:
            index_info = {
                "manifest_sha256": index.manifest_sha256,
                "fingerprint_config_sha256": index.config.digest,
                "indexed_assets": len(index.tracks),
                "postings": sum(track.landmarks for track in index.tracks.values()),
                "bytes": args.index.stat().st_size,
            }
        # Run fresh connections first. A process cannot flush the filesystem cache portably.
        for repeat in range(1, args.fresh + 1):
            for asset, path in planned:
                opened = perf_counter_ns()
                with open_index(args.index) as index:
                    rows.append(
                        query_row(
                            asset,
                            path,
                            index,
                            policy,
                            aligner,
                            "fresh_connection",
                            repeat,
                            perf_counter_ns() - opened,
                        )
                    )
        if args.warm:
            with open_index(args.index) as index:
                for _, path in planned:
                    profile_match(path, index, policy, aligner)
                for repeat in range(1, args.warm + 1):
                    rows.extend(
                        query_row(
                            asset,
                            path,
                            index,
                            policy,
                            aligner,
                            "warm_connection",
                            repeat,
                        )
                        for asset, path in planned
                    )
        digests = {}
        for row in rows:
            key, value = row["query_id"], row["result_sha256"]
            if digests.setdefault(key, value) != value:
                raise ValueError(f"{key}: ranked result changed across repetitions")
        samples = args.out / "queries.csv"
        write_csv(samples, QUERY_COLUMNS, rows)
        report = {
            "schema_version": 1,
            "workload": args.workload,
            "engine": args.engine,
            "native_binary_sha256": sha256_file(
                Path(sys.modules["_echo_offsets"].__file__)
            )
            if args.engine == "rust"
            else None,
            "environment": environment(),
            "input_query_manifest_sha256": manifest_sha,
            "match_policy_sha256": policy.digest,
            "index": {**index_info, "sha256": sha256_file(args.index)},
            "query_count": len(planned),
            "repetitions": {
                "fresh": args.fresh,
                "warm": args.warm,
                "warmup": int(bool(args.warm)),
            },
            "timing_boundary": {
                "match": "decode, fingerprints, lookup, vote, rank and decision; excludes checksums and output",
                "fresh": "fresh SQLite connection per query; total includes open and schema/track read",
                "warm": "one connection after one full warmup pass; excludes opening",
                "filesystem_cache": "uncontrolled; query WAVs were checksummed before timing",
            },
            "queries_sha256": sha256_file(samples),
            "measurements": query_summary(rows),
        }
        write_json(args.out / "summary.json", report)
    return report


def run_build(args):
    config = read_config(args.config)
    rows = []
    with new_output_directory(args.out):
        for repeat in range(1, args.repetitions + 1):
            target = args.out / f"index-{repeat}.sqlite"
            started = perf_counter_ns()
            detail = build_index(args.manifest, args.root, target, config)
            elapsed = perf_counter_ns() - started
            rows.append(
                {
                    "repeat": repeat,
                    "build_ns": elapsed,
                    "indexed_assets": detail["indexed_assets"],
                    "postings": detail["postings"],
                    "bytes": detail["bytes"],
                    "tracks_per_second": detail["indexed_assets"] * 1e9 / elapsed,
                    "postings_per_second": detail["postings"] * 1e9 / elapsed,
                }
            )
            print(f"Build {repeat}: {elapsed / 1e9:.2f}s", file=sys.stderr, flush=True)
        if (
            len(
                {(row["indexed_assets"], row["postings"], row["bytes"]) for row in rows}
            )
            != 1
        ):
            raise ValueError("indexed corpus changed across build repetitions")
        samples = args.out / "builds.csv"
        write_csv(samples, BUILD_COLUMNS, rows)
        report = {
            "schema_version": 1,
            "workload": args.workload,
            "environment": environment(),
            "index": detail,
            "repetitions": args.repetitions,
            "latency": latency(rows, "build_ns"),
            "median_tracks_per_second": median(
                row["tracks_per_second"] for row in rows
            ),
            "median_postings_per_second": median(
                row["postings_per_second"] for row in rows
            ),
            "builds_sha256": sha256_file(samples),
            "timing_boundary": "fresh database path per build; hashes and decode through SQLite publication; uncontrolled OS cache",
        }
        write_json(args.out / "summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in ("query", "build"):
        child = modes.add_parser(name)
        for argument in ("--manifest", "--root", "--out"):
            child.add_argument(argument, type=Path, required=True)
        child.add_argument("--workload", required=True)
        if name == "query":
            child.add_argument("--index", type=Path, required=True)
            child.add_argument("--policy", type=Path)
            child.add_argument("--engine", choices=("python", "rust"), default="python")
            child.add_argument("--warm", type=int, default=3)
            child.add_argument("--fresh", type=int, default=1)
        else:
            child.add_argument("--config", type=Path)
            child.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    try:
        if args.mode == "query":
            if min(args.fresh, args.warm) < 0 or args.fresh + args.warm == 0:
                raise ValueError(
                    "query passes must be nonnegative with at least one timed pass"
                )
            report = run_query(args)
            print(
                json.dumps(
                    {
                        key: value["latency"]["total_ns"]
                        for key, value in report["measurements"].items()
                    }
                )
            )
        else:
            if args.repetitions < 1:
                raise ValueError("build repetitions must be positive")
            print(json.dumps(run_build(args)["latency"]))
    except (ValueError, OSError, sqlite3.DatabaseError) as error:
        print(f"echo stage 6: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
