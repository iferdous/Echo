"""Command-line entry point for Echo."""

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from zipfile import BadZipFile

from echo.acquisition import fetch_stage_one, verify_digest
from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.audio import load_audio
from echo.batch import scan_manifest, write_batch
from echo.datasets import (
    ESC50_METADATA_SHA256,
    ESC50_REVISION,
    FSD50K_GROUND_TRUTH_SHA256,
    FSD50K_REVISION,
    inventory_esc50,
    load_esc50_metadata,
    overlap_report,
    read_fsd50k_partitions,
    read_manifest,
)
from echo.fingerprint import read_config
from echo.fixtures import write_fixture
from echo.index import build_index, open_index
from echo.matcher import (
    DEFAULT_LIMIT,
    DEFAULT_POLICY,
    MATCH_SCHEMA_VERSION,
    match_audio,
    read_policy,
    resolve_alignment_engine,
)
from echo.spike import DEFAULT_INDEX_SIZE, DEFAULT_SEED, write_spike


def run_fixture(args: argparse.Namespace) -> int:
    write_fixture(args.out)
    print(f"Wrote audio fixture to {args.out}")
    return 0


def run_audio(args: argparse.Namespace) -> int:
    audio = load_audio(args.path, target_rate=args.target_rate)
    print(
        f"{audio.source_frames} source frames at {audio.source_rate} Hz "
        f"({audio.source_channels} channels, {audio.source_format}/{audio.source_subtype}). "
        f"{len(audio.samples)} output frames at {audio.sample_rate} Hz (mono float32)"
    )
    return 0


def run_fetch(args: argparse.Namespace) -> int:
    esc50, fsd50k = fetch_stage_one(args.root)
    print(f"ESC-50: {esc50}\nFSD50K ground truth: {fsd50k}")
    return 0


def run_inventory(args: argparse.Namespace) -> int:
    report = inventory_esc50(
        args.esc50, load_esc50_metadata(args.esc50 / "meta/esc50.csv"), args.out
    )
    print(
        f"Decoded {report['decoded_assets']}/{report['expected_assets']} ESC-50 files. "
        f"Report: {args.out / 'inventory.json'}"
    )
    return int(bool(report["rejected"] or report["unlisted_wavs"]))


def run_audit(args: argparse.Namespace) -> int:
    verify_digest(args.fsd50k, FSD50K_GROUND_TRUTH_SHA256)
    report = overlap_report(
        load_esc50_metadata(args.esc50_metadata), read_fsd50k_partitions(args.fsd50k)
    )
    report["inputs"] = {
        "esc50_revision": ESC50_REVISION,
        "esc50_metadata_sha256": ESC50_METADATA_SHA256,
        "fsd50k_revision": FSD50K_REVISION,
        "fsd50k_ground_truth_sha256": FSD50K_GROUND_TRUTH_SHA256,
    }
    with new_output_directory(args.out):
        write_json(args.out / "overlap.json", report)
    print(
        f"{report['shared_esc50_rows']} ESC-50 rows share "
        f"{report['shared_source_ids']} FSD50K source IDs. "
        f"Report: {args.out / 'overlap.json'}"
    )
    return 0


def run_spike(args: argparse.Namespace) -> int:
    report = write_spike(
        args.esc50,
        read_manifest(args.inventory),
        args.out,
        seed=args.seed,
        index_size=args.index_size,
        manifest_sha256=sha256_file(args.inventory),
    )
    print(
        f"Prepared {report['indexed_assets']} index items, "
        f"{report['positive_queries']} matching crops, and "
        f"{report['absent_source_queries']} absent-source queries in {args.out}."
    )
    return 0


