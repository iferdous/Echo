"""Execute the generated smoke benchmark and the verified local replay."""

import csv
import os
import platform
import sqlite3
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.batch import scan_manifest, write_batch
from echo.datasets import Asset, read_manifest, write_manifest
from echo.evidence import (
    FIXTURE_FILES,
    REPLAY_FILES,
    make_evidence,
    published_evidence,
    require,
    write_evidence,
)
from echo.fingerprint import FingerprintConfig
from echo.fixtures import (
    CROP_SAMPLES,
    CROP_START,
    FIXTURE_SEED,
    SAMPLE_RATE,
    write_fixture,
)
from echo.index import build_index
from echo.matcher import DEFAULT_POLICY, read_policy, resolve_alignment_engine

RECOVERY = "see docs/reproduce-evidence.md for the pinned inputs and build commands"


def capture_environment(repo: Path, started: datetime, tick: float) -> dict:
    git = (repo / ".git").exists()
    commit = None
    dirty = None
    if git:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)
        )
    return {
        "source_commit": commit,
        "dirty": dirty,
        "lock_sha256": sha256_file(repo / "uv.lock")
        if (repo / "uv.lock").is_file()
        else None,
        "echo_audit": version("echo-audit"),
        "python": platform.python_version(),
        "numpy": version("numpy"),
        "scipy": version("scipy"),
        "soundfile": version("soundfile"),
        "libsndfile": sf.__libsndfile_version__,
        "sqlite": sqlite3.sqlite_version,
        "system": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "started_utc": started.isoformat(),
        "completed_utc": datetime.now(UTC).isoformat(),
        "wall_seconds": perf_counter() - tick,
    }


def build_fixture(repo: Path, out: Path) -> None:
    started, tick = datetime.now(UTC), perf_counter()
    config = FingerprintConfig()
    expected_results = {
        "crop": "matched",
        "absent": "no_match",
        "silent": "insufficient_evidence",
    }
    with new_output_directory(out), TemporaryDirectory(dir=out) as directory:
        work = Path(directory)
        audio = work / "audio"
        write_fixture(audio)
        sf.write(
            audio / "silence.wav", np.zeros(CROP_SAMPLES), SAMPLE_RATE, subtype="PCM_16"
        )
        reference_manifest = audio / "index.csv"
        queries = work / "query-manifest.csv"
        write_manifest(
            queries,
            [
                Asset(
                    name,
                    "fixture",
                    str(FIXTURE_SEED),
                    file,
                    "query",
                    sha256=sha256_file(audio / file),
                )
                for name, file in (
                    ("crop", "query.wav"),
                    ("absent", "distractor.wav"),
                    ("silent", "silence.wav"),
                )
            ],
        )
        index = work / "index.sqlite"
        build_index(reference_manifest, audio, index, config)
        batch = scan_manifest(queries, audio, index, DEFAULT_POLICY)
        require(
            {row.asset.asset_id: row.status for row in batch.queries}
            == expected_results,
            "fixture decisions differ from the smoke expectations",
        )
        match = batch.queries[0].match
        expected_offset = CROP_START / SAMPLE_RATE
        require(
            match is not None
            and match.candidates[0].asset_id == "fixture:reference"
            and abs(match.candidates[0].offset_seconds - expected_offset)
            <= config.hop_size / SAMPLE_RATE,
            "fixture did not recover the known recording within one fingerprint hop",
        )
        run = work / "audit"
        write_batch(batch, run)
        recipe = work / "recipe.json"
        write_json(
            recipe,
            {
                "schema_version": 1,
                "seed": FIXTURE_SEED,
                "source": "deterministically generated audio",
                "fingerprint": asdict(config),
                "policy": asdict(DEFAULT_POLICY),
                "expected": expected_results,
                "reference_id": "fixture:reference",
                "expected_offset_seconds": expected_offset,
                "offset_tolerance_seconds": config.hop_size / SAMPLE_RATE,
            },
        )
        sources = (
            recipe,
            reference_manifest,
            queries,
            run / "audit.json",
            run / "queries.csv",
            run / "candidates.csv",
        )
        payload = {
            name: file.read_bytes()
            for name, file in zip(FIXTURE_FILES, sources, strict=True)
        }
        evidence = make_evidence(
            "fixture", payload, capture_environment(repo, started, tick)
        )
        write_evidence(evidence, out)


