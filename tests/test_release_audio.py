import json

import numpy as np
import soundfile as sf

from echo.audio import load_audio
from echo.cli import main
from echo.fingerprint import FingerprintConfig, Landmark, fingerprint
from echo.fixtures import write_fixture


def test_malformed_queries_fail_cleanly_with_a_seeded_byte_corpus(tmp_path, capsys):
    data = tmp_path / "fixture"
    write_fixture(data)
    index = tmp_path / "index.sqlite"
    assert main(["index", str(data / "index.csv"), "--out", str(index)]) == 0
    capsys.readouterr()
    wav = (data / "query.wav").read_bytes()
    generator = np.random.default_rng(90217)
    inputs = [
        b"",
        b"not an audio file",
        wav[:20],
        wav[:-251],
        b"JUNK" + wav[4:],
        *(generator.bytes(length) for length in range(1, 401, 4)),
    ]
    query = data / "untrusted.wav"
    for sample in inputs:
        query.write_bytes(sample)
        assert main(["match", str(query), "--index", str(index), "--json"]) == 1
        output = capsys.readouterr()
        result = json.loads(output.out)
        assert result["status"] == "input_error"
        assert result["query_id"] == query.name
        assert query.name in result["message"]
        if sample == wav[:-251]:
            assert "truncated WAV container" in result["message"]


def test_valid_edge_audio_has_an_explicit_match_status(tmp_path, capsys):
    data = tmp_path / "fixture"
    write_fixture(data)
    index = tmp_path / "index.sqlite"
    assert main(["index", str(data / "index.csv"), "--out", str(index)]) == 0
    capsys.readouterr()
    query = data / "edge.wav"
    for rate, sample_count, channels in (
        (8_000, 1, 1),
        (96_000, 960, 2),
        (16_000, 960_000, 1),
    ):
        sf.write(query, np.zeros((sample_count, channels), dtype=np.float32), rate)
        assert main(["match", str(query), "--index", str(index), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "insufficient_evidence"


def test_hop_aligned_translation_preserves_interior_landmarks(tmp_path):
    data = tmp_path / "fixture"
    write_fixture(data)
    config = FingerprintConfig()
    samples = load_audio(data / "reference.wav", target_rate=config.sample_rate).samples
    landmarks = fingerprint(samples, config)
    assert landmarks == fingerprint(samples.copy(), config)

    # Moving identical PCM by whole hops should preserve interior pairs.
    # The edges can legitimately change because the spectral window has new context.
    guard = config.max_pair_frames + config.peak_floor_radius_frames + 8
    end = len(samples) // config.hop_size - guard
    expected = {point for point in landmarks if guard <= point.frame < end}
    assert expected
    for shift in (7, 33, 125):
        padded = np.pad(samples, (shift * config.hop_size, 0))
        shifted = {
            Landmark(point.frame - shift, point.key)
            for point in fingerprint(padded, config)
            if guard <= point.frame - shift < end
        }
        assert shifted == expected
