"""Run the calibration and holdout with a recorded, reusable policy."""

import csv
import json
import platform
import resource
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.audio import load_audio
from echo.datasets import Asset, read_manifest
from echo.evaluation_data import SPLITS, Trial, design_digest, read_trials
from echo.evaluation_metrics import match_counts, summarize
from echo.fingerprint import FingerprintConfig, fingerprint
from echo.index import build_index, open_index
from echo.matcher import (
    DEFAULT_POLICY,
    MatchPolicy,
    MatchResult,
    decide,
    rank_landmarks,
    read_policy,
)

POLICIES = {
    "stage2": DEFAULT_POLICY,
    "short_span": replace(DEFAULT_POLICY, min_coverage=0.14),
    "short_span_margin": replace(
        DEFAULT_POLICY, min_coverage=0.14, min_score_margin=12
    ),
    "weaker_support_margin": replace(
        DEFAULT_POLICY, min_support_fraction=0.02, min_score_margin=12
    ),
    "larger_support": replace(DEFAULT_POLICY, min_support=28, min_score_margin=12),
    "larger_span": replace(DEFAULT_POLICY, min_coverage=0.33, min_score_margin=12),
    "short_span_weaker_support": replace(
        DEFAULT_POLICY,
        min_coverage=0.14,
        min_support_fraction=0.02,
        min_score_margin=12,
    ),
    "high_precision": replace(
        DEFAULT_POLICY, min_support=32, min_support_fraction=0.06, min_score_margin=20
    ),
}


@dataclass(frozen=True, slots=True)
class Partition:
    root: Path
    references: list[Asset]
    trials: list[Trial]

    @property
    def source_ids(self) -> set[str]:
        return {item.source_id for item in self.references} | {
            trial.source_id for trial in self.trials
        }


def read_design(path: Path) -> tuple[dict, dict[str, Partition]]:
    design = json.loads((path / "design.json").read_text(encoding="utf-8"))
    if design.get("schema_version") != 1:
        raise ValueError("unsupported evaluation design version")
    partitions = {}
    for name in SPLITS:
        root = path / name
        index = root / "index.csv"
        queries = root / "queries.csv"
        record = design["splits"][name]
        if (
            sha256_file(index) != record["index_sha256"]
            or sha256_file(queries) != record["queries_sha256"]
        ):
            raise ValueError(f"{name}: manifest differs from the frozen design")
        references = read_manifest(index)
        trials = read_trials(queries)
        verify_partition(references, trials, name)
        partitions[name] = Partition(root, references, trials)
    if partitions["calibration"].source_ids & partitions["test"].source_ids:
        raise ValueError("calibration and test share a source group")
    return design, partitions


def verify_partition(references: list[Asset], trials: list[Trial], name: str) -> None:
    sources = {asset.source_id for asset in references}
    exact = {asset.sha256 for asset in references}
    by_id = {asset.asset_id: asset for asset in references}
    group_identity = {}
    for trial in trials:
        identity = (
            trial.kind,
            trial.expected_id,
            trial.provenance_service,
            trial.provenance_id,
        )
        if group_identity.setdefault(trial.source_id, identity) != identity:
            raise ValueError(f"{name}: inconsistent derivatives for {trial.source_id}")
        if trial.kind == "positive":
            reference = by_id.get(trial.expected_id)
            if reference is None or reference.source_id != trial.source_id:
                raise ValueError(
                    f"{name}: missing positive reference for {trial.query_id}"
                )
        else:
            distractor = by_id.get(trial.distractor_id)
            if trial.source_id in sources or trial.sha256 in exact:
                raise ValueError(
                    f"{name}: absent source is indexed for {trial.query_id}"
                )
            if distractor is None or distractor.label != trial.label:
                raise ValueError(
                    f"{name}: missing same-class distractor for {trial.query_id}"
                )


@dataclass(frozen=True, slots=True)
class TrialEvidence:
    trial: Trial
    result: MatchResult | None
    partial: dict


def baseline(candidates: list[str] | None, expected: str) -> tuple[str, int | None]:
    if candidates is None:
        return "unavailable", None
    rank = candidates.index(expected) + 1 if expected in candidates else None
    return ("matched" if candidates else "no_match"), rank


