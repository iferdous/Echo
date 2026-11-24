import csv
import json

import numpy as np
import pytest
import soundfile as sf

from echo.artifacts import sha256_file
from echo.datasets import Asset, write_manifest
from echo.evaluation import calibrate, evaluate_test, read_design
from echo.evaluation_data import VARIANTS, prepare
from echo.evaluation_metrics import match_counts, source_group_metrics


def test_counts_distinguish_wrong_accepts_and_repeated_recording_groups():
    rows = [
        {
            "kind": "positive",
            "source_id": "a",
            "decision": "matched",
            "expected_rank": 1,
        },
        {
            "kind": "positive",
            "source_id": "a",
            "decision": "matched",
            "expected_rank": 2,
        },
        {
            "kind": "positive",
            "source_id": "b",
            "decision": "no_match",
            "expected_rank": 1,
        },
        {
            "kind": "absent",
            "source_id": "c",
            "decision": "matched",
            "expected_rank": None,
        },
        {
            "kind": "absent",
            "source_id": "c",
            "decision": "matched",
            "expected_rank": None,
        },
        {
            "kind": "absent",
            "source_id": "d",
            "decision": "no_match",
            "expected_rank": None,
        },
    ]
    counts = match_counts(rows)
    assert counts["top_1"] == 2
    assert counts["top_5"] == 3
    assert counts["correct_accepts"] == counts["incorrect_accepts"] == 1
    assert counts["positive_abstentions"] == 1
    assert counts["false_accepts"] == 2
    groups = source_group_metrics(rows)
    assert groups["mean_correct_accept_rate_by_positive_group"] == 0.25
    assert groups["absent_source_groups"] == 2
    assert groups["absent_groups_with_a_false_accept"] == 1


def test_calibration_and_holdout_use_frozen_manifest_and_policy(tmp_path, monkeypatch):
    monkeypatch.setattr("echo.evaluation_data.STRATA", {"example": ("dog",)})
    monkeypatch.setattr("echo.evaluation_data.VARIANTS", VARIANTS[:1])
    root = tmp_path / "corpus"
    root.mkdir()
    rows = []
    rate = 16_000
    time = np.arange(5 * rate) / rate
    for i in range(4):
        source = str(i + 1)
        name = source + ".wav"
        envelope = 0.1 + 0.2 * np.sin(2 * np.pi * (2.4 + 2 * i) * time) ** 4
        signal = envelope * np.random.default_rng(i).standard_normal(time.size)
        sf.write(root / name, signal, rate, subtype="PCM_16")
        rows.append(
            Asset(
                f"id-{i}",
                "esc50",
                "fixture",
                name,
                "source",
                "freesound",
                source,
                "dog",
                sha256=sha256_file(root / name),
            )
        )
    manifest = root / "inventory.csv"
    write_manifest(manifest, rows)
    development = tmp_path / "development"
    development.mkdir()
    write_manifest(development / "index.csv", [])
    (development / "queries.csv").write_text("source_id\n")
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "seed": 11,
                "groups_per_label_and_kind": 1,
                "background_references_per_split": 0,
            }
        )
    )

    frozen = tmp_path / "design"
    prepare(root, manifest, development, spec, frozen)
    _, partitions = read_design(frozen)
    assert partitions["calibration"].source_ids.isdisjoint(
        partitions["test"].source_ids
    )
    calibration = tmp_path / "calibration"
    report = calibrate(root, frozen, calibration)
    assert report["metrics"]["match"]["correct_accepts"] == 1
    test_run = tmp_path / "test"
    report = evaluate_test(root, frozen, calibration, test_run)
    assert report["metrics"]["match"]["correct_accepts"] == 1
    assert report["metrics"]["match"]["false_accepts"] == 0
    assert report["metrics"]["baselines"]["bytes"]["correct_top_1"] == 1
    with (test_run / "results.csv").open(newline="") as file:
        assert len(list(csv.DictReader(file))) == 2

    policy = calibration / "policy.json"
    policy.write_text('{"min_support": 999}')
    with pytest.raises(ValueError, match="has changed"):
        evaluate_test(root, frozen, calibration, tmp_path / "tampered")
    queries = frozen / "test/queries.csv"
    queries.write_text(queries.read_text() + "\n")
    with pytest.raises(ValueError, match="differs from the frozen design"):
        read_design(frozen)
