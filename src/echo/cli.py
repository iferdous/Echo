"""Command-line entry point for Echo."""

import argparse
import csv
import sys
from importlib.metadata import version
from pathlib import Path
from zipfile import BadZipFile

from echo.acquisition import fetch_stage_one, verify_digest
from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.audio import load_audio
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
from echo.fixtures import write_fixture
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
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (
        OSError,
        RuntimeError,
        ValueError,
        BadZipFile,
        KeyError,
        csv.Error,
    ) as error:
        print(f"echo-audit: {error}", file=sys.stderr)
        return 1
