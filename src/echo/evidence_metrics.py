"""Recompute the benchmark metrics from the verified per-query artifacts."""

import json
from collections import Counter, defaultdict
from math import isclose
from statistics import mean, median, quantiles, stdev

import numpy as np

from echo.evaluation_metrics import summarize
from echo.evidence import Evidence, identity_digest, require, sha256
from echo.experiment_metrics import group_bootstrap, masks, paired_metrics
from echo.matcher import MatchPolicy

BATCH_IDENTITY = (
    "schema_version",
    "query_manifest_sha256",
    "reference_manifest_sha256",
    "fingerprint_config_sha256",
    "match_policy_sha256",
    "indexed_assets",
    "result_limit",
)
MODEL_IDENTITY = (
    "design_sha256",
    "experiment_model_sha256",
    "experiment_runner_sha256",
    "dependency_lock_sha256",
    "checkpoint_rule",
    "calibration_sha256",
    "seeds",
    "test_manifest_sha256",
)


def receipt(evidence: Evidence, file: str) -> dict:
    record = evidence.json(file)
    require(record.get("schema_version") == 1, f"{file}: unsupported evidence schema")
    return record


def check_batch(
    evidence: Evidence, record: dict, queries: str, candidates: str
) -> None:
    require(record["schema_version"] == 1, "unsupported batch audit schema")
    require(
        identity_digest({key: record[key] for key in BATCH_IDENTITY})
        == record["run_id"],
        "audit run ID does not match its declared inputs",
    )
    evidence.check_digest(queries, record["queries_sha256"])
    evidence.check_digest(candidates, record["candidates_sha256"])
    rows = evidence.rows(queries, ("run_id", "query_id", "decision"))
    ranked = evidence.rows(candidates, ("run_id", "query_id", "rank", "accepted"))
    ids = {row["query_id"] for row in rows}
    require(
        len(ids) == len(rows) == record["query_count"]
        and len(ranked) == record["candidate_count"]
        and Counter(row["decision"] for row in rows) == record["decisions"]
        and all(
            row["run_id"] == record["run_id"] and row["query_id"] in ids
            for row in (*rows, *ranked)
        ),
        "audit output rows do not agree with the run receipt",
    )


def fixture_metrics(evidence: Evidence) -> dict:
    recipe = receipt(evidence, "fixture/recipe.json")
    batch = receipt(evidence, "fixture/audit.json")
    check_batch(evidence, batch, "fixture/queries.csv", "fixture/candidates.csv")
    evidence.check_digest("fixture/query-manifest.csv", batch["query_manifest_sha256"])
    evidence.check_digest("fixture/references.csv", batch["reference_manifest_sha256"])
    require(
        MatchPolicy(**recipe["policy"]).digest == batch["match_policy_sha256"],
        "fixture policy disagrees with its batch",
    )
    rows = evidence.rows("fixture/queries.csv")
    require(
        {row["query_id"]: row["decision"] for row in rows} == recipe["expected"],
        "fixture decisions disagree with its recipe",
    )
    crop = next((row for row in rows if row["query_id"] == "crop"), None)
    require(
        crop is not None
        and crop["best_reference"] == recipe["reference_id"]
        and abs(float(crop["offset_seconds"]) - recipe["expected_offset_seconds"])
        <= recipe["offset_tolerance_seconds"],
        "fixture crop does not match its known offset",
    )
    return {
        "audit_run_id": batch["run_id"],
        "expected_offset_seconds": recipe["expected_offset_seconds"],
        "queries": rows,
    }


def development_metrics(evidence: Evidence) -> dict:
    metrics = {}
    for variant in ("global", "local"):
        name = f"results/stage-2-{variant}"
        summary = receipt(evidence, f"{name}-summary.json")
        evidence.check_digest(f"{name}-queries.csv", summary["result_queries_sha256"])
        rows = evidence.rows(
            f"{name}-queries.csv",
            ("query_id", "expected_asset_id", "best_asset_id", "status"),
        )
        positives = [row for row in rows if row["expected_asset_id"]]
        absent = [row for row in rows if not row["expected_asset_id"]]
        check = {
            "positive_queries": len(positives),
            "absent_source_queries": len(absent),
            "correct_top_one": sum(
                row["best_asset_id"] == row["expected_asset_id"] for row in positives
            ),
            "correct_accepted": sum(
                row["best_asset_id"] == row["expected_asset_id"]
                and row["status"] == "matched"
                for row in positives
            ),
            "absent_source_accepted": sum(row["status"] == "matched" for row in absent),
            "backend_agreements": sum(
                row["backend_agreement"] == "True" for row in rows
            ),
        }
        require(
            all(summary["results"][key] == value for key, value in check.items()),
            f"{name}: metrics disagree with saved queries",
        )
        metrics[variant] = {
            **summary["results"],
            "index": summary["index"],
            "source_commit": summary["source_commit"],
        }
    return metrics