def rank_partition(
    root: Path, partition: Partition, index_path: Path
) -> tuple[list[TrialEvidence], dict]:
    config = FingerprintConfig()
    start = perf_counter()
    index_info = build_index(partition.root / "index.csv", root, index_path, config)
    index_info["build_ms"] = round((perf_counter() - start) * 1000, 3)
    bytes_index = defaultdict(list)
    provenance = defaultdict(list)
    for asset in sorted(partition.references, key=lambda reference: reference.asset_id):
        bytes_index[asset.sha256].append(asset.asset_id)
        provenance[asset.source_service, asset.source_id].append(asset.asset_id)
    evidence = []
    with open_index(index_path, config) as index:
        for trial in partition.trials:
            evidence.append(
                rank_trial(trial, partition.root, index, bytes_index, provenance)
            )
    return evidence, index_info


def rank_trial(trial, root, index, bytes_index, provenance) -> TrialEvidence:
    if trial.exclusion_reason:
        return TrialEvidence(
            trial, None, {"decision": "excluded", "message": trial.exclusion_reason}
        )
    path = (root / trial.query_path).resolve()
    try:
        if not path.is_relative_to(root.resolve()) or sha256_file(path) != trial.sha256:
            raise ValueError("query path or checksum differs from the frozen manifest")
        started = perf_counter()
        audio = load_audio(path, target_rate=index.config.sample_rate)
        decoded = perf_counter()
        hashes = fingerprint(audio.samples, index.config)
        fingerprinted = perf_counter()
        result = rank_landmarks(hashes, len(audio.samples), index)
        ranked = perf_counter()
    except (OSError, ValueError) as error:
        return TrialEvidence(
            trial, None, {"decision": "input_error", "message": str(error)}
        )

    bytes_status, bytes_rank = baseline(
        bytes_index.get(trial.sha256, []), trial.expected_id
    )
    known = None
    if trial.provenance_id:
        known = provenance.get((trial.provenance_service, trial.provenance_id), [])
    source_status, source_rank = baseline(known, trial.expected_id)
    partial = {
        "bytes_status": bytes_status,
        "bytes_rank": bytes_rank,
        "source_status": source_status,
        "source_rank": source_rank,
        "decode_ms": round((decoded - started) * 1000, 3),
        "fingerprint_ms": round((fingerprinted - decoded) * 1000, 3),
        "ranking_ms": round((ranked - fingerprinted) * 1000, 3),
        "total_ms": round((ranked - started) * 1000, 3),
    }
    return TrialEvidence(trial, result, partial)


RESULT_COLUMNS = (
    "query_id",
    "variant",
    "kind",
    "source_id",
    "stratum",
    "label",
    "id_visibility",
    "expected_id",
    "best_id",
    "expected_rank",
    "decision",
    "expected_offset_ms",
    "offset_ms",
    "offset_error_ms",
    "best_score",
    "runner_up_score",
    "best_anchor_frames",
    "best_distinct_hashes",
    "coverage",
    "support_fraction",
    "bytes_status",
    "bytes_rank",
    "source_status",
    "source_rank",
    "decode_ms",
    "fingerprint_ms",
    "ranking_ms",
    "total_ms",
    "message",
)


def results_for(evidence: list[TrialEvidence], policy: MatchPolicy) -> list[dict]:
    rows = []
    for entry in evidence:
        trial, raw = entry.trial, entry.result
        row = {
            "query_id": trial.query_id,
            "variant": trial.variant,
            "kind": trial.kind,
            "source_id": trial.source_id,
            "stratum": trial.stratum,
            "label": trial.label,
            "id_visibility": "visible" if trial.provenance_id else "masked",
            "expected_id": trial.expected_id,
            **entry.partial,
        }
        if raw is not None:
            candidates = raw.candidates
            best = candidates[0] if candidates else None
            expected_rank = next(
                (
                    candidate.rank
                    for candidate in candidates
                    if candidate.asset_id == trial.expected_id
                ),
                None,
            )
            expected_offset = (
                trial.expected_offset * 1000 if trial.expected_id else None
            )
            row.update(
                decision=decide(raw, policy).status,
                expected_rank=expected_rank,
                expected_offset_ms=expected_offset,
                offset_error_ms=None,
            )
            if best is not None:
                row.update(
                    best_id=best.asset_id,
                    offset_ms=best.offset_seconds * 1000,
                    best_score=best.score,
                    runner_up_score=candidates[1].score if len(candidates) > 1 else 0,
                    best_anchor_frames=best.anchor_frames,
                    best_distinct_hashes=best.distinct_hashes,
                    coverage=round(best.coverage, 6),
                    support_fraction=round(best.support_fraction, 6),
                )
                if expected_rank == 1:
                    row["offset_error_ms"] = round(
                        abs(row["offset_ms"] - expected_offset), 6
                    )
        rows.append(row)
    return rows


