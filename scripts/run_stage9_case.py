"""Replay a release review of a real ESC-50/FSD50K evaluation cohort."""

import argparse
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from plot_stage9_case import plot_case

from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.batch import scan_manifest, write_batch
from echo.datasets import read_manifest, write_manifest
from echo.evidence import identity_digest, published_evidence, require
from echo.evidence_metrics import BATCH_IDENTITY, audit_metrics
from echo.matcher import read_policy, resolve_alignment_engine
from echo.review import read_evidence

REPO = Path(__file__).resolve().parents[1]
CASE = Path("docs/results/stage-9-case")
CONFIRMED = {
    "confirmed_audio_matched",
    "confirmed_audio_offset_disagreement",
    "confirmed_audio_matcher_miss",
}
UNRESOLVED = {"same_source_audio_unresolved", "control_accepted_audio_unresolved"}
EXAMPLES = ("4-207124-A-0.wav", "4-188033-A-38.wav", "1-14262-A-37.wav")


def triage(queries):
    confirmed_sources = {
        row["query_source_id"] for row in queries if row["outcome"] in CONFIRMED
    }
    for row in queries:
        outcome = row["outcome"]
        if outcome in CONFIRMED:
            action, reason = "quarantine", "waveform_confirmed"
        elif row["query_source_id"] in confirmed_sources:
            action, reason = "quarantine", "confirmed_source_group"
        elif outcome in UNRESOLVED:
            action, reason = "hold", outcome
        else:
            require(outcome == "control_not_accepted", f"unexpected outcome: {outcome}")
            action, reason = "retain", "control_declined"
        yield {
            "query_id": row["query_id"],
            "label": row["query_label"],
            "source_id": row["query_source_id"],
            "source_url": row["query_source_url"],
            "matcher_decision": row["matcher_decision"],
            "top_reference": row["top_reference"],
            "matcher_offset_seconds": row["top_offset_seconds"],
            "review_outcome": outcome,
            "release_action": action,
            "release_reason": reason,
        }


def validate_recheck(source, before, manifest, path):
    recheck, actual_queries, ranks = read_evidence(path)
    retained_ids = {row.asset_id for row in read_manifest(manifest)}
    actual_candidates = [
        candidate for row in actual_queries for candidate in ranks[row["query_id"]]
    ]
    expected_queries = [
        row
        for row in source.rows("results/stage-4-batch-queries.csv")
        if row["query_id"] in retained_ids
    ]
    expected_candidates = [
        row
        for row in source.rows("results/stage-4-candidates.csv")
        if row["query_id"] in retained_ids
    ]
    for rows in (
        actual_queries,
        expected_queries,
        actual_candidates,
        expected_candidates,
    ):
        for row in rows:
            del row["run_id"]
            row.pop("elapsed_ms", None)
    require(
        recheck["query_manifest_sha256"] == sha256_file(manifest)
        and identity_digest({key: recheck[key] for key in BATCH_IDENTITY})
        == recheck["run_id"]
        and all(
            recheck[key] == before[key]
            for key in BATCH_IDENTITY
            if key != "query_manifest_sha256"
        )
        and actual_queries == expected_queries
        and actual_candidates == expected_candidates
        and len(actual_queries) == len(retained_ids),
        "release recheck disagrees with the frozen settings, decisions, or candidate rankings",
    )
    return {
        "audit": recheck,
        "query_rows_excluding_elapsed_identity_sha256": identity_digest(actual_queries),
        "candidate_rows_identity_sha256": identity_digest(actual_candidates),
    }