def matcher_metrics(evidence: Evidence) -> dict:
    design = receipt(evidence, "results/stage-3-design.json")
    calibration = receipt(evidence, "results/stage-3-calibration.json")
    test = receipt(evidence, "results/stage-3-test-summary.json")
    candidate_policy = MatchPolicy(**evidence.json("results/stage-3-policy.json"))
    for name, expected in (
        ("bench/stage3-spec.json", design["spec_sha256"]),
        ("results/stage-3-calibration.json", test["calibration_sha256"]),
        (
            "results/stage-3-calibration-summary.json",
            calibration["calibration_summary_sha256"],
        ),
    ):
        evidence.check_digest(name, expected)
    require(
        identity_digest(design)
        == calibration["design_sha256"]
        == test["design_sha256"],
        "held-out design content differs from its canonical digest",
    )
    require(
        candidate_policy.digest
        == calibration["policy_sha256"]
        == test["policy_sha256"],
        "held-out results use a different match policy",
    )
    evaluated = {}
    for split in ("calibration", "test"):
        summary = receipt(evidence, f"results/stage-3-{split}-summary.json")
        path = f"results/stage-3-{split}-queries.csv"
        evidence.check_digest(path, summary["results_sha256"])
        rows = evidence.rows(path)
        require(
            len({row["query_id"] for row in rows})
            == len(rows)
            == design["splits"][split]["planned_trials"],
            f"{path}: mismatched trial identity",
        )
        for row in rows:
            for field in ("expected_rank", "bytes_rank", "source_rank"):
                row[field] = int(row[field]) if row[field] else None
            for field in (
                "offset_error_ms",
                "decode_ms",
                "fingerprint_ms",
                "ranking_ms",
                "total_ms",
            ):
                row[field] = float(row[field]) if row[field] else None
        metrics = summarize(rows)
        require(
            metrics == summary["metrics"],
            f"{path}: recomputed matcher statistics disagree with the summary",
        )
        evaluated[split] = metrics
    return {
        **evaluated,
        "name": "stage-3-held-out",
        "summary_sha256": sha256(evidence.payload["results/stage-3-test-summary.json"]),
        "source_commit": test["run"]["source_commit"],
        "policy_sha256": test["policy_sha256"],
    }