def verify_file(path: Path, expected: str) -> None:
    require(path.is_file(), f"missing local input {path}; {RECOVERY}")
    require(sha256_file(path) == expected, f"local input changed: {path}; {RECOVERY}")


def verify_audio(manifest: Path, root: Path, expected_count: int) -> int:
    tracks = read_manifest(manifest)
    require(
        len(tracks) == expected_count, f"{manifest}: expected {expected_count} files"
    )
    for track in tracks:
        verify_file(track.local_path(root), track.sha256)
    return len(tracks)


def build_full(
    repo: Path,
    data_root: Path,
    out: Path,
    *,
    fsd_root: Path | None = None,
    index: Path | None = None,
    engine: str = "python",
) -> None:
    started, tick = datetime.now(UTC), perf_counter()
    published = published_evidence(repo)
    historical = published.json("results/stage-4-summary.json")
    inventory = published.json("results/stage-1-inventory.json")
    cohort = published.json("results/stage-4-cohort.json")
    receipt = historical["batch"]
    esc_root = data_root / "esc50"
    if fsd_root is None:
        completed = data_root / "stage4/fsd50k-complete"
        fsd_root = completed if completed.is_dir() else data_root / "stage4/fsd50k"
    if index is None:
        index = data_root / "stage4/audit-run/index.sqlite"
    originals = data_root / "stage1/inventory/assets.csv"
    verify_file(originals, inventory["manifest_sha256"])
    verify_file(
        data_root / "downloads/fsd50k-ground-truth.zip", cohort["ground_truth_sha256"]
    )
    require(index.is_file(), f"missing saved Stage 4 index {index}; {RECOVERY}")
    aligner = resolve_alignment_engine(engine)
    with new_output_directory(out), TemporaryDirectory(dir=out) as directory:
        temporary = Path(directory)
        references, queries, policy_file = (
            temporary / file
            for file in ("references.csv", "queries.csv", "policy.json")
        )
        for local, name in (
            (references, "stage-4-index-manifest.csv"),
            (queries, "stage-4-query-manifest.csv"),
            (policy_file, "stage-3-policy.json"),
        ):
            local.write_bytes(published.payload[f"results/{name}"])
        esc_count = verify_audio(originals, esc_root, inventory["decoded_assets"])
        fsd_count = verify_audio(references, fsd_root, receipt["indexed_assets"])
        policy = read_policy(policy_file)
        config = FingerprintConfig()
        require(
            policy.digest == receipt["match_policy_sha256"],
            "stage 4 policy does not match the published audit",
        )
        batch = scan_manifest(
            queries,
            esc_root,
            index,
            policy,
            config=config,
            limit=receipt["result_limit"],
            reference_manifest_sha256=receipt["reference_manifest_sha256"],
            aligner=aligner,
        )
        replay = temporary / "audit"
        new = write_batch(batch, replay)
        require(
            new["run_id"] == receipt["run_id"]
            and new["decisions"] == receipt["decisions"]
            and new["candidates_sha256"] == receipt["candidates_sha256"],
            "full replay disagrees with the saved decisions or candidate rankings",
        )
        with (replay / "queries.csv").open(newline="", encoding="utf-8") as stream:
            actual = list(csv.DictReader(stream))
        expected = published.rows("results/stage-4-batch-queries.csv")
        for group in (actual, expected):
            for row in group:
                row.pop("elapsed_ms")
        require(actual == expected, "full replay changed a saved query result")
        native_profile = published.json("results/stage-6/tuned-stage4.json")
        database_sha = sha256_file(index)
        verification = {
            "schema_version": 1,
            "audio_sha256_verified": {"esc50": esc_count, "fsd50k_eval": fsd_count},
            "audit_run_id": new["run_id"],
            "equal_query_rows": new["query_count"],
            "equal_candidate_rows": new["candidate_count"],
            "sqlite_sha256": database_sha,
            "matches_profiled_sqlite_bytes": database_sha
            == native_profile["index"]["sha256"],
            "replay_engine": engine,
            "historical_classifier_run_id": published.json(
                "results/stage-5-summary.json"
            )["run_id"],
        }
        write_json(replay / "verification.json", verification)
        payload = {
            **published.payload,
            **{name: (replay / Path(name).name).read_bytes() for name in REPLAY_FILES},
        }
        evidence = make_evidence(
            "full", payload, capture_environment(repo, started, tick)
        )
        write_evidence(evidence, out)