def run_index(args: argparse.Namespace) -> int:
    report = build_index(
        args.manifest,
        args.root or args.manifest.parent,
        args.out,
        read_config(args.config),
        replace_existing=args.replace,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


def run_match(args: argparse.Namespace) -> int:
    try:
        expected_config = read_config(args.config) if args.config is not None else None
        policy = read_policy(args.policy) if args.policy is not None else DEFAULT_POLICY
        aligner = resolve_alignment_engine(args.engine)
        with open_index(args.index, expected_config) as index:
            result = match_audio(
                args.path, index, limit=args.limit, policy=policy, aligner=aligner
            )
            digest = index.config.digest
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        if not args.json:
            raise
        print(
            json.dumps(
                {
                    "schema_version": MATCH_SCHEMA_VERSION,
                    "status": "input_error",
                    "query_id": args.path.name,
                    "message": str(error),
                }
            )
        )
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    **asdict(result),
                    "query_id": args.path.name,
                    "fingerprint_config_sha256": digest,
                    "match_policy_sha256": policy.digest,
                },
                sort_keys=True,
            )
        )
    elif result.status == "matched":
        winner = result.candidates[0]
        print(
            f"{winner.asset_id} at {winner.offset_seconds:+.3f} s ({winner.score} aligned landmarks)"
        )
    else:
        print(result.status.replace("_", " "))
    return 0


def run_batch_audit(args: argparse.Namespace) -> int:
    if args.out.exists():
        raise FileExistsError(f"audit output already exists: {args.out}")
    policy = read_policy(args.policy) if args.policy is not None else DEFAULT_POLICY
    config = read_config(args.config) if args.config is not None else None
    batch = scan_manifest(
        args.manifest,
        args.root or args.manifest.parent,
        args.index,
        policy,
        config=config,
        limit=args.limit,
        aligner=resolve_alignment_engine(args.engine),
    )
    report = write_batch(batch, args.out)
    print(json.dumps(report, sort_keys=True))
    return int(report["decisions"].get("input_error", 0) > 0)


def add_match_commands(commands) -> None:
    index = commands.add_parser("index", help="build a local SQLite fingerprint index")
    index.add_argument("manifest", type=Path)
    index.add_argument(
        "--root", type=Path, help="audio root (defaults to the manifest directory)"
    )
    index.add_argument("--out", required=True, type=Path)
    index.add_argument("--config", type=Path, help="fingerprint configuration JSON")
    index.add_argument(
        "--replace",
        action="store_true",
        help="replace the old index after a successful build",
    )
    index.set_defaults(handler=run_index)

    match = commands.add_parser(
        "match", help="look up the recording and offset for a clip"
    )
    match.add_argument("path", type=Path)
    match.add_argument("--index", required=True, type=Path)
    match.add_argument(
        "--config", type=Path, help="require this fingerprint configuration"
    )
    match.add_argument("--policy", type=Path, help="threshold policy JSON")
    match.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    match.add_argument(
        "--engine",
        choices=("python", "rust"),
        default="python",
        help="offset voting engine (default: Python)",
    )
    match.add_argument("--json", action="store_true")
    match.set_defaults(handler=run_match)

    audit = commands.add_parser(
        "audit", help="match an audio manifest and write query and candidate CSVs"
    )
    audit.add_argument("manifest", type=Path)
    audit.add_argument(
        "--root",
        type=Path,
        help="query audio root (defaults to the manifest directory)",
    )
    audit.add_argument("--index", type=Path, required=True)
    audit.add_argument(
        "--config", type=Path, help="require this fingerprint configuration"
    )
    audit.add_argument("--policy", type=Path, help="threshold policy JSON")
    audit.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    audit.add_argument(
        "--engine",
        choices=("python", "rust"),
        default="python",
        help="offset voting engine (default: Python)",
    )
    audit.add_argument("--out", type=Path, required=True)
    audit.set_defaults(handler=run_batch_audit)