def select_policy(evidence: list[TrialEvidence]) -> tuple[str, list[dict]]:
    choices = []
    for name, policy in POLICIES.items():
        rows = results_for(evidence, policy)
        valid = [
            row for row in rows if row["decision"] not in {"excluded", "input_error"}
        ]
        counts = match_counts(valid)
        choices.append({"name": name, "policy": asdict(policy), "counts": counts})
    best = min(
        choices,
        key=lambda choice: (
            choice["counts"]["false_accepts"],
            choice["counts"]["incorrect_accepts"],
            -choice["counts"]["correct_accepts"],
        ),
    )
    return best["name"], choices


def run_info() -> dict:
    project = Path(__file__).resolve().parents[2]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project, text=True
        ).strip(),
        "dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=project)
        ),
        "lock_sha256": sha256_file(project / "uv.lock"),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "platform": platform.system(),
        "peak_whole_process_rss_bytes": rss
        if platform.system() == "Darwin"
        else rss * 1024,
    }


def write_results(
    out: Path, rows: list[dict], index_info: dict, policy: MatchPolicy
) -> dict:
    path = out / "results.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, RESULT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "schema_version": 1,
        "index": index_info,
        "metrics": summarize(rows),
        "results_sha256": sha256_file(path),
        "policy_sha256": policy.digest,
        "run": run_info(),
        "timing_scope": "One open SQLite connection. Per-query timing excludes checksum and report writing.",
    }
    write_json(out / "summary.json", report)
    return report


def calibrate(root: Path, design_root: Path, out: Path) -> dict:
    design, partitions = read_design(design_root)
    with new_output_directory(out):
        evidence, index_info = rank_partition(
            root, partitions["calibration"], out / "index.sqlite"
        )
        selected, choices = select_policy(evidence)
        policy = POLICIES[selected]
        report = write_results(out, results_for(evidence, policy), index_info, policy)
        if report["metrics"]["input_errors"]:
            return report

        write_json(out / "policy.json", asdict(policy))
        write_json(
            out / "calibration.json",
            {
                "schema_version": 1,
                "design_sha256": design_digest(design),
                "calibration_summary_sha256": sha256_file(out / "summary.json"),
                "fingerprint_sha256": FingerprintConfig().digest,
                "chosen_policy": selected,
                "policy_sha256": policy.digest,
                "selection_order": [
                    "fewer_false_accepts",
                    "fewer_incorrect_accepts",
                    "more_correct_accepts",
                    "grid_order",
                ],
                "candidates": choices,
            },
        )
    return report


def evaluate_test(root: Path, design_root: Path, calibration: Path, out: Path) -> dict:
    design, partitions = read_design(design_root)
    frozen = json.loads((calibration / "calibration.json").read_text(encoding="utf-8"))
    policy = read_policy(calibration / "policy.json")
    if (
        frozen["design_sha256"] != design_digest(design)
        or frozen["calibration_summary_sha256"]
        != sha256_file(calibration / "summary.json")
        or frozen["fingerprint_sha256"] != FingerprintConfig().digest
        or frozen["policy_sha256"] != policy.digest
        or frozen["chosen_policy"] not in POLICIES
        or policy != POLICIES[frozen["chosen_policy"]]
    ):
        raise ValueError("calibration record, policy, or design has changed")
    with new_output_directory(out):
        evidence, index_info = rank_partition(
            root, partitions["test"], out / "index.sqlite"
        )
        report = write_results(out, results_for(evidence, policy), index_info, policy)
        report["design_sha256"] = design_digest(design)
        report["calibration_sha256"] = sha256_file(calibration / "calibration.json")
        write_json(out / "summary.json", report)
    return report
