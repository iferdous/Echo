"""Matcher counts and recording-group uncertainty for a fixed cohort."""

from collections import defaultdict
from math import sqrt
from random import Random
from statistics import mean, median, quantiles


def interval_any_false_accept(count: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    rate = count / total
    denominator = 1 + z**2 / total
    center = (rate + z**2 / (2 * total)) / denominator
    span = z * sqrt(rate * (1 - rate) / total + z**2 / (4 * total**2)) / denominator
    return [round(max(0.0, center - span), 6), round(min(1.0, center + span), 6)]


def distributions(values: list[float]) -> dict:
    result = {"n": len(values), "p50": None, "p95": None, "max": None}
    if values:
        result["p50"] = round(median(values), 6)
        result["p95"] = (
            round(quantiles(values, n=20, method="inclusive")[18], 6)
            if len(values) > 1
            else values[0]
        )
        result["max"] = round(max(values), 6)
    return result


def match_counts(rows: list[dict]) -> dict:
    positives = [row for row in rows if row["kind"] == "positive"]
    absent = [row for row in rows if row["kind"] == "absent"]
    return {
        "positives": len(positives),
        "top_1": sum(row["expected_rank"] == 1 for row in positives),
        "top_5": sum(row["expected_rank"] is not None for row in positives),
        "correct_accepts": sum(
            row["expected_rank"] == 1 and row["decision"] == "matched"
            for row in positives
        ),
        "incorrect_accepts": sum(
            row["expected_rank"] != 1 and row["decision"] == "matched"
            for row in positives
        ),
        "positive_abstentions": sum(row["decision"] != "matched" for row in positives),
        "absent": len(absent),
        "false_accepts": sum(row["decision"] == "matched" for row in absent),
        "insufficient_evidence": sum(
            row["decision"] == "insufficient_evidence" for row in rows
        ),
    }


def source_group_metrics(rows: list[dict]) -> dict:
    matches = defaultdict(list)
    absent = defaultdict(list)
    for row in rows:
        if row["kind"] == "positive":
            matches[row["source_id"]].append(
                row["decision"] == "matched" and row["expected_rank"] == 1
            )
        else:
            absent[row["source_id"]].append(row["decision"] == "matched")
    means = [mean(group) for _, group in sorted(matches.items())]
    bootstrap = None
    if len(means) > 1:
        rng = Random(5031)
        estimates = sorted(mean(rng.choices(means, k=len(means))) for _ in range(1500))
        bootstrap = [round(estimates[37], 6), round(estimates[1462], 6)]
    false_groups = sum(any(group) for group in absent.values())
    return {
        "positive_source_groups": len(matches),
        "mean_correct_accept_rate_by_positive_group": round(mean(means), 6)
        if means
        else None,
        "positive_group_bootstrap_95": bootstrap,
        "absent_source_groups": len(absent),
        "absent_groups_with_a_false_accept": false_groups,
        "absent_group_wilson_95": interval_any_false_accept(false_groups, len(absent)),
    }


def baseline_metrics(rows: list[dict], name: str) -> dict:
    valid = [row for row in rows if row[f"{name}_status"] != "unavailable"]
    positives = [row for row in valid if row["kind"] == "positive"]
    negatives = [row for row in valid if row["kind"] == "absent"]
    return {
        "available": len(valid),
        "unavailable": len(rows) - len(valid),
        "positive_queries": len(positives),
        "correct_top_1": sum(row[f"{name}_rank"] == 1 for row in positives),
        "absent_queries": len(negatives),
        "accepted_absent": sum(row[f"{name}_status"] == "matched" for row in negatives),
    }


def summarize(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["decision"] not in {"excluded", "input_error"}]
    return {
        "planned_queries": len(rows),
        "excluded": sum(row["decision"] == "excluded" for row in rows),
        "input_errors": sum(row["decision"] == "input_error" for row in rows),
        "valid_queries": len(valid),
        "match": match_counts(valid),
        "source_groups": source_group_metrics(valid),
        "variants": {
            variant: match_counts([row for row in valid if row["variant"] == variant])
            for variant in sorted({row["variant"] for row in rows})
        },
        "id_visibility": {
            mode: match_counts([row for row in valid if row["id_visibility"] == mode])
            for mode in ("visible", "masked")
        },
        "baselines": {
            name: baseline_metrics(valid, name) for name in ("bytes", "source")
        },
        "matched_offset_error_ms": distributions(
            [
                row["offset_error_ms"]
                for row in valid
                if row["offset_error_ms"] is not None
            ]
        ),
        "query_ms": {
            stage: distributions([row[stage] for row in valid])
            for stage in ("decode_ms", "fingerprint_ms", "ranking_ms", "total_ms")
        },
    }
