"""Audit a manifest of audio files against a persisted fingerprint index."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.datasets import Asset, read_manifest
from echo.fingerprint import FingerprintConfig
from echo.index import open_index
from echo.matcher import (
    DEFAULT_LIMIT,
    AlignmentEngine,
    MatchPolicy,
    MatchResult,
    align_tracks,
    match_audio,
)

QUERY_COLUMNS = (
    "run_id",
    "query_id",
    "decision",
    "best_reference",
    "offset_seconds",
    "query_landmarks",
    "elapsed_ms",
    "message",
)
CANDIDATE_COLUMNS = (
    "run_id",
    "query_id",
    "reference_id",
    "rank",
    "offset_seconds",
    "score",
    "anchor_frames",
    "distinct_hashes",
    "coverage",
    "support_fraction",
    "query_start_seconds",
    "query_end_seconds",
    "reference_start_seconds",
    "reference_end_seconds",
    "passes_threshold",
    "accepted",
)


@dataclass(frozen=True, slots=True)
class ScannedQuery:
    asset: Asset
    match: MatchResult | None
    elapsed_ms: float
    error: str = ""

    @property
    def status(self) -> str:
        return self.match.status if self.match is not None else "input_error"


@dataclass(frozen=True, slots=True)
class Batch:
    metadata: dict
    queries: list[ScannedQuery]


def scan_manifest(
    manifest: Path,
    root: Path,
    index_path: Path,
    policy: MatchPolicy,
    *,
    config: FingerprintConfig | None = None,
    limit: int = DEFAULT_LIMIT,
    reference_manifest_sha256: str | None = None,
    aligner: AlignmentEngine = align_tracks,
) -> Batch:
    if limit < 1:
        raise ValueError("result limit must be positive")
    query_digest = sha256_file(manifest)
    assets = read_manifest(manifest)
    if sha256_file(manifest) != query_digest:
        raise ValueError("query manifest changed while it was read")
    queries = []
    with open_index(index_path, config) as index:
        if (
            reference_manifest_sha256 is not None
            and index.manifest_sha256 != reference_manifest_sha256
        ):
            raise ValueError("index was built from a different reference manifest")
        metadata = {
            "schema_version": 1,
            "query_manifest_sha256": query_digest,
            "reference_manifest_sha256": index.manifest_sha256,
            "fingerprint_config_sha256": index.config.digest,
            "match_policy_sha256": policy.digest,
            "indexed_assets": len(index.tracks),
            "result_limit": limit,
        }
        metadata["run_id"] = hashlib.sha256(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for asset in assets:
            start = perf_counter()
            try:
                audio = asset.local_path(root)
                if asset.sha256 and sha256_file(audio) != asset.sha256:
                    raise ValueError(
                        f"{asset.asset_id}: audio differs from the manifest checksum"
                    )
                result = match_audio(
                    audio, index, limit=limit, policy=policy, aligner=aligner
                )
            except (OSError, ValueError) as error:
                queries.append(
                    ScannedQuery(
                        asset,
                        None,
                        round((perf_counter() - start) * 1000, 3),
                        str(error),
                    )
                )
                continue
            queries.append(
                ScannedQuery(asset, result, round((perf_counter() - start) * 1000, 3))
            )
    return Batch(metadata, queries)


def write_batch(batch: Batch, path: Path) -> dict:
    run_id = batch.metadata["run_id"]
    queries = []
    candidates = []
    for row in batch.queries:
        matches = row.match.candidates if row.match else []
        query = {
            "run_id": run_id,
            "query_id": row.asset.asset_id,
            "decision": row.status,
            "elapsed_ms": row.elapsed_ms,
            "message": row.error,
        }
        if row.match:
            query["query_landmarks"] = row.match.query_landmarks
        if matches:
            query.update(
                best_reference=matches[0].asset_id,
                offset_seconds=matches[0].offset_seconds,
            )
        queries.append(query)
        for candidate in matches:
            candidates.append(
                {
                    "run_id": run_id,
                    "query_id": row.asset.asset_id,
                    "reference_id": candidate.asset_id,
                    "rank": candidate.rank,
                    "offset_seconds": candidate.offset_seconds,
                    "score": candidate.score,
                    "anchor_frames": candidate.anchor_frames,
                    "distinct_hashes": candidate.distinct_hashes,
                    "coverage": candidate.coverage,
                    "support_fraction": candidate.support_fraction,
                    "query_start_seconds": candidate.query_span_seconds[0],
                    "query_end_seconds": candidate.query_span_seconds[1],
                    "reference_start_seconds": candidate.reference_span_seconds[0],
                    "reference_end_seconds": candidate.reference_span_seconds[1],
                    "passes_threshold": candidate.passes_threshold,
                    "accepted": candidate.rank == 1 and row.status == "matched",
                }
            )
    report = {
        **batch.metadata,
        "query_count": len(queries),
        "candidate_count": len(candidates),
        "decisions": dict(Counter(row.status for row in batch.queries)),
    }
    with new_output_directory(path):
        write_csv(path / "queries.csv", QUERY_COLUMNS, queries)
        write_csv(path / "candidates.csv", CANDIDATE_COLUMNS, candidates)
        report["queries_sha256"] = sha256_file(path / "queries.csv")
        report["candidates_sha256"] = sha256_file(path / "candidates.csv")
        write_json(path / "audit.json", report)
    return report
