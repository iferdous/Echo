import numpy as np
import pytest
import soundfile as sf

from echo.audio import AudioError, load_audio


def test_downmix_preserves_original_metadata_and_accepts_silence(tmp_path):
    path = tmp_path / "stereo.wav"
    frames = np.array([[0.5, -0.5], [0.25, 0.25], [0.0, 0.0]], dtype=np.float32)
    sf.write(path, frames, 8_000, subtype="FLOAT")
    audio = load_audio(path)
    assert audio.source_channels == 2
    assert audio.source_frames == 3
    assert audio.source_rate == audio.sample_rate == 8_000
    assert audio.source_duration == 3 / 8_000
    assert audio.samples.dtype == np.float32
    np.testing.assert_array_equal(audio.samples, [0.0, 0.25, 0.0])


def test_polyphase_resampling_preserves_timing_and_filters_alias_sources(tmp_path):
    source_rate = 44_100
    target_rate = 16_000
    path = tmp_path / "impulse.wav"
    impulse = np.zeros(source_rate, dtype=np.float32)
    impulse[11_025] = 1
    sf.write(path, impulse, source_rate, subtype="FLOAT")
    audio = load_audio(path, target_rate=target_rate)
    assert audio.samples.dtype == np.float32
    assert audio.source_rate == source_rate
    assert audio.sample_rate == target_rate
    assert len(audio.samples) == target_rate
    assert abs(int(np.argmax(audio.samples)) - 4_000) <= 1

    time = np.arange(source_rate) / source_rate
    sf.write(path, np.sin(2 * np.pi * 12_000 * time), source_rate, subtype="FLOAT")
    samples = load_audio(path, target_rate=target_rate).samples[256:-256]
    assert np.sqrt(np.mean(samples**2)) < 0.01


@pytest.mark.parametrize("kind", ["missing", "corrupt", "empty", "non-finite"])
def test_invalid_audio_reports_source_path(tmp_path, kind):
    path = tmp_path / f"{kind}.wav"
    if kind == "corrupt":
        path.write_bytes(b"incomplete audio")
    elif kind == "empty":
        sf.write(path, np.empty(0), 8_000)
    elif kind == "non-finite":
        sf.write(path, np.array([0.0, np.nan]), 8_000, subtype="FLOAT")

    with pytest.raises(AudioError, match=path.name):
        load_audio(path)


def test_invalid_target_rate_is_reported_before_decoding(tmp_path):
    with pytest.raises(ValueError, match="positive integer"):
        load_audio(tmp_path / "irrelevant.wav", target_rate=0)
