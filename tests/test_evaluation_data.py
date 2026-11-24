import hashlib

import numpy as np
import pytest
import soundfile as sf

from echo.artifacts import sha256_file
from echo.audio import load_audio
from echo.datasets import Asset
from echo.evaluation_data import VARIANTS, get_ffmpeg, plan_splits, write_variant


def asset(number):
    source = str(number)
    return Asset(
        f"original-{source}",
        "esc50",
        "fixture",
        f"{source}.wav",
        "source",
        "freesound",
        source,
        "dog",
        sha256=hashlib.sha256(source.encode()).hexdigest(),
    )


def test_plan_reserves_disjoint_sources_and_exact_audio(monkeypatch):
    monkeypatch.setattr("echo.evaluation_data.STRATA", {"example": ("dog",)})
    assets = [asset(number) for number in range(20)]
    options = {
        "seed": 99,
        "groups_per_label_and_kind": 2,
        "background_references_per_split": 2,
    }
    plan = plan_splits(assets, {"0", "1"}, **options)
    assert plan == plan_splits(list(reversed(assets)), {"0", "1"}, **options)
    partition_sources = []
    for split in plan.values():
        references = {item.asset_id: item for item in split.index}
        sources = {item.source_id for item in split.index}
        queries = {cohort.asset.source_id for cohort in split.cohorts}
        asserts_included = 0
        for cohort in split.cohorts:
            if cohort.expected_id:
                assert (
                    references[cohort.expected_id].source_id == cohort.asset.source_id
                )
                asserts_included += 1
            else:
                assert cohort.asset.source_id not in sources
                assert references[cohort.distractor_id].label == cohort.asset.label
        assert len(split.index) == len(split.cohorts) == 4
        assert asserts_included == 2
        assert sum(cohort.expose_id for cohort in split.cohorts) == 2
        partition_sources.append(sources | queries)
    assert partition_sources[0].isdisjoint(partition_sources[1])
    assert (partition_sources[0] | partition_sources[1]).isdisjoint({"0", "1"})


def test_audio_variations_have_expected_rate_length_and_reproducible_noise(tmp_path):
    original = tmp_path / "source.wav"
    rate = 44_100
    samples = (0.3 * np.sin(2 * np.pi * 400 * np.arange(rate * 5) / rate)).astype(
        np.float32
    )
    sf.write(original, samples, rate, subtype="PCM_16")
    audio = load_audio(original)
    by_name = {variant.name: variant for variant in VARIANTS}
    ffmpeg = get_ffmpeg()
    for name in (
        "identity",
        "crop_4s",
        "mp3_64k",
        "mp3_128k",
        "resample_8khz",
        "noise_10db",
        "quiet_24db",
    ):
        variant = by_name[name]
        suffix = ".mp3" if variant.transform == "mp3" else ".wav"
        destination = tmp_path / (name + suffix)
        write_variant(
            destination,
            original,
            audio,
            rate // 2,
            variant,
            137,
            ffmpeg,
            tmp_path / "scratch.wav",
        )
        decoded = load_audio(destination)
        if name == "identity":
            assert sha256_file(original) == sha256_file(destination)
        assert decoded.sample_rate == (8_000 if name == "resample_8khz" else rate)
        assert decoded.source_duration == pytest.approx(variant.seconds or 5, abs=0.03)
        if name == "quiet_24db":
            assert np.max(np.abs(decoded.samples)) < 0.025

    repeat = tmp_path / "repeat.wav"
    write_variant(
        repeat,
        original,
        audio,
        rate // 2,
        by_name["noise_10db"],
        137,
        ffmpeg,
        tmp_path / "scratch.wav",
    )
    assert sha256_file(repeat) == sha256_file(tmp_path / "noise_10db.wav")
