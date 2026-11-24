import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict, replace

import numpy as np
import pytest
import soundfile as sf

from echo.artifacts import sha256_file
from echo.cli import main
from echo.datasets import Asset, read_manifest, write_manifest
from echo.fingerprint import FingerprintConfig, Landmark
from echo.fixtures import write_fixture
from echo.index import (
    FingerprintedTrack,
    IndexFormatError,
    MemoryIndex,
    Track,
    build_index,
    fingerprint_manifest,
    open_index,
)
from echo.matcher import DEFAULT_POLICY, match_audio, match_landmarks


@pytest.fixture
def audio_fixture(tmp_path):
    out = tmp_path / "fixture"
    write_fixture(out)
    return out


def test_fresh_cli_process_matches_memory_and_reports_offset(audio_fixture):
    database = audio_fixture / "index #1?.sqlite"
    manifest = audio_fixture / "index.csv"
    assert main(["index", str(manifest), "--out", str(database)]) == 0
    query = audio_fixture / "query.wav"
    config = FingerprintConfig()
    memory = MemoryIndex(config, fingerprint_manifest(manifest, audio_fixture, config))
    expected = match_audio(query, memory)
    output = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "echo",
            "match",
            str(query),
            "--index",
            str(database),
            "--json",
        ],
        text=True,
    )
    received = json.loads(output)
    assert {name: received[name] for name in asdict(expected)} == asdict(expected)
    assert received["fingerprint_config_sha256"] == config.digest
    assert received["status"] == "matched"
    assert received["candidates"][0]["asset_id"] == "fixture:reference"
    assert received["candidates"][0]["offset_seconds"] == pytest.approx(0.75, abs=0.008)

    with open_index(database) as index:
        distractor = match_audio(audio_fixture / "distractor.wav", index)
        assert distractor.query_landmarks >= DEFAULT_POLICY.min_support
        assert distractor.status == "no_match"


def test_negative_offsets_and_stable_candidate_ties(audio_fixture):
    config = FingerprintConfig()
    manifest = audio_fixture / "index.csv"
    (original,) = read_manifest(manifest)
    crop = audio_fixture / "query.wav"
    excerpt = replace(original, path=crop.name, sha256=sha256_file(crop))
    write_manifest(
        manifest, [replace(excerpt, asset_id="z"), replace(excerpt, asset_id="a")]
    )
    memory = MemoryIndex(config, fingerprint_manifest(manifest, audio_fixture, config))
    result = match_audio(audio_fixture / "reference.wav", memory)
    assert result.status == "matched"
    assert [candidate.asset_id for candidate in result.candidates] == ["a", "z"]
    assert result.candidates[0].offset_seconds == pytest.approx(-0.75, abs=0.008)
    assert result.candidates[0].reference_span_seconds[0] >= 0


def test_neighboring_offsets_and_duplicate_query_points_count_once():
    config = FingerprintConfig()
    query = [Landmark(2 * i, i + 100) for i in range(24)]
    reference = [
        Landmark(point.frame + offset, point.key)
        for point in query
        for offset in (10, 11)
    ]
    memory = MemoryIndex(
        config, [FingerprintedTrack(Track("rec", 16_000, len(reference)), reference)]
    )
    result = match_landmarks(query + query, 16_000, memory)
    assert result.status == "matched"
    assert result.query_landmarks == result.candidates[0].score == len(query)
    assert result.candidates[0].offset_frames == 10

    result = match_landmarks(
        query, 16_000, memory, policy=replace(DEFAULT_POLICY, max_postings_per_hash=1)
    )
    assert result.status == "no_match"
    assert result.candidates == []


def test_silence_empty_index_and_corrupt_input_are_distinct(audio_fixture, capsys):
    config = FingerprintConfig()
    empty = MemoryIndex(config, [])
    assert match_audio(audio_fixture / "query.wav", empty).status == "no_match"
    silent = audio_fixture / "silent.wav"
    sf.write(silent, np.zeros(16_000), 16_000)
    assert match_audio(silent, empty).status == "insufficient_evidence"

    manifest = audio_fixture / "empty.csv"
    write_manifest(manifest, [])
    database = audio_fixture / "index.sqlite"
    build_index(manifest, audio_fixture, database, config)
    answer = match_audio(audio_fixture / "query.wav", empty)
    with open_index(database) as index:
        assert match_audio(audio_fixture / "query.wav", index) == answer
    corrupt = audio_fixture / "corrupt.wav"
    corrupt.write_text("not a WAV")
    assert main(["match", str(corrupt), "--index", str(database), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "input_error"


def test_sqlite_rejects_non_echo_schema_and_configuration_mismatch(audio_fixture):
    config = FingerprintConfig()
    database = audio_fixture / "index.sqlite"
    build_index(audio_fixture / "index.csv", audio_fixture, database, config)
    with (
        pytest.raises(IndexFormatError, match="does not match"),
        open_index(database, replace(config, fan_out=config.fan_out + 1)),
    ):
        pytest.fail("configuration mismatch was accepted")

    wrong = audio_fixture / "other.sqlite"
    with closing(sqlite3.connect(wrong)) as connection:
        connection.execute("CREATE TABLE misc (id INTEGER)")
    with (
        pytest.raises(IndexFormatError, match="unsupported Echo index schema"),
        open_index(wrong),
    ):
        pytest.fail("unrelated database was accepted")


def test_failed_and_interrupted_replacements_preserve_prior_index(
    audio_fixture, monkeypatch
):
    config = FingerprintConfig()
    manifest = audio_fixture / "index.csv"
    database = audio_fixture / "index.sqlite"
    build_index(manifest, audio_fixture, database, config)
    before = sha256_file(database)
    with pytest.raises(FileExistsError, match="--replace"):
        build_index(manifest, audio_fixture, database, config)

    (original,) = read_manifest(manifest)
    write_manifest(
        manifest, [original, Asset("missing", "fixture", "1", "missing.wav", "index")]
    )
    with pytest.raises(ValueError, match="missing.wav"):
        build_index(manifest, audio_fixture, database, config, replace_existing=True)
    assert sha256_file(database) == before

    def interrupt_build(*args):
        points = [Landmark(0, 100)]
        yield FingerprintedTrack(Track("partial", 512, 1), points)
        raise KeyboardInterrupt

    monkeypatch.setattr("echo.index.fingerprint_manifest", interrupt_build)
    with pytest.raises(KeyboardInterrupt):
        build_index(manifest, audio_fixture, database, config, replace_existing=True)
    assert sha256_file(database) == before
    with open_index(database) as index:
        assert list(index.tracks) == ["fixture:reference"]
    assert not any(path.is_dir() for path in audio_fixture.iterdir())
