"""Score the frozen cross-dataset cohort and independently review its audio."""

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from echo import waveform_review
from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.audio import load_audio
from echo.batch import Batch, scan_manifest, write_batch
from echo.cross_dataset import read_acquisition, read_cohort
from echo.datasets import Asset
from echo.evaluation import run_info
from echo.fingerprint import FingerprintConfig
from echo.index import build_index
from echo.matcher import read_policy

OFFSET_TOLERANCE_SECONDS = 0.032
REJECTED_PER_COHORT = 6

QUERY_COLUMNS = (
    "query_id",
    "query_path",
    "query_label",
    "query_cohort",
    "query_source_id",
    "query_source_url",
    "previously_seen_source",
    "expected_reference",
    "expected_indexed",
    "matcher_decision",
    "top_reference",
    "top_source_id",
    "top_score",
    "top_offset_seconds",
    "top_review_verdict",
    "outcome",
)
REVIEW_COLUMNS = (
    "query_id",
    "reference_id",
    "query_cohort",
    "query_source_id",
    "reference_source_id",
    "reference_source_url",
    "reference_license",
    "review_reasons",
    "matcher_rank",
    "matcher_score",
    "matcher_offset_seconds",
    "matcher_accepted",
    "verdict",
    "offset_agrees",
    *waveform_review.Review.__dataclass_fields__,
)


def review_queue(
    batch: Batch, references: dict[str, Asset], available: dict[str, Asset]
):
    known = {asset.source_id: asset.asset_id for asset in references.values()}
    queue = defaultdict(set)
    rejected = defaultdict(list)
    for row in batch.queries:
        if row.match is None:
            continue
        query = row.asset
        expected = known.get(query.source_id)
        top = next(iter(row.match.candidates), None)
        accepted = row.status == "matched" and top is not None
        if expected in available:
            reasons = queue[query.asset_id, expected]
            reasons.add("known_source")
            if not accepted or top.asset_id != expected:
                reasons.add("missed_known_source")
        if accepted:
            reasons = queue[query.asset_id, top.asset_id]
            reasons.add("accepted_top")
            if query.source_id != available[top.asset_id].source_id:
                reasons.add("different_source_id")
        elif top is not None:
            rejected[query.role].append((-top.score, query.asset_id, top.asset_id))
    for items in rejected.values():
        for _, query, reference in sorted(items)[:REJECTED_PER_COHORT]:
            queue[query, reference].add("highest_scoring_rejected")
    return queue


def review_pairs(batch, references, available, acquisition, esc_root, fsd_root):
    scans = {row.asset.asset_id: row for row in batch.queries}

    @lru_cache(maxsize=32)
    def reference_audio(key):
        path = available[key].local_path(fsd_root)
        return load_audio(path, target_rate=waveform_review.SAMPLE_RATE).samples

    @lru_cache(maxsize=1)
    def query_audio(key):
        path = scans[key].asset.local_path(esc_root)
        return load_audio(path, target_rate=waveform_review.SAMPLE_RATE).samples

    reviews = {}
    queue = review_queue(batch, references, available)
    for (query_id, reference_id), reasons in sorted(queue.items()):
        scan = scans[query_id]
        reference = available[reference_id]
        match = next(
            (row for row in scan.match.candidates if row.asset_id == reference_id), None
        )
        result = waveform_review.verify_waveforms(
            query_audio(query_id), reference_audio(reference_id)
        )
        offset_agrees = None
        if result.offset_seconds is not None and match is not None:
            offset_agrees = (
                abs(match.offset_seconds - result.offset_seconds)
                <= OFFSET_TOLERANCE_SECONDS
            )
        reviews[query_id, reference_id] = {
            "query_id": query_id,
            "reference_id": reference_id,
            "query_cohort": scan.asset.role,
            "query_source_id": scan.asset.source_id,
            "reference_source_id": reference.source_id,
            "reference_source_url": reference.attribution,
            "reference_license": acquisition[reference_id]["license"],
            "review_reasons": "|".join(sorted(reasons)),
            "matcher_rank": match.rank if match else None,
            "matcher_score": match.score if match else None,
            "matcher_offset_seconds": match.offset_seconds if match else None,
            "matcher_accepted": "accepted_top" in reasons,
            "verdict": "confirmed" if result.verified else "unresolved",
            "offset_agrees": offset_agrees,
            **asdict(result),
        }
    return reviews


def coverage_outcome(status, expected, expected_indexed, expected_review, top_review):
    if status == "input_error":
        return "query_unavailable"
    if expected:
        if not expected_indexed:
            return "expected_reference_unavailable"
        if expected_review["verdict"] != "confirmed":
            return "same_source_audio_unresolved"
        if not expected_review["matcher_accepted"]:
            return "confirmed_audio_matcher_miss"
        if not expected_review["offset_agrees"]:
            return "confirmed_audio_offset_disagreement"
        return "confirmed_audio_matched"
    if status != "matched":
        return "control_not_accepted"
    if top_review["verdict"] != "confirmed":
        return "control_accepted_audio_unresolved"
    if not top_review["offset_agrees"]:
        return "control_confirmed_audio_offset_disagreement"
    return "control_confirmed_audio_matched"


