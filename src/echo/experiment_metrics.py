"""Paired accuracy, class metrics, and test-recording bootstrap intervals."""

from collections import defaultdict

import numpy as np

BOOTSTRAP_SEED = 500903
BOOTSTRAP_REPETITIONS = 10_000
SLICES = ("all", "directly_exposed", "unexposed")


def metrics(expected: np.ndarray, predictions: np.ndarray) -> dict:
    n = len(expected)
    if not n:
        return {"rows": 0, "correct": 0, "accuracy": None, "macro_f1": None}
    f1 = []
    for label in np.unique(expected):
        actual = expected == label
        predicted = predictions == label
        f1.append(
            2 * int((actual & predicted).sum()) / int(actual.sum() + predicted.sum())
        )
    correct = int((expected == predictions).sum())
    return {
        "rows": n,
        "correct": correct,
        "accuracy": correct / n,
        "macro_f1": float(np.mean(f1)),
    }


def paired_metrics(
    expected: np.ndarray, comparison: np.ndarray, exposed: np.ndarray
) -> dict:
    first = metrics(expected, comparison)
    second = metrics(expected, exposed)
    a = expected == comparison
    b = expected == exposed
    return {
        "comparison": first,
        "exposed": second,
        "delta_accuracy_pp": 100 * (second["accuracy"] - first["accuracy"])
        if len(expected)
        else None,
        "delta_macro_f1_pp": 100 * (second["macro_f1"] - first["macro_f1"])
        if len(expected)
        else None,
        "comparison_wrong_exposed_right": int((~a & b).sum()),
        "comparison_right_exposed_wrong": int((a & ~b).sum()),
    }


def masks(direct: np.ndarray) -> dict[str, np.ndarray]:
    return dict(
        zip(SLICES, (np.ones(len(direct), dtype=bool), direct, ~direct), strict=True)
    )


def group_bootstrap(delta_by_seed: np.ndarray, groups: list[str]) -> dict:
    rows_by_group = defaultdict(list)
    for row, group in enumerate(groups):
        rows_by_group[group].append(row)
    counts = np.array([len(rows) for rows in rows_by_group.values()])
    totals = np.array(
        [delta_by_seed[:, rows].mean(axis=0).sum() for rows in rows_by_group.values()]
    )
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    reps = []
    for start in range(0, BOOTSTRAP_REPETITIONS, 512):
        number = min(512, BOOTSTRAP_REPETITIONS - start)
        select = rng.integers(0, len(counts), size=(number, len(counts)))
        reps.extend(100 * totals[select].sum(axis=1) / counts[select].sum(axis=1))
    return {
        "conditional_on_trained_models": True,
        "test_source_groups": len(counts),
        "replicates": BOOTSTRAP_REPETITIONS,
        "seed": BOOTSTRAP_SEED,
        "percentile_95_interval_accuracy_pp": np.percentile(reps, [2.5, 97.5]).tolist(),
    }
