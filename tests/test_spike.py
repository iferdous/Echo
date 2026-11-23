import csv
from dataclasses import replace

import numpy as np
import soundfile as sf

from echo.artifacts import sha256_file
from echo.cli import main
from echo.datasets import Asset, read_manifest, write_manifest
from echo.spike import STRATA


def test_cli_spike_is_repeatable_and_negative_sources_are_absent(tmp_path):
    data = tmp_path / "esc50"
    audio_root = data / "audio"
    audio_root.mkdir(parents=True)
    sample_rate = 8_000
    time = np.arange(5 * sample_rate) / sample_rate
    assets = []
    for label in (label for labels in STRATA.values() for label in labels):
        for _ in range(3):
            source = str(len(assets) + 1)
            path = audio_root / f"{source}.wav"
            sf.write(
                path,
                0.4 * np.sin(2 * np.pi * (100 + 7 * int(source)) * time),
                sample_rate,
            )
            assets.append(
                Asset(
                    f"esc50:{source}",
                    "esc50",
                    "test",
                    f"audio/{source}.wav",
                    "source",
                    "freesound",
                    source,
                    label,
                    sha256=sha256_file(path),
                )
            )

    manifest = tmp_path / "assets.csv"
    write_manifest(manifest, assets)
    base = [
        "data",
        "spike",
        "--esc50",
        str(data),
        "--inventory",
        str(manifest),
        "--index-size",
        "40",
    ]
    out = tmp_path / "first"
    assert main([*base, "--out", str(out)]) == 0
    again = tmp_path / "again"
    write_manifest(manifest, reversed(assets))
    assert main([*base, "--out", str(again)]) == 0
    for name in ("queries.csv", "index.csv"):
        assert (out / name).read_bytes() == (again / name).read_bytes()

    index = {asset.asset_id: asset for asset in read_manifest(out / "index.csv")}
    indexed_sources = {asset.source_id for asset in index.values()}
    by_id = {asset.asset_id: asset for asset in assets}
    with (out / "queries.csv").open(newline="") as file:
        queries = list(csv.DictReader(file))
    assert len(queries) == 30
    assert len({row["source_id"] for row in queries}) == 30
    assert len(index) == len(indexed_sources) == 40
    assert sum(bool(row["expected_asset_id"]) for row in queries) == 20
    for row in queries:
        source = by_id[row["source_asset_id"]]
        if row["expected_asset_id"]:
            assert index[row["expected_asset_id"]].source_id == source.source_id
        else:
            assert source.source_id not in indexed_sources
            assert index[row["distractor_asset_id"]].label == source.label

        original, _ = sf.read(source.local_path(data), dtype="int16")
        crop, rate = sf.read(out / row["query_path"], dtype="int16")
        start = int(row["crop_start_sample"])
        assert rate == sample_rate
        assert len(crop) == 2 * sample_rate == int(row["crop_samples"])
        np.testing.assert_array_equal(crop, original[start : start + len(crop)])
        assert row["sha256"] == sha256_file(out / row["query_path"])

    damaged = [replace(asset, sha256="0" * 64) for asset in assets]
    write_manifest(manifest, damaged)
    broken = tmp_path / "broken"
    assert main([*base, "--out", str(broken)]) == 1
    assert not broken.exists()


def test_spike_has_clear_error_on_unverified_input(tmp_path, capsys):
    manifest = tmp_path / "assets.csv"
    write_manifest(
        manifest, [Asset("esc50:1", "esc50", "test", "audio/1.wav", "source")]
    )
    assert (
        main(
            [
                "data",
                "spike",
                "--esc50",
                str(tmp_path),
                "--inventory",
                str(manifest),
                "--out",
                str(tmp_path / "bad"),
            ]
        )
        == 1
    )
    assert "verified ESC-50 inventory" in capsys.readouterr().err
