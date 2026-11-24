import json
from dataclasses import replace
from random import Random

import pytest

from echo.cli import main
from echo.fingerprint import FingerprintConfig, Landmark
from echo.fixtures import write_fixture
from echo.index import FingerprintedTrack, MemoryIndex, Track, build_index
from echo.matcher import DEFAULT_POLICY, match_landmarks, resolve_alignment_engine


def test_explicit_rust_failure_keeps_the_python_fallback_available(monkeypatch):
    def missing(_name):
        raise ModuleNotFoundError("_echo_offsets")

    monkeypatch.setattr("echo.matcher.import_module", missing)
    assert callable(resolve_alignment_engine("python"))
    with pytest.raises(ValueError, match="build and install"):
        resolve_alignment_engine("rust")


def test_native_votes_match_python_with_signed_offsets_repeated_keys_and_ties():
    pytest.importorskip("_echo_offsets")
    rust = resolve_alignment_engine("rust")
    rng = Random(8346)
    for _ in range(32):
        points = [Landmark(rng.randrange(60), rng.randrange(24)) for _ in range(100)]
        tracks = [
            FingerprintedTrack(
                Track(name, 24_000, 100),
                [Landmark(rng.randrange(80), rng.randrange(30)) for _ in range(100)],
            )
            for name in ("duplicate", "b", "café", "a")
        ]
        # Same postings under two IDs exercise the stable candidate tie-break.
        tracks[0] = FingerprintedTrack(tracks[0].track, tracks[-1].landmarks * 2)
        index = MemoryIndex(FingerprintConfig(), tracks)
        for radius in (0, 1, 5, 100, 10**20):
            policy = replace(
                DEFAULT_POLICY, offset_radius_frames=radius, min_score_margin=2
            )
            expected = match_landmarks(points, 16_000, index, policy=policy)
            actual = match_landmarks(points, 16_000, index, policy=policy, aligner=rust)
            assert actual == expected


def test_native_match_and_input_errors_at_cli(tmp_path, capsys):
    pytest.importorskip("_echo_offsets")
    root = tmp_path / "fixture"
    write_fixture(root)
    database = root / "index.sqlite"
    build_index(root / "index.csv", root, database, FingerprintConfig())
    for filename, expected_code in (
        ("query.wav", 0),
        ("distractor.wav", 0),
        ("missing.wav", 1),
    ):
        results = []
        for engine in ("python", "rust"):
            code = main(
                [
                    "match",
                    str(root / filename),
                    "--index",
                    str(database),
                    "--engine",
                    engine,
                    "--json",
                ]
            )
            assert code == expected_code
            results.append(json.loads(capsys.readouterr().out))
        assert results[0] == results[1]
