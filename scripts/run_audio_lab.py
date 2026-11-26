"""Run Echo on the public listening pack and export a trace for the browser."""

import argparse
import csv
import json
import platform
import subprocess
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from run_stage6 import PHASES, latency, profile_match

from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.audio import load_audio
from echo.datasets import Asset, read_manifest, write_manifest
from echo.evidence import identity_digest, require
from echo.fingerprint import FIELD_BITS, FIELD_LIMIT, FingerprintConfig, spectral_peaks
from echo.index import build_index, open_index
from echo.matcher import (
    align_tracks,
    best_offset,
    read_policy,
    resolve_alignment_engine,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / "examples/audio-audit"
POLICY = ROOT / "docs/results/stage-3-policy.json"


def data_script(path, variable, payload):
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    path.write_bytes(f"globalThis.{variable} = {data};\n".encode())


def plot_peaks(path, config):
    audio = load_audio(path, target_rate=config.sample_rate)
    points = spectral_peaks(audio.samples, config)
    stride = max(1, len(points) // 1000 + 1)
    return {
        "samples": len(audio.samples),
        "count": len(points),
        "displayed": points[::stride],
    }


def trace_top(top, recorded, radius):
    query, postings = recorded
    bands = defaultdict(set)
    occurrences = defaultdict(dict)
    entries = 0
    for number, point in enumerate(query):
        for asset, frame in postings.get(point.key, ()):
            entries += 1
            if asset == top.asset_id:
                offset = frame - point.frame
                bands[offset].add(number)
                occurrences[offset][number] = frame
    offset, voters = best_offset(bands, radius)
    require(
        offset == top.offset_frames and len(voters) == top.score,
        "illustrated votes disagree with the production matcher",
    )
    samples = []
    ordered = sorted(bands[offset], key=lambda number: (query[number].frame, number))
    if ordered:
        for number in ordered[:: max(1, (len(ordered) + 2) // 3)][:3]:
            point = query[number]
            key = point.key
            mask = FIELD_LIMIT - 1
            samples.append(
                {
                    "query_frame": point.frame,
                    "reference_frame": occurrences[offset][number],
                    "anchor_bin": key >> (2 * FIELD_BITS),
                    "target_bin": (key >> FIELD_BITS) & mask,
                    "delay_bin": key & mask,
                    "key": key,
                }
            )
    return {
        "exact_offset_bins": [[n, len(bands[n])] for n in sorted(bands)],
        "example_votes": samples,
        "sql_postings_matched_to_query": entries,
        "exact_winning_bin": len(bands[offset]),
        "window_deduplicated_votes": len(voters),
    }


def capture_case(query_def, path, index, policy):
    used = None

    def capture(query, postings, radius):
        nonlocal used
        used = (query, postings)
        return align_tracks(query, postings, radius)

    result, details = profile_match(path, index, policy, capture)
    trace = (
        trace_top(result.candidates[0], used, policy.offset_radius_frames)
        if result.candidates
        else None
    )
    return {
        **query_def,
        "match": asdict(result),
        "trace": trace,
        "lookup": {
            "landmarks": details["landmarks"],
            "postings_returned": details["postings_returned"],
        },
        "peaks": plot_peaks(path, index.config),
    }


def measure(index, queries, policy, repeats, engines, expected):
    aligners = {name: resolve_alignment_engine(name) for name in engines}
    for aligner in aligners.values():
        for path in queries.values():
            profile_match(path, index, policy, aligner)
    rows = []
    for repeat in range(repeats):
        order = engines if repeat % 2 == 0 else engines[::-1]
        for name in order:
            for query_id, path in queries.items():
                result, timing = profile_match(path, index, policy, aligners[name])
                require(
                    asdict(result) == expected[query_id],
                    f"{name} changed the saved result for {query_id}",
                )
                rows.append(
                    {"query": query_id, "engine": name, "repeat": repeat, **timing}
                )
    processor = platform.machine()
    if platform.system() == "Darwin":
        processor = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
    return rows, {
        "processor": processor,
        "system": platform.platform(),
        "python": platform.python_version(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "repeats": repeats,
        "timing_boundary": (
            "WAV or MP3 decode, spectral peaks, fingerprint hashes, SQLite retrieval, "
            "voting and decision over one reused connection. One warmup pass per "
            "engine. Index build, process startup, file digests and trace export excluded."
        ),
        "engines": summarize_timings(rows, engines),
    }


def summarize_timings(rows, engines):
    selected = {
        name: [row for row in rows if row["engine"] == name] for name in engines
    }
    return {
        name: {
            "observations": len(samples),
            "query": latency(samples, "match_ns"),
            "phases": {phase: latency(samples, phase) for phase in PHASES},
        }
        for name, samples in selected.items()
    }


def check_timings(args, expected):
    with (args.pack / "timings.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    saved = json.loads((args.pack / "performance.json").read_text(encoding="utf-8"))
    engines = saved["engines"]
    identifiers = {(row["engine"], int(row["repeat"]), row["query"]) for row in rows}
    require(
        len(rows) == len(identifiers)
        and identifiers
        == {
            (name, repeat, query)
            for name in engines
            for repeat in range(saved["repeats"])
            for query in expected
        },
        "Timing rows do not cover every engine, query and repeat",
    )
    for row in rows:
        for key in (*PHASES, "match_ns"):
            row[key] = int(row[key])
    require(
        summarize_timings(rows, engines) == engines,
        "Published timing summaries disagree with their raw measurements",
    )
    data_script(args.out / "performance-check.js", "ECHO_LAB_PERF", saved)
    require(
        (args.out / "performance-check.js").read_bytes()
        == (args.pack / "performance.js").read_bytes(),
        "Browser timings drifted from the published summary",
    )


def run(args):
    data = json.loads((args.pack / "dataset.json").read_text(encoding="utf-8"))
    require(data["schema_version"] == 1, "Unsupported listening pack schema")
    inputs, config, policy = data["audio"], FingerprintConfig(), read_policy(POLICY)
    for asset in inputs.values():
        require(
            sha256_file(args.pack / asset["path"]) == asset["sha256"],
            f"{asset['path']}: checksums disagree with the listening pack",
        )
    with new_output_directory(args.out):
        references = args.out / "references.csv"
        write_manifest(
            references,
            [
                Asset(
                    name,
                    "fsd50k-eval",
                    "10.5281/zenodo.4060432",
                    inputs[name]["path"],
                    "reference",
                    sha256=inputs[name]["sha256"],
                )
                for name in data["references"]
            ],
        )
        path = args.out / "index.sqlite"
        build_index(references, args.pack, path, config)
        reference_assets = read_manifest(references)
        queries = {
            item["id"]: args.pack / inputs[item["id"]]["path"]
            for item in data["queries"]
        }
        reference_hashes = {item.sha256 for item in reference_assets}
        with open_index(path, config) as index:
            cases = []
            for item in data["queries"]:
                case = capture_case(item, queries[item["id"]], index, policy)
                case["byte_equal_reference"] = (
                    inputs[item["id"]]["sha256"] in reference_hashes
                )
                cases.append(case)
            expected = {case["id"]: case["match"] for case in cases}
            if args.repeats:
                rows, perf = measure(
                    index, queries, policy, args.repeats, args.engines, expected
                )
                write_csv(args.out / "timings.csv", rows[0], rows)
                write_json(args.out / "performance.json", perf)
                data_script(args.out / "performance.js", "ECHO_LAB_PERF", perf)
            counts = {
                "references": len(index.tracks),
                "indexed_landmarks": sum(
                    track.landmarks for track in index.tracks.values()
                ),
                "queries": len(cases),
                "known_overlaps": sum(case["expected"] is not None for case in cases),
                "byte_hash_hits": sum(case["byte_equal_reference"] for case in cases),
                "accepted_known_overlaps": sum(
                    case["expected"] is not None
                    and case["match"]["status"] == "matched"
                    and case["match"]["candidates"][0]["asset_id"] == case["expected"]
                    for case in cases
                ),
                "absent_source_queries": sum(
                    case["expected"] is None for case in cases
                ),
                "accepted_absent_sources": sum(
                    case["expected"] is None and case["match"]["status"] == "matched"
                    for case in cases
                ),
            }
            payload = {
                "schema_version": 1,
                "id": identity_digest(
                    {
                        "dataset": data,
                        "config": asdict(config),
                        "policy": asdict(policy),
                    }
                ),
                "policy": asdict(policy),
                "config": asdict(config),
                "audio": inputs,
                "cases": cases,
                "references": {
                    name: plot_peaks(args.pack / inputs[name]["path"], config)
                    for name in data["references"]
                },
                "counts": counts,
            }
        write_json(args.out / "evidence.json", payload)
        data_script(args.out / "evidence.js", "ECHO_LAB", payload)
        if args.check:
            require(
                (args.out / "evidence.js").read_bytes()
                == (args.pack / "evidence.js").read_bytes(),
                "Listening example drifted from the production matcher",
            )
            check_timings(args, expected)
        print(json.dumps(counts, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repeats", type=int, default=0)
    parser.add_argument(
        "--engines", nargs="+", choices=("python", "rust"), default=["python"]
    )
    args = parser.parse_args()
    if args.repeats < 0 or len(set(args.engines)) != len(args.engines):
        parser.error("repeats must be nonnegative and engines must be unique")
    try:
        run(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"audio example: {error}\n")


if __name__ == "__main__":
    main()
