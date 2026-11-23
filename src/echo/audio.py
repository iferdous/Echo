"""Decode audio to mono float32 PCM with explicit source metadata."""

from dataclasses import dataclass
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray
from scipy.signal import resample_poly


class AudioError(ValueError):
    """An input could not be decoded as usable audio."""


@dataclass(frozen=True, slots=True)
class Audio:
    samples: NDArray[np.float32]
    sample_rate: int
    source_rate: int
    source_channels: int
    source_frames: int
    source_format: str
    source_subtype: str

    @property
    def source_duration(self) -> float:
        return self.source_frames / self.source_rate


def load_audio(path: Path, *, target_rate: int | None = None) -> Audio:
    """Keep the original time origin when downmixing and resampling."""
    if target_rate is not None and (type(target_rate) is not int or target_rate <= 0):
        raise ValueError("target sample rate must be a positive integer")

    try:
        with sf.SoundFile(path) as file:
            source_rate = file.samplerate
            source_channels = file.channels
            source_format = file.format
            source_subtype = file.subtype
            frames = file.read(dtype="float32", always_2d=True)
    except (OSError, sf.SoundFileError) as error:
        raise AudioError(f"cannot decode {path}: {error}") from error

    source_frames = len(frames)
    if source_rate <= 0 or source_channels <= 0 or source_frames == 0:
        raise AudioError(f"{path}: empty audio or invalid source format")
    if not np.isfinite(frames).all():
        raise AudioError(f"{path}: decoded audio contains non-finite samples")

    if source_channels == 1:
        samples = frames[:, 0]
    else:
        samples = frames.mean(axis=1, dtype=np.float64).astype(np.float32)

    sample_rate = target_rate or source_rate
    if sample_rate != source_rate:
        divisor = gcd(sample_rate, source_rate)
        samples = resample_poly(samples, sample_rate // divisor, source_rate // divisor)
        if not np.isfinite(samples).all():
            raise AudioError(f"{path}: resampled audio contains non-finite samples")
    return Audio(
        samples,
        sample_rate,
        source_rate,
        source_channels,
        source_frames,
        source_format,
        source_subtype,
    )