def audit_metrics(evidence: Evidence) -> dict:
    summary = receipt(evidence, "results/stage-4-summary.json")
    cohort = receipt(evidence, "results/stage-4-cohort.json")
    acquisition = receipt(evidence, "results/stage-4-acquisition.json")
    batch = summary["batch"]
    for name, expected in (
        ("bench/stage4-spec.json", cohort["spec_sha256"]),
        ("results/stage-3-design.json", cohort["stage3_design_sha256"]),
        ("results/stage-3-calibration.json", summary["calibration_sha256"]),
        ("results/stage-4-cohort.json", summary["cohort_sha256"]),
        ("results/stage-4-cohort.json", acquisition["cohort_sha256"]),
        ("results/stage-4-acquisition.json", summary["acquisition_sha256"]),
        ("results/stage-4-acquisition.csv", acquisition["acquisition_sha256"]),
        ("results/stage-4-reference-manifest.csv", cohort["references_sha256"]),
        ("results/stage-4-index-manifest.csv", acquisition["index_sha256"]),
        ("results/stage-4-index-manifest.csv", batch["reference_manifest_sha256"]),
        ("results/stage-4-query-manifest.csv", cohort["queries_sha256"]),
        ("results/stage-4-query-manifest.csv", batch["query_manifest_sha256"]),
        ("results/stage-4-audit-queries.csv", summary["queries_sha256"]),
        ("results/stage-4-reviews.csv", summary["reviews_sha256"]),
    ):
        evidence.check_digest(name, expected)
    require(
        MatchPolicy(**evidence.json("results/stage-3-policy.json")).digest
        == batch["match_policy_sha256"],
        "audit policy disagrees with its source record",
    )
    check_batch(
        evidence,
        batch,
        "results/stage-4-batch-queries.csv",
        "results/stage-4-candidates.csv",
    )
    queries = evidence.rows("results/stage-4-audit-queries.csv")
    reviews = evidence.rows("results/stage-4-reviews.csv")
    plans = evidence.rows("results/stage-4-query-manifest.csv")
    outcomes = defaultdict(set)
    counts = Counter()
    for row in queries:
        counts[row["outcome"]] += 1
        outcomes[row["outcome"]].add(row["query_source_id"])
    groups = {
        key: {"query_rows": counts[key], "unique_query_sources": len(value)}
        for key, value in outcomes.items()
    }
    by_reason = defaultdict(Counter)
    for row in reviews:
        for reason in row["review_reasons"].split("|"):
            by_reason[reason][row["verdict"]] += 1
    known = by_reason["known_source"]
    require(
        [row["query_id"] for row in queries] == [row["asset_id"] for row in plans]
        and len(queries) == batch["query_count"]
        and len(reviews) == summary["review"]["reviewed_pairs"]
        and groups == summary["coverage"]["outcomes"]
        and by_reason == summary["review"]["by_reason"]
        and known.total() == summary["full_metadata"]["esc50_shared_fsd_eval"]
        and known["confirmed"]
        == sum(
            count for key, count in counts.items() if key.startswith("confirmed_audio_")
        ),
        "cross-dataset coverage and review counts disagree with the recorded evidence",
    )
    if evidence.profile == "full":
        replay = receipt(evidence, "replay/audit.json")
        verification = receipt(evidence, "replay/verification.json")
        check_batch(evidence, replay, "replay/queries.csv", "replay/candidates.csv")
        inventory = receipt(evidence, "results/stage-1-inventory.json")
        classifier = receipt(evidence, "results/stage-5-summary.json")
        profiled_index = receipt(evidence, "results/stage-6/tuned-stage4.json")["index"]
        require(
            verification["audio_sha256_verified"]
            == {
                "esc50": inventory["decoded_assets"],
                "fsd50k_eval": batch["indexed_assets"],
            }
            and verification["historical_classifier_run_id"] == classifier["run_id"]
            and verification["matches_profiled_sqlite_bytes"]
            == (verification["sqlite_sha256"] == profiled_index["sha256"])
            and verification["replay_engine"] in ("python", "rust"),
            "full replay receipt disagrees with the corpus, classifier, or index record",
        )
        require(
            verification["equal_query_rows"]
            == replay["query_count"]
            == batch["query_count"]
            and verification["equal_candidate_rows"]
            == replay["candidate_count"]
            == batch["candidate_count"]
            and verification["audit_run_id"] == replay["run_id"] == batch["run_id"]
            and replay["candidates_sha256"] == batch["candidates_sha256"],
            "full replay is incomplete or belongs to a different audit",
        )
        historical = evidence.rows("results/stage-4-batch-queries.csv")
        replayed = evidence.rows("replay/queries.csv")
        for rows in (replayed, historical):
            for row in rows:
                row.pop("elapsed_ms")
        require(
            replayed == historical,
            "full replay changed an audit decision or the best candidate",
        )
    return {
        "run_id": batch["run_id"],
        "queries": batch["query_count"],
        "references": batch["indexed_assets"],
        "known_source_confirmed": known["confirmed"],
        "eligible_known_source_pairs": known.total(),
        "outcomes": groups,
        "decisions": batch["decisions"],
        "reviewed_pairs": len(reviews),
        "full_metadata": summary["full_metadata"],
        "queried_by_cohort": summary["coverage"]["queried_by_cohort"],
        "indexed_references_by_cohort": summary["coverage"][
            "indexed_references_by_cohort"
        ],
        "review": summary["review"],
    }


