import json
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf

from echo.artifacts import sha256_file
from echo.datasets import ESC50_REVISION, Asset, write_manifest
from echo.experiment_data import (
    make_plan,
    prepare_design,
    read_experiment_design,
    split_validation,
)

SPEC = {
    "schema_version": 1,
    "selection_seed": 1,
    "max_crops_per_class": 1,
    "crop_seconds": 3,
    "calibration_seed": 2,
    "paired_seeds": [3, 4, 5],
    "learning_rates": [0.001],
    "epochs": 1,
    "batch_size": 4,
    "cpu_threads": 1,
}


def test_group_precedence_and_frozen_pcm_exposure(tmp_path):
    assets = []
    root = tmp_path / "audio"
    root.mkdir()
    for number, (fold, source) in enumerate(
        (
            ("1", "10"),
            ("1", "11"),
            ("2", "20"),
            ("3", "20"),
            ("3", "30"),
            ("4", "40"),
            ("4", "41"),
        )
    ):
        name = f"{number}.wav"
        samples = np.arange(4000, dtype=np.int16) + number
        # Four seconds of known, different PCM for each source.
        sf.write(root / name, np.tile(samples, 8), 8000, subtype="PCM_16")
        assets.append(
            Asset(
                name,
                "esc50",
                ESC50_REVISION,
                name,
                "source",
                "freesound",
                source,
                "test_label",
                fold,
                sha256_file(root / name),
            )
        )
    inventory, spec, out = (
        tmp_path / "inventory.csv",
        tmp_path / "spec.json",
        tmp_path / "design",
    )
    write_manifest(inventory, assets)
    spec.write_text(json.dumps(SPEC))
    prepare_design(inventory, root, spec, out)
    design = read_experiment_design(out, inventory)
    assert design.splits.exclusions[0]["reason"] == "precedence_validation"
    crop = design.crops["exposed"][0]
    asset = next(a for a in assets if a.asset_id == crop.original_id)
    original, _ = sf.read(root / asset.path, dtype="int16")
    stored, _ = sf.read(out / crop.path, dtype="int16")
    np.testing.assert_equal(stored, original[4000:28000])
    assert (crop.start_sample, crop.frames) == (4000, 24000)
    assert (
        design.metadata["validation"]["confirmation"]["comparison_train_test_groups"]
        == []
    )
    groups = design.splits.groups
    base = {groups[a.asset_id] for a in design.splits.assets["train_base"]}
    assert design.crops["comparison"][0].group not in base

    # A different source ID with identical bytes inherits the test role.
    clone = replace(assets[-1], sha256=assets[0].sha256)
    regrouped = make_plan([*assets[:-1], clone], design.spec)
    assert any(
        entry["asset_id"] == clone.asset_id and entry["reason"] == "precedence_test"
        for entry in regrouped.exclusions
    )
    split_validation(regrouped)

    with (out / "test.csv").open("a", encoding="utf-8") as file:
        file.write("\n")
    with pytest.raises(ValueError, match="frozen checksums"):
        read_experiment_design(out, inventory)