def run(args):
    source = published_evidence(args.repo)
    audit_metrics(source)
    summary = source.json("results/stage-4-summary.json")
    before = summary["batch"]
    queries = source.rows("results/stage-4-audit-queries.csv")
    assets = read_manifest(args.repo / "docs/results/stage-4-query-manifest.csv")
    references = source.rows("results/stage-4-index-manifest.csv")
    reviews = {
        (row["query_id"], row["reference_id"]): row
        for row in source.rows("results/stage-4-reviews.csv")
    }
    require(
        [(row["query_id"], row["query_source_id"]) for row in queries]
        == [(asset.asset_id, asset.source_id) for asset in assets],
        "the review rows do not match the frozen query manifest",
    )
    release_rows = list(triage(queries))
    retained = [
        asset
        for row, asset in zip(release_rows, assets, strict=True)
        if row["release_action"] == "retain"
    ]
    reference_hashes = {row["sha256"] for row in references}
    reference_sources = {row["source_id"] for row in references}
    dispositions = Counter(row["release_action"] for row in release_rows)
    reasons = Counter(row["release_reason"] for row in release_rows)
    examples = []
    release_by_query = {row["query_id"]: row for row in release_rows}
    for name in EXAMPLES:
        row = release_by_query[f"esc50:{name}"]
        review = reviews[(row["query_id"], row["top_reference"])]
        examples.append(
            {
                **row,
                **{
                    f"waveform_{key}": review[key]
                    for key in (
                        "verdict",
                        "offset_seconds",
                        "query_start_seconds",
                        "query_end_seconds",
                        "aligned_windows",
                        "best_correlation",
                        "median_aligned_correlation",
                    )
                },
                "reference_source_url": review["reference_source_url"],
                "reference_license": review["reference_license"],
            }
        )
    example = source.json("results/stage-4-example.json")
    matched = example["replayed_cli_output"]["candidates"][0]
    require(
        matched["asset_id"] == examples[0]["top_reference"],
        "the example replay differs from the audit",
    )
    examples[0]["matcher_query_interval_seconds"] = matched["query_span_seconds"]
    examples[0]["matcher_reference_interval_seconds"] = matched[
        "reference_span_seconds"
    ]
    with new_output_directory(args.out):
        manifest = args.out / "proposed-test.csv"
        write_manifest(manifest, retained)
        write_csv(args.out / "triage.csv", release_rows[0], release_rows)
        result = {
            "schema_version": 1,
            "source_evidence_id": source.run_id,
            "initial_audit": before,
            "baseline": {
                "exact_sha256_shared_rows": sum(
                    a.sha256 in reference_hashes for a in assets
                ),
                "source_id_shared_rows": sum(
                    a.source_id in reference_sources for a in assets
                ),
                "waveform_confirmed_rows": reasons["waveform_confirmed"],
            },
            "release_actions": dict(dispositions),
            "release_reasons": dict(reasons),
            "retained_manifest_sha256": sha256_file(manifest),
            "labels": {
                "original": dict(Counter(asset.label for asset in assets)),
                "retained": dict(Counter(asset.label for asset in retained)),
            },
            "examples": examples,
        }
        if args.index is not None:
            replay = scan_manifest(
                manifest,
                args.esc_root,
                args.index,
                read_policy(args.repo / "docs/results/stage-3-policy.json"),
                limit=before["result_limit"],
                reference_manifest_sha256=before["reference_manifest_sha256"],
                aligner=resolve_alignment_engine(args.engine),
            )
            write_batch(replay, args.out / "recheck")
        saved = args.repo / CASE
        if args.index is not None or args.check:
            recheck = saved / "recheck" if args.check else args.out / "recheck"
            result["recheck"] = validate_recheck(source, before, manifest, recheck)
        write_json(args.out / "summary.json", result)
        if "recheck" in result:
            with TemporaryDirectory(dir=args.out) as directory:
                plot_case(result, args.out / "split-review.svg", Path(directory))
        if args.check:
            for name in (
                "proposed-test.csv",
                "triage.csv",
                "summary.json",
                "split-review.svg",
            ):
                require(
                    (saved / name).read_bytes() == (args.out / name).read_bytes(),
                    f"{saved / name}: release case drifted",
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--esc-root", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the published case from saved rows without audio",
    )
    parser.add_argument("--engine", choices=("python", "rust"), default="python")
    args = parser.parse_args()
    if (args.esc_root is None) != (args.index is None):
        parser.error(
            "--esc-root and --index are required together for an audio recheck"
        )
    if args.check and args.index is not None:
        parser.error(
            "--check uses the published recheck and does not take audio inputs"
        )
    try:
        run(args)
        print(f"Stage 9 case evidence saved to {args.out}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"release case: {error}\n")


if __name__ == "__main__":
    main()