def add_data_commands(commands) -> None:
    data = commands.add_parser(
        "data", help="fetch, inventory, and prepare dataset inputs"
    )
    data_commands = data.add_subparsers(dest="data_command", required=True)
    fetch = data_commands.add_parser(
        "fetch", help="fetch pinned ESC-50 and FSD50K metadata"
    )
    fetch.add_argument("--root", type=Path, default=Path(".local"))
    fetch.set_defaults(handler=run_fetch)

    inventory = data_commands.add_parser(
        "inventory", help="decode and checksum the ESC-50 corpus"
    )
    inventory.add_argument("--esc50", required=True, type=Path)
    inventory.add_argument("--out", required=True, type=Path)
    inventory.set_defaults(handler=run_inventory)

    audit = data_commands.add_parser(
        "audit", help="compare original recording IDs in the metadata"
    )
    audit.add_argument(
        "--esc50-metadata", required=True, type=Path, help="pinned ESC-50 CSV"
    )
    audit.add_argument(
        "--fsd50k", required=True, type=Path, help="v1.0 ground-truth ZIP"
    )
    audit.add_argument("--out", required=True, type=Path)
    audit.set_defaults(handler=run_audit)

    spike = data_commands.add_parser(
        "spike", help="create indexed references and crop queries"
    )
    spike.add_argument("--esc50", required=True, type=Path)
    spike.add_argument(
        "--inventory", required=True, type=Path, help="verified assets.csv"
    )
    spike.add_argument("--out", required=True, type=Path)
    spike.add_argument("--seed", type=int, default=DEFAULT_SEED)
    spike.add_argument("--index-size", type=int, default=DEFAULT_INDEX_SIZE)
    spike.set_defaults(handler=run_spike)


def run_experiment_command(args: argparse.Namespace) -> int:
    if args.experiment_command == "prepare":
        from echo.experiment_data import prepare_design

        report = prepare_design(args.inventory, args.esc_root, args.spec, args.out)
        print(json.dumps(report["validation"]["rows"], sort_keys=True))
        return 0

    try:
        from echo.experiment import calibrate, run_experiment, run_smoke
    except ModuleNotFoundError as error:
        if error.name != "torch":
            raise
        raise ValueError(
            "install the locked experiment group with uv sync --locked --group experiment"
        ) from error

    inputs = (args.inventory, args.esc_root, args.design)
    if args.experiment_command == "smoke":
        report = run_smoke(*inputs, args.out)
        print(f"CPU smoke replay matched in {args.out}")
    elif args.experiment_command == "calibrate":
        report = calibrate(*inputs, args.out)
        print(
            f"Frozen validation-selected learning rate {report['learning_rate']:g} in {args.out}"
        )
    else:
        report = run_experiment(*inputs, args.calibration, args.out)
        print(
            f"Mean exposed minus comparison accuracy {report['slices']['all']['mean_delta_accuracy_pp']:+.2f} pp in {args.out}"
        )
    return 0


def add_experiment_commands(commands) -> None:
    experiment = commands.add_parser(
        "experiment", help="run the controlled ESC-50 leakage study"
    )
    modes = experiment.add_subparsers(dest="experiment_command", required=True)
    for name, help_text in (
        ("prepare", "freeze group-disjoint splits and render paired crops"),
        ("smoke", "verify deterministic CPU training on a small clean subset"),
        (
            "calibrate",
            "select the recipe using the clean training and validation splits",
        ),
        ("run", "train paired models and score the fixed test set"),
    ):
        command = modes.add_parser(name, help=help_text)
        for arg in ("--inventory", "--esc-root", "--out"):
            command.add_argument(arg, type=Path, required=True)
        if name == "prepare":
            command.add_argument(
                "--spec", type=Path, default=Path("bench/stage5-spec.json")
            )
        else:
            command.add_argument("--design", type=Path, required=True)
        if name == "run":
            command.add_argument("--calibration", type=Path, required=True)
        command.set_defaults(handler=run_experiment_command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="echo-audit", description="Audit shared recordings across audio datasets."
    )
    parser.add_argument(
        "--version", action="version", version=f"echo-audit {version('echo-audit')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fixture = commands.add_parser(
        "fixture", help="write deterministic synthetic WAV fixtures"
    )
    fixture.add_argument("--out", required=True, type=Path, help="new output directory")
    fixture.set_defaults(handler=run_fixture)

    audio = commands.add_parser(
        "audio", help="decode audio and print source and output metadata"
    )
    audio.add_argument("path", type=Path)
    audio.add_argument("--target-rate", type=int)
    audio.set_defaults(handler=run_audio)

    add_data_commands(commands)
    add_match_commands(commands)
    add_experiment_commands(commands)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (
        OSError,
        RuntimeError,
        ValueError,
        BadZipFile,
        sqlite3.DatabaseError,
        KeyError,
        csv.Error,
    ) as error:
        print(f"echo-audit: {error}", file=sys.stderr)
        return 1
