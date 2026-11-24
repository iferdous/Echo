import numpy as np
import pytest

from echo.audio import load_audio
from echo.fingerprint import FingerprintConfig, fingerprint, pack_hash
from echo.fixtures import write_fixture


def test_pair_hash_keeps_three_distinct_fields():
    packed = {
        pack_hash(a, b, t)
        for a in (0, 1, 1023)
        for b in (0, 1, 1023)
        for t in (0, 1, 1023)
    }
    assert len(packed) == 27
    with pytest.raises(ValueError, match="fit"):
        pack_hash(0, 1024, 0)


def test_configuration_round_trips_and_rejects_invalid_values():
    config = FingerprintConfig(peak_floor_radius_frames=0, fan_out=3)
    recovered = FingerprintConfig.from_json(config.to_json())
    assert config == recovered
    assert config.digest == recovered.digest
    assert config.digest != FingerprintConfig().digest

    with pytest.raises(ValueError, match="invalid fingerprint configuration"):
        FingerprintConfig.from_json('{"unknown": 3}')
    with pytest.raises(ValueError, match="positive integers"):
        FingerprintConfig(fan_out=True)
    with pytest.raises(ValueError, match="pairing window"):
        FingerprintConfig(min_pair_ms=800)


def test_landmarks_are_stable_under_gain_and_have_no_duplicates(tmp_path):
    out = tmp_path / "fixture"
    write_fixture(out)
    config = FingerprintConfig()
    samples = load_audio(out / "reference.wav", target_rate=config.sample_rate).samples
    landmarks = fingerprint(samples, config)
    assert landmarks
    assert landmarks == sorted(set(landmarks))
    assert landmarks == fingerprint(samples * np.float32(0.25), config)


def test_silence_and_subwindow_audio_have_no_landmarks():
    config = FingerprintConfig()
    assert fingerprint(np.zeros(16_000, dtype=np.float32), config) == []
    assert fingerprint(np.ones(config.fft_size - 1, dtype=np.float32), config) == []
