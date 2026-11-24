import csv
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from echo.artifacts import sha256_file
from echo.cli import main
from echo.datasets import ESC50_REVISION, Asset, write_manifest
from echo.experiment_metrics import paired_metrics

SPEC = {
    "schema_version": 1,
    "selection_seed": 7,
    "max_crops_per_class": 1,
    "crop_seconds": 3,
    "calibration_seed": 11,
    "paired_seeds": [13, 17, 19],
    "learning_rates": [0.001],
    "epochs": 1,
    "batch_size": 8,
    "cpu_threads": 1,
}


def test_paired_metrics_count_each_direction_and_use_slice_support():
    expected = np.array([0, 0, 1, 1])
    comparison = np.array([0, 0, 0, 1])
    exposed = np.array([1, 0, 1, 1])
    result = paired_metrics(expected, comparison, exposed)
    assert result["delta_accuracy_pp"] == 0
    assert result["comparison_wrong_exposed_right"] == 1
    assert result["comparison_right_exposed_wrong"] == 1
    assert result["comparison"]["macro_f1"] == pytest.approx((4 / 5 + 2 / 3) / 2)


def test_cpu_cli_keeps_identical_ordered_test_files_and_update_counts(tmp_path):
    pytest.importorskip("torch")
    root = tmp_path / "audio"
    root.mkdir()
    time = np.arange(40_000) / 8000
    assets = []
    for label, frequency in (("chirp", 400), ("tone", 1000)):
        for fold in ("1", "1", "2", "3", "3", "4"):
            index = len(assets)
            name = f"{index}.wav"
            sf.write(
                root / name, 0.3 * np.sin(2 * np.pi * (frequency + index) * time), 8000
            )
            assets.append(
                Asset(
                    name,
                    "esc50",
                    ESC50_REVISION,
                    name,
                    "source",
                    "freesound",
                    str(index),
                    label,
                    fold,
                    sha256_file(root / name),
                )
            )
    inventory = tmp_path / "inventory.csv"
    spec = tmp_path / "spec.json"
    design = tmp_path / "design"
    smoke = tmp_path / "smoke"
    calibration = tmp_path / "calibration"
    results = tmp_path / "result"
    write_manifest(inventory, assets)
    spec.write_text(json.dumps(SPEC))
    inputs = ["--inventory", str(inventory), "--esc-root", str(root)]
    designed = [*inputs, "--design", str(design)]

    def run(mode: str, out: Path, arguments: list[str]) -> int:
        return main(["experiment", mode, *arguments, "--out", str(out)])

    assert run("prepare", design, [*inputs, "--spec", str(spec)]) == 0
    assert run("smoke", smoke, designed) == 0
    assert json.loads((smoke / "smoke.json").read_text())["deterministic_replay"]
    assert run("calibrate", calibration, designed) == 0
    arguments = [*designed, "--calibration", str(calibration / "calibration.json")]
    assert run("run", results, arguments) == 0

    summary = json.loads((results / "summary.json").read_text())
    assert summary["train_examples_per_arm"] == 6
    assert summary["slices"]["all"]["test_rows"] == 4
    assert summary["slices"]["directly_exposed"]["test_rows"] == 2
    assert summary["slices"]["unexposed"]["test_rows"] == 2
    for seed in summary["per_seed"]:
        assert {arm["optimizer_updates"] for arm in seed["arms"].values()} == {1}
        assert {arm["test_manifest_sha256"] for arm in seed["arms"].values()} == {
            summary["test_manifest_sha256"]
        }
    with (results / "predictions.csv").open() as file:
        predictions = list(csv.DictReader(file))
    expected = sorted((a.asset_id, a.label, a.sha256) for a in assets if a.fold == "1")
    for seed in SPEC["paired_seeds"]:
        assert [
            (row["asset_id"], row["label"], row["wav_sha256"])
            for row in predictions
            if int(row["seed"]) == seed
        ] == expected

    recipe_path = calibration / "calibration.json"
    recipe = json.loads(recipe_path.read_text())
    recipe["learning_rate"] = 0.003
    recipe_path.write_text(json.dumps(recipe))
    rejected = tmp_path / "must_not_score"
    assert run("run", rejected, arguments) == 1
    assert not rejected.exists()
