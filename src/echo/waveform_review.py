"""Independently verify matched time spans with normalized waveform correlation."""

from dataclasses import dataclass
from statistics import median

import numpy as np
from numpy.typing import NDArray
from scipy.signal import correlate

SAMPLE_RATE = 8_000
WINDOW_SAMPLES = SAMPLE_RATE // 2
MIN_CORRELATION = 0.93
PEAK_MARGIN = 0.03
COMPETING_PEAK_DISTANCE = round(SAMPLE_RATE * 0.04)
MAX_LAG_DELTA = round(SAMPLE_RATE * 0.002)
MIN_WINDOWS = 2
MIN_RMS = 0.00001


@dataclass(frozen=True, slots=True)
class Window:
    start: int
    offset: int
    correlation: float
    unique: bool


@dataclass(frozen=True, slots=True)
class Review:
    verified: bool
    reason: str
    offset_seconds: float | None
    query_start_seconds: float | None
    query_end_seconds: float | None
    aligned_windows: int
    examined_windows: int
    best_correlation: float | None
    median_aligned_correlation: float | None


def centered_window_norms(samples: NDArray, length: int) -> NDArray:
    sums = np.cumsum(samples, dtype=np.float64)
    squares = np.cumsum(samples**2, dtype=np.float64)
    sums = np.r_[0.0, sums]
    squares = np.r_[0.0, squares]
    total = sums[length:] - sums[:-length]
    energy = squares[length:] - squares[:-length] - total**2 / length
    return np.sqrt(np.maximum(energy, 0))


def locate_window(query, start, reference, norms) -> Window | None:
    section = query[start : start + WINDOW_SAMPLES]
    centered = section - section.mean()
    norm = np.linalg.norm(centered)
    minimum = MIN_RMS * np.sqrt(WINDOW_SAMPLES)
    if norm < minimum:
        return None
    dots = correlate(reference, centered, mode="valid", method="fft")
    absolute = np.divide(
        np.abs(dots), norms * norm, out=np.zeros_like(dots), where=norms >= minimum
    )
    np.minimum(absolute, 1, out=absolute)
    best = int(np.argmax(absolute))
    peak = float(absolute[best])
    competing = max(
        float(absolute[: max(0, best - COMPETING_PEAK_DISTANCE)].max(initial=0.0)),
        float(absolute[best + COMPETING_PEAK_DISTANCE + 1 :].max(initial=0.0)),
    )
    return Window(start, best - start, peak, peak - competing >= PEAK_MARGIN)


def verify_waveforms(query: NDArray, reference: NDArray) -> Review:
    if min(len(query), len(reference)) < WINDOW_SAMPLES:
        return Review(
            False, "shorter_than_review_window", None, None, None, 0, 0, None, None
        )
    query = query.astype(np.float64, copy=False)
    reference = reference.astype(np.float64, copy=False)
    norms = centered_window_norms(reference, WINDOW_SAMPLES)
    windows = [
        window
        for start in range(0, len(query) - WINDOW_SAMPLES + 1, WINDOW_SAMPLES)
        if (window := locate_window(query, start, reference, norms)) is not None
    ]
    strong = [
        window
        for window in windows
        if window.unique and window.correlation >= MIN_CORRELATION
    ]
    groups = [
        [
            peer
            for peer in strong
            if abs(peer.offset - candidate.offset) <= MAX_LAG_DELTA
        ]
        for candidate in strong
    ]
    best = max(
        groups,
        key=lambda items: (len(items), median(item.correlation for item in items)),
        default=[],
    )
    peak = max((item.correlation for item in windows), default=None)
    if len(best) < MIN_WINDOWS:
        reason = "no_stable_waveform_alignment"
        if not windows:
            reason = "insufficient_non_silent_audio"
        elif any(
            item.correlation >= MIN_CORRELATION and not item.unique for item in windows
        ):
            reason = "ambiguous_repeated_waveform"
        return Review(
            False, reason, None, None, None, len(best), len(windows), peak, None
        )
    return Review(
        True,
        "consistent_unique_waveform",
        median(item.offset for item in best) / SAMPLE_RATE,
        min(item.start for item in best) / SAMPLE_RATE,
        (max(item.start for item in best) + WINDOW_SAMPLES) / SAMPLE_RATE,
        len(best),
        len(windows),
        peak,
        median(item.correlation for item in best),
    )