def model_metrics(evidence: Evidence) -> dict:
    summary = receipt(evidence, "results/stage-5-summary.json")
    design = receipt(evidence, "results/stage-5-design/design.json")
    verification = receipt(evidence, "results/stage-5-verification.json")
    for file, expected in (
        ("results/stage-5-summary.json", verification["summary_sha256"]),
        ("results/stage-5-design/design.json", summary["design_sha256"]),
        ("results/stage-5-calibration.json", summary["calibration_sha256"]),
        ("results/stage-5-design/test.csv", summary["test_manifest_sha256"]),
        ("bench/stage5-spec.json", design["spec_sha256"]),
        *(
            (f"results/stage-5-design/{name}", digest)
            for name, digest in design["files"].items()
        ),
    ):
        evidence.check_digest(file, expected)
    for name, file in (
        ("per_class.csv", "per-class"),
        ("predictions.csv", "predictions"),
        ("training.csv", "training"),
    ):
        evidence.check_digest(f"results/stage-5-{file}.csv", summary["files"][name])
    run_id = sha256(
        json.dumps(
            {key: summary[key] for key in MODEL_IDENTITY}, sort_keys=True
        ).encode()
    )
    require(
        run_id == summary["run_id"] == verification["run_id"],
        "classifier run ID disagrees with its frozen inputs",
    )
    require(
        design["validation"] == summary["split_validation"],
        "classifier split assertions disagree with its design",
    )

    test = evidence.rows("results/stage-5-design/test.csv")
    predictions = evidence.rows("results/stage-5-predictions.csv")
    row_ids = [(row["asset_id"], row["label"], row["sha256"]) for row in test]
    by_seed = defaultdict(list)
    for row in predictions:
        require(row["run_id"] == run_id, "prediction row belongs to a different run")
        by_seed[int(row["seed"])].append(row)
    require(
        list(by_seed)
        == summary["seeds"]
        == [record["seed"] for record in summary["per_seed"]],
        "paired seed order disagrees with the run",
    )
    direct_assets = {
        row["original_id"]
        for row in evidence.rows("results/stage-5-design/crops.csv")
        if row["arm"] == "exposed"
    }
    direct = np.array([row["asset_id"] in direct_assets for row in test])
    expected = np.array([row["label"] for row in test])
    slices = masks(direct)
    groups = [row["recording_group"] for row in next(iter(by_seed.values()))]
    results = []
    deltas = []
    for record in summary["per_seed"]:
        seed = record["seed"]
        rows = by_seed[seed]
        require(
            [(row["asset_id"], row["label"], row["wav_sha256"]) for row in rows]
            == row_ids
            and [int(row["row"]) for row in rows] == list(range(len(test)))
            and [row["directly_exposed"] == "True" for row in rows] == direct.tolist()
            and [row["recording_group"] for row in rows] == groups,
            f"seed {seed}: predictions disagree with its fixed test set",
        )
        comparison = np.array([row["comparison_prediction"] for row in rows])
        exposed = np.array([row["exposed_prediction"] for row in rows])
        scores = {
            name: paired_metrics(
                expected[selected], comparison[selected], exposed[selected]
            )
            for name, selected in slices.items()
        }
        require(
            scores == record["metrics"],
            f"seed {seed}: saved paired results disagree with predictions",
        )
        deltas.append((exposed == expected).astype(np.int8) - (comparison == expected))
        results.append({"seed": seed, **scores})
    for name, selected in slices.items():
        stats = summary["slices"][name]
        pairs = [row[name] for row in results]
        differences = [pair["delta_accuracy_pp"] for pair in pairs]
        recomputed = {
            "test_rows": int(selected.sum()),
            "comparison_mean_accuracy": mean(
                pair["comparison"]["accuracy"] for pair in pairs
            ),
            "exposed_mean_accuracy": mean(
                pair["exposed"]["accuracy"] for pair in pairs
            ),
            "comparison_mean_macro_f1": mean(
                pair["comparison"]["macro_f1"] for pair in pairs
            ),
            "exposed_mean_macro_f1": mean(
                pair["exposed"]["macro_f1"] for pair in pairs
            ),
            "mean_delta_accuracy_pp": mean(differences),
            "min_delta_accuracy_pp": min(differences),
            "max_delta_accuracy_pp": max(differences),
            "sample_sd_delta_accuracy_pp": stdev(differences),
        }
        ci = group_bootstrap(
            np.asarray(deltas)[:, selected],
            [group for group, keep in zip(groups, selected, strict=True) if keep],
        )
        require(
            all(isclose(stats[key], value) for key, value in recomputed.items())
            and np.allclose(
                stats["paired_test_source_bootstrap"][
                    "percentile_95_interval_accuracy_pp"
                ],
                ci["percentile_95_interval_accuracy_pp"],
            ),
            f"{name}: saved classifier statistics disagree with paired predictions",
        )
    return {
        "run_id": run_id,
        "slices": summary["slices"],
        "seeds": results,
        "split_validation": design["validation"],
    }


