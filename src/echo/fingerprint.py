"""Deterministic time-frequency landmarks and pair hashes."""

import hashlib
import json
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass, fields
from itertools import groupby
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from scipy.fft import rfft
from scipy.ndimage import maximum_filter, maximum_filter1d
from scipy.signal.windows import hann

FINGERPRINT_VERSION = 1
FIELD_BITS = 10
FIELD_LIMIT = 1 << FIELD_BITS


@dataclass(frozen=True, slots=True)
class FingerprintConfig:
    sample_rate: int = 16_000
    fft_size: int = 512
    hop_size: int = 128
    peak_floor_db: int = 45
    peak_floor_radius_frames: int = 16
    peak_time_radius: int = 3
    peak_frequency_radius: int = 3
    max_peaks_per_frame: int = 5
    min_frequency_hz: int = 50
    min_pair_ms: int = 50
    max_pair_ms: int = 750
    fan_out: int = 8
    delay_bin_frames: int = 2

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, field.name)) is not int
            or getattr(self, field.name)
            < (0 if field.name == "peak_floor_radius_frames" else 1)
            for field in fields(self)
        ):
            raise ValueError(
                "fingerprint fields must be positive integers (floor radius may be zero)"
            )
        if not 8 <= self.fft_size < 2 * FIELD_LIMIT or self.fft_size % 2:
            raise ValueError(
                "fft_size must be even and fit the fingerprint frequency fields"
            )
        if self.hop_size > self.fft_size:
            raise ValueError("hop_size cannot exceed fft_size")
        if self.min_frequency_hz * 2 >= self.sample_rate:
            raise ValueError("min_frequency_hz must be below Nyquist")
        if self.min_pair_frames > self.max_pair_frames:
            raise ValueError(
                "pairing window must contain at least one positive frame interval"
            )
        if self.max_pair_frames // self.delay_bin_frames >= FIELD_LIMIT:
            raise ValueError("pairing window does not fit the fingerprint delay field")

    @property
    def min_pair_frames(self) -> int:
        return (self.min_pair_ms * self.sample_rate + 1000 * self.hop_size - 1) // (
            1000 * self.hop_size
        )

    @property
    def max_pair_frames(self) -> int:
        return self.max_pair_ms * self.sample_rate // (1000 * self.hop_size)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> "FingerprintConfig":
        value = json.loads(text)
        try:
            if not isinstance(value, dict):
                raise TypeError("expected a JSON object")
            return cls(**value)
        except TypeError as error:
            raise ValueError(f"invalid fingerprint configuration: {error}") from error


def read_config(path: Path | None) -> FingerprintConfig:
    if path is None:
        return FingerprintConfig()
    return FingerprintConfig.from_json(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True, order=True)
class Landmark:
    frame: int
    key: int


def pack_hash(anchor_bin: int, target_bin: int, delay_bin: int) -> int:
    if not all(
        0 <= value < FIELD_LIMIT for value in (anchor_bin, target_bin, delay_bin)
    ):
        raise ValueError("fingerprint hash fields must fit in 10 bits each")
    return (anchor_bin << (2 * FIELD_BITS)) | (target_bin << FIELD_BITS) | delay_bin


def spectral_peaks(
    samples: NDArray[np.float32], config: FingerprintConfig
) -> list[tuple[int, int]]:
    if samples.size < config.fft_size:
        return []
    amplitude = np.max(np.abs(samples))
    if amplitude == 0:
        return []

    windows = sliding_window_view(samples / amplitude, config.fft_size)[
        :: config.hop_size
    ]
    window = hann(config.fft_size, sym=False).astype(np.float32)
    magnitude = np.abs(rfft(windows * window, axis=1))
    first_bin = (
        config.min_frequency_hz * config.fft_size + config.sample_rate - 1
    ) // (config.sample_rate)
    magnitude[:, :first_bin] = 0
    maximum = float(magnitude.max())
    if maximum == 0:
        return []

    local_max = maximum_filter(
        magnitude,
        size=(2 * config.peak_time_radius + 1, 2 * config.peak_frequency_radius + 1),
        mode="constant",
        cval=0,
    )
    # A local floor preserves quiet excerpts when a loud event occurs elsewhere.
    floor_reference = maximum
    if config.peak_floor_radius_frames:
        floor_reference = maximum_filter1d(
            magnitude.max(axis=1),
            2 * config.peak_floor_radius_frames + 1,
            mode="constant",
            cval=0,
        )[:, None]
    floor = floor_reference * (10.0 ** (-config.peak_floor_db / 20))
    matches = np.argwhere(
        (magnitude >= floor) & (magnitude == local_max) & (magnitude > 0)
    )

    peaks = []
    for frame, row in groupby(matches.tolist(), key=lambda item: item[0]):
        bins = [frequency for _, frequency in row]
        strongest = sorted(
            bins, key=lambda frequency: (-magnitude[frame, frequency], frequency)
        )
        peaks.extend(
            (frame, frequency)
            for frequency in sorted(strongest[: config.max_peaks_per_frame])
        )
    return peaks


def fingerprint(
    samples: NDArray[np.float32], config: FingerprintConfig
) -> list[Landmark]:
    return pair_peaks(spectral_peaks(samples, config), config)


def pair_peaks(
    peaks: list[tuple[int, int]], config: FingerprintConfig
) -> list[Landmark]:
    frames = [frame for frame, _ in peaks]
    result = set()
    min_delay, max_delay = config.min_pair_frames, config.max_pair_frames
    for frame, frequency in peaks:
        start = bisect_left(frames, frame + min_delay)
        stop = bisect_right(frames, frame + max_delay, lo=start)
        for target_frame, target in peaks[start : min(stop, start + config.fan_out)]:
            delay_bin = (target_frame - frame) // config.delay_bin_frames
            result.add(Landmark(frame, pack_hash(frequency, target, delay_bin)))
    return sorted(result)
