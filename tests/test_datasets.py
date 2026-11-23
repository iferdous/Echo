import io
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest
import soundfile as sf

from echo.acquisition import download_verified
from echo.artifacts import sha256_file
from echo.datasets import (
    Asset,
    inventory_esc50,
    overlap_report,
    parse_esc50,
    read_fsd50k_partitions,
    read_manifest,
    write_manifest,
)

ESC_ROWS = """filename,fold,target,category,src_file,take
2-30-A-0.wav,2,0,dog,30,A
1-30-B-0.wav,1,0,dog,30,B
1-40-A-1.wav,1,1,rooster,40,A
3-60-A-0.wav,3,0,dog,60,A
"""


def test_manifests_round_trip_and_reject_duplicates(tmp_path):
    assets = parse_esc50(io.StringIO(ESC_ROWS))
    path = tmp_path / "manifest.csv"
    write_manifest(path, assets)
    assert read_manifest(path) == assets
    assert assets[0].asset_id == "esc50:1-30-B-0.wav"
    assert assets[0].source_id == "30"
    write_manifest(path, [assets[0], assets[0]])
    with pytest.raises(ValueError, match="duplicate asset ID"):
        read_manifest(path)


@pytest.mark.parametrize(
    "relative", ["../outside.wav", "/outside.wav", "audio\\x.wav", "a//b.wav"]
)
def test_manifest_rejects_unsafe_asset_paths(relative):
    with pytest.raises(ValueError, match="relative POSIX"):
        Asset("test:1", "test", "v1", relative, "source")


def test_manifest_rejects_symlink_escape(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    external = tmp_path / "external.wav"
    external.touch()
    (root / "escape.wav").symlink_to(external)
    asset = Asset("test:1", "test", "v1", "escape.wav", "source")
    with pytest.raises(ValueError, match="outside the dataset root"):
        asset.local_path(root)


def test_invalid_esc50_data_is_rejected():
    with pytest.raises(ValueError, match="invalid ESC-50 metadata row"):
        parse_esc50(io.StringIO(ESC_ROWS.replace("dog,30,A", "dog,31,A")))
    with pytest.raises(ValueError, match="missing or duplicate CSV columns"):
        parse_esc50(io.StringIO(ESC_ROWS.replace("filename,fold", "filename,filename")))
    with pytest.raises(ValueError, match="wrong number of fields"):
        parse_esc50(io.StringIO(ESC_ROWS.replace("dog,30,A", "dog,30,A,unexpected")))


def make_fsd_zip(path: Path, *, eval_source: int = 40) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "FSD50K.ground_truth/dev.csv", "fname,split\n30,train\n50,val\n"
        )
        archive.writestr("FSD50K.ground_truth/eval.csv", f"fname\n{eval_source}\n")


def test_overlap_counts_assets_and_sources_independently(tmp_path):
    path = tmp_path / "metadata.zip"
    make_fsd_zip(path)
    report = overlap_report(
        parse_esc50(io.StringIO(ESC_ROWS)), read_fsd50k_partitions(path)
    )
    assert report["esc50_cross_fold_sources"] == {"30": ["1", "2"]}
    assert report["shared_esc50_rows"] == 3
    assert report["shared_source_ids"] == 2
    assert report["partitions"]["train"]["shared_esc50_rows"] == 2
    assert report["partitions"]["train"]["shared_source_ids"] == 1
    assert report["partitions"]["train"]["shared_esc50_rows_by_fold"] == {
        "1": 1,
        "2": 1,
        "3": 0,
        "4": 0,
        "5": 0,
    }
    assert report["partitions"]["val"]["shared_esc50_rows"] == 0


def test_fsd50k_rejects_duplicate_source_ids_across_partitions(tmp_path):
    path = tmp_path / "metadata.zip"
    make_fsd_zip(path, eval_source=30)
    with pytest.raises(ValueError, match="duplicate FSD50K source ID 30"):
        read_fsd50k_partitions(path)


def test_inventory_keeps_only_verified_assets_and_accounts_for_missing_and_corrupt(
    tmp_path,
):
    root = tmp_path / "corpus"
    (root / "audio").mkdir(parents=True)
    (root / "meta").mkdir()
    (root / "meta/esc50.csv").write_text(ESC_ROWS)
    assets = parse_esc50(io.StringIO(ESC_ROWS))
    first_path = root / assets[0].path
    sf.write(first_path, np.zeros(16_000), 16_000)
    (root / assets[1].path).write_bytes(b"corrupt")
    (root / "audio/unlisted.wav").touch()

    out = tmp_path / "run"
    report = inventory_esc50(root, assets, out)
    assert report["expected_assets"] == 4
    assert report["decoded_assets"] == 1
    assert report["sample_rates"] == {"16000": 1}
    assert report["total_duration_seconds"] == 1.0
    assert len(report["rejected"]) == 3
    assert report["unlisted_wavs"] == ["audio/unlisted.wav"]
    assert report["manifest_sha256"] == sha256_file(out / "assets.csv")
    assert read_manifest(out / "assets.csv") == [
        replace(assets[0], sha256=sha256_file(first_path))
    ]


def test_download_checks_digest_before_installing_archive(tmp_path):
    original = tmp_path / "source.zip"
    original.write_bytes(b"known bytes")
    target = tmp_path / "cache/download.zip"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_verified(original.as_uri(), target, "0" * 64)
    assert list(target.parent.iterdir()) == []
    digest = sha256_file(original)
    download_verified(original.as_uri(), target, digest)
    download_verified("file:///ignored-on-cache-hit", target, digest)
    assert target.read_bytes() == original.read_bytes()
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        download_verified(original.as_uri(), target, digest)
    assert target.read_bytes() == b"changed"


def test_esc50_extraction_publishes_only_complete_inputs(tmp_path, monkeypatch):
    from hashlib import sha256

    from echo import datasets
    from echo.acquisition import extract_esc50

    prefix = f"ESC-50-{datasets.ESC50_REVISION}/"
    incoming = tmp_path / "input.zip"
    extracted = tmp_path / "esc50"
    monkeypatch.setattr(
        datasets, "ESC50_METADATA_SHA256", sha256(ESC_ROWS.encode()).hexdigest()
    )

    def make_zip(include_audio):
        with ZipFile(incoming, "w") as archive:
            archive.writestr(prefix + "LICENSE", "test license")
            archive.writestr(prefix + "meta/esc50.csv", ESC_ROWS)
            if include_audio:
                for asset in parse_esc50(io.StringIO(ESC_ROWS)):
                    archive.writestr(prefix + asset.path, b"test file")

    make_zip(include_audio=False)
    with pytest.raises(KeyError):
        extract_esc50(incoming, extracted)
    assert not extracted.exists()
    make_zip(include_audio=True)
    extract_esc50(incoming, extracted)
    assert (extracted / "meta/esc50.csv").read_text() == ESC_ROWS
    assert len(list((extracted / "audio").glob("*.wav"))) == 4