def coverage_rows(batch, references, available, reviews, prior):
    known = {asset.source_id: asset.asset_id for asset in references.values()}
    rows = []
    for scan in batch.queries:
        query = scan.asset
        expected = known.get(query.source_id)
        expected_indexed = expected in available
        top = next(iter(scan.match.candidates), None) if scan.match else None
        top_key = top.asset_id if top else None
        top_review = reviews.get((query.asset_id, top_key), {})
        outcome = coverage_outcome(
            scan.status,
            expected,
            expected_indexed,
            reviews.get((query.asset_id, expected), {}),
            top_review,
        )
        rows.append(
            {
                "query_id": query.asset_id,
                "query_path": query.path,
                "query_label": query.label,
                "query_cohort": query.role,
                "query_source_id": query.source_id,
                "query_source_url": f"https://freesound.org/s/{query.source_id}/",
                "previously_seen_source": query.source_id in prior,
                "expected_reference": expected,
                "expected_indexed": expected_indexed if expected else None,
                "matcher_decision": scan.status,
                "top_reference": top_key,
                "top_source_id": available[top_key].source_id if top else None,
                "top_score": top.score if top else None,
                "top_offset_seconds": top.offset_seconds if top else None,
                "top_review_verdict": top_review.get("verdict", "unreviewed")
                if top
                else None,
                "outcome": outcome,
            }
        )
    return rows


def counts_by_outcome(rows):
    groups = defaultdict(set)
    for row in rows:
        groups[row["outcome"]].add(row["query_source_id"])
    counts = Counter(row["outcome"] for row in rows)
    return {
        outcome: {"query_rows": count, "unique_query_sources": len(groups[outcome])}
        for outcome, count in sorted(counts.items())
    }


def review_counts(reviews):
    groups = defaultdict(Counter)
    for row in reviews.values():
        for reason in row["review_reasons"].split("|"):
            groups[reason][row["verdict"]] += 1
    return {reason: dict(counts) for reason, counts in sorted(groups.items())}


def audit_cohort(
    cohort_root: Path,
    esc_root: Path,
    fsd_root: Path,
    policy_path: Path,
    calibration_path: Path,
    out: Path,
) -> dict:
    cohort, frozen_refs, _ = read_cohort(cohort_root)
    acquisition, available, acquired_rows = read_acquisition(
        fsd_root, cohort_root, frozen_refs
    )
    config = FingerprintConfig()
    policy = read_policy(policy_path)
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if (
        config.digest != calibration["fingerprint_sha256"]
        or policy.digest != calibration["policy_sha256"]
    ):
        raise ValueError(
            "audit requires the frozen Stage 3 policy and fingerprint configuration"
        )
    references = {asset.asset_id: asset for asset in frozen_refs}

    with new_output_directory(out):
        index_path = out / "index.sqlite"
        index = build_index(fsd_root / "index.csv", fsd_root, index_path, config)
        batch = scan_manifest(
            cohort_root / "queries.csv",
            esc_root,
            index_path,
            policy,
            config=config,
            reference_manifest_sha256=acquisition["index_sha256"],
        )
        batch_report = write_batch(batch, out / "batch")
        # Join metadata only after every acoustic ranking has completed.
        reviews = review_pairs(
            batch, references, available, acquired_rows, esc_root, fsd_root
        )
        prior = set(cohort["previously_seen_query_sources"])
        rows = coverage_rows(batch, references, available, reviews, prior)
        write_csv(out / "queries.csv", QUERY_COLUMNS, rows)
        write_csv(out / "reviews.csv", REVIEW_COLUMNS, reviews.values())
        summary = {
            "schema_version": 1,
            "batch": batch_report,
            "index": index,
            "cohort_sha256": sha256_file(cohort_root / "cohort.json"),
            "acquisition_sha256": sha256_file(fsd_root / "acquisition.json"),
            "calibration_sha256": sha256_file(calibration_path),
            "queries_sha256": sha256_file(out / "queries.csv"),
            "reviews_sha256": sha256_file(out / "reviews.csv"),
            "full_metadata": {
                "esc50_rows": cohort["full_esc50_rows"],
                "fsd50k_official_eval_rows": cohort["official_eval_sources"],
                "esc50_shared_any_fsd_split": cohort["all_fsd_partitions_shared_rows"],
                "esc50_shared_fsd_eval": cohort["query_cohorts"]["shared_eval_id"],
                "esc50_shared_fsd_eval_unique_sources": cohort[
                    "shared_eval_unique_sources"
                ],
            },
            "coverage": {
                "queried_by_cohort": cohort["query_cohorts"],
                "selected_references_by_cohort": cohort["index_cohorts"],
                "indexed_references_by_cohort": dict(
                    Counter(asset.role for asset in available.values())
                ),
                "scored_by_cohort": dict(
                    Counter(
                        row.asset.role for row in batch.queries if row.match is not None
                    )
                ),
                "outcomes": counts_by_outcome(rows),
                "shared_source_outcomes_by_prior_exposure": {
                    name: counts_by_outcome(
                        [
                            row
                            for row in rows
                            if row["expected_reference"]
                            and row["previously_seen_source"] == seen
                        ]
                    )
                    for name, seen in (("previously_seen", True), ("new", False))
                },
            },
            "review": {
                "reviewed_pairs": len(reviews),
                "by_reason": review_counts(reviews),
                "method": "normalized_waveform_correlation",
                "sample_rate": waveform_review.SAMPLE_RATE,
                "window_samples": waveform_review.WINDOW_SAMPLES,
                "min_correlation": waveform_review.MIN_CORRELATION,
                "min_peak_margin": waveform_review.PEAK_MARGIN,
                "min_competing_peak_distance_samples": waveform_review.COMPETING_PEAK_DISTANCE,
                "max_lag_delta_samples": waveform_review.MAX_LAG_DELTA,
                "min_aligned_windows": waveform_review.MIN_WINDOWS,
                "min_rms": waveform_review.MIN_RMS,
                "matcher_offset_tolerance_seconds": OFFSET_TOLERANCE_SECONDS,
                "max_extra_rejected_per_cohort": REJECTED_PER_COHORT,
            },
            "environment": run_info(),
        }
        write_json(out / "summary.json", summary)
    return summary
