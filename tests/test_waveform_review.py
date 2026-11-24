import numpy as np
import pytest

from echo.waveform_review import SAMPLE_RATE, verify_waveforms


def test_recovers_signed_offset_from_shared_audio_with_gain():
    rng = np.random.default_rng(137)
    original = rng.standard_normal(5 * SAMPLE_RATE)
    start = 6_237
    excerpt = original[start : start + 2 * SAMPLE_RATE] * -0.6
    result = verify_waveforms(excerpt, original)
    assert result.verified
    assert result.offset_seconds == pytest.approx(start / SAMPLE_RATE)
    assert result.aligned_windows == 4
    reverse = verify_waveforms(original, excerpt)
    assert reverse.verified
    assert reverse.offset_seconds == pytest.approx(-start / SAMPLE_RATE)
    assert reverse.aligned_windows >= 3


def test_no_confirmation_for_independent_noise_repeated_tones_or_silence():
    rng = np.random.default_rng(35)
    samples = 3 * SAMPLE_RATE
    assert not verify_waveforms(
        rng.standard_normal(samples), rng.standard_normal(samples)
    ).verified
    tone = np.sin(2 * np.pi * 400 * np.arange(samples) / SAMPLE_RATE)
    repeated = verify_waveforms(tone, tone)
    assert not repeated.verified
    assert repeated.reason == "ambiguous_repeated_waveform"
    assert (
        verify_waveforms(np.zeros(samples), tone).reason
        == "insufficient_non_silent_audio"
    )