def timing_metrics(evidence: Evidence) -> dict:
    receipt_path = "results/stage-6/comparison.json"
    comparison = receipt(evidence, receipt_path)
    for file, digest in comparison["artifacts_sha256"].items():
        evidence.check_digest(f"results/stage-6/{file}", digest)
    results = {}
    for stage in ("stage2", "stage4"):
        by_engine = {}
        for engine in ("baseline", "tuned", "rust"):
            prefix = f"results/stage-6/{engine}-{stage}"
            summary = receipt(evidence, f"{prefix}.json")
            evidence.check_digest(f"{prefix}.csv", summary["queries_sha256"])
            evidence.check_digest(
                f"bench/stage6-{stage}-queries.csv",
                summary["input_query_manifest_sha256"],
            )
            csv = evidence.rows(f"{prefix}.csv")
            latency = {}
            for condition in ("warm_connection", "fresh_connection"):
                times = [
                    int(row["total_ns"]) / 1e6
                    for row in csv
                    if row["condition"] == condition
                ]
                measured = summary["measurements"][condition]
                p50, p95 = (
                    median(times),
                    quantiles(times, n=100, method="inclusive")[94],
                )
                actual = measured["latency"]["total_ns"]
                require(
                    len(times) == measured["observations"]
                    and isclose(p50, actual["p50_ms"])
                    and isclose(p95, actual["p95_ms"]),
                    f"{prefix}: raw samples do not reproduce the latency summary",
                )
                latency[condition] = {"count": len(times), "p50_ms": p50, "p95_ms": p95}
            phases = (
                "decode_ns",
                "spectral_peaks_ns",
                "pair_hashes_ns",
                "retrieve_ns",
                "vote_rank_decide_ns",
            )
            warm = [row for row in csv if row["condition"] == "warm_connection"]
            phase_medians = {
                name: median([int(row[name]) / 1e6 for row in warm]) for name in phases
            }
            require(
                all(
                    isclose(
                        value,
                        summary["measurements"]["warm_connection"]["latency"][name][
                            "p50_ms"
                        ],
                    )
                    for name, value in phase_medians.items()
                ),
                f"{prefix}: raw samples do not reproduce the phase medians",
            )
            by_engine[engine] = {
                "warm_phase_medians_ms": phase_medians,
                **latency,
                "peak_rss_bytes": summary["environment"][
                    "peak_whole_process_rss_bytes"
                ],
            }
        tuned, rust = (
            by_engine[engine]["warm_connection"] for engine in ("tuned", "rust")
        )
        decrease = 100 * (1 - rust["p50_ms"] / tuned["p50_ms"])
        record = comparison["workloads"][stage]
        require(
            isclose(decrease, record["warm_median_reduction_percent"]),
            f"{stage}: Rust timing claim disagrees with raw samples",
        )
        build = receipt(evidence, f"results/stage-6/build-{stage}.json")
        evidence.check_digest(
            f"results/stage-6/build-{stage}.csv", build["builds_sha256"]
        )
        results[stage] = {
            "workload": record["workload"],
            "engines": by_engine,
            "warm_median_reduction_percent": decrease,
            "build": build,
        }
    return results


def aggregate(evidence: Evidence) -> dict:
    result = {
        "schema_version": 1,
        "profile": evidence.profile,
        "run_id": evidence.run_id,
    }
    if evidence.profile == "fixture":
        result["fixture"] = fixture_metrics(evidence)
    else:
        result.update(
            metadata=receipt(evidence, "results/stage-1-overlap.json"),
            development=development_metrics(evidence),
            matcher=matcher_metrics(evidence),
            audit=audit_metrics(evidence),
            classifier=model_metrics(evidence),
            timing=timing_metrics(evidence),
        )
        if evidence.profile == "full":
            result["local_replay"] = receipt(evidence, "replay/verification.json")
    return result
