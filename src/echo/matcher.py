"""Rank candidate recordings by consistent, independent offset votes."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from echo.audio import load_audio
from echo.fingerprint import Landmark, fingerprint
from echo.index import Index, Track

MATCH_SCHEMA_VERSION = 1
DEFAULT_LIMIT = 5


@dataclass(frozen=True, slots=True)
class MatchPolicy:
    max_postings_per_hash: int = 256
    offset_radius_frames: int = 1
    min_support: int = 18
    min_anchor_frames: int = 8
    min_distinct_hashes: int = 10
    min_coverage: float = 0.20
    min_support_fraction: float = 0.035


DEFAULT_POLICY = MatchPolicy()


@dataclass(frozen=True, slots=True)
class Candidate:
    asset_id: str
    rank: int
    offset_frames: int
    offset_seconds: float
    query_span_seconds: list[float]
    reference_span_seconds: list[float]
    score: int
    anchor_frames: int
    distinct_hashes: int
    coverage: float
    support_fraction: float
    passes_threshold: bool


@dataclass(frozen=True, slots=True)
class MatchResult:
    schema_version: int
    status: str
    query_duration_seconds: float
    query_landmarks: int
    candidates: list[Candidate]


def best_offset(bins: dict[int, set[int]], radius: int) -> tuple[int, set[int]]:
    best_key = None
    best_frame = 0
    best_votes = set()
    for offset, exact in bins.items():
        combined = exact.copy()
        for neighbor in range(offset - radius, offset + radius + 1):
            if neighbor != offset and neighbor in bins:
                combined.update(bins[neighbor])
        key = (len(combined), len(exact), -abs(offset), -offset)
        if best_key is None or key > best_key:
            best_key = key
            best_frame = offset
            best_votes = combined
    return best_frame, best_votes


@dataclass(frozen=True, slots=True)
class Alignment:
    asset_id: str
    offset: int
    first_frame: int
    last_frame: int
    score: int
    anchors: int
    hashes: int


def describe_alignment(
    alignment: Alignment,
    rank: int,
    track: Track,
    query_samples: int,
    query_landmarks: int,
    index: Index,
    policy: MatchPolicy,
) -> Candidate:
    config = index.config
    first_sample = alignment.first_frame * config.hop_size + config.fft_size // 2
    last_sample = alignment.last_frame * config.hop_size + config.fft_size // 2
    offset_samples = alignment.offset * config.hop_size
    rate = config.sample_rate
    coverage = (last_sample - first_sample) / query_samples
    support_fraction = alignment.score / query_landmarks

    query_span = [first_sample / rate, last_sample / rate]
    reference_span = [
        min(track.samples, max(0, sample + offset_samples)) / rate
        for sample in (first_sample, last_sample)
    ]
    passes = (
        alignment.score >= policy.min_support
        and alignment.anchors >= policy.min_anchor_frames
        and alignment.hashes >= policy.min_distinct_hashes
        and coverage >= policy.min_coverage
        and support_fraction >= policy.min_support_fraction
    )
    return Candidate(
        alignment.asset_id,
        rank,
        alignment.offset,
        offset_samples / rate,
        query_span,
        reference_span,
        alignment.score,
        alignment.anchors,
        alignment.hashes,
        coverage,
        support_fraction,
        passes,
    )


def match_landmarks(
    query: list[Landmark],
    query_samples: int,
    index: Index,
    *,
    limit: int = DEFAULT_LIMIT,
    policy: MatchPolicy = DEFAULT_POLICY,
) -> MatchResult:
    if limit < 1:
        raise ValueError("result limit must be positive")
    if query_samples < 1:
        raise ValueError("query must contain at least one sample")
    query = sorted(set(query))
    duration = query_samples / index.config.sample_rate
    if len(query) < policy.min_support:
        return MatchResult(
            MATCH_SCHEMA_VERSION, "insufficient_evidence", duration, len(query), []
        )

    postings = index.lookup(
        {point.key for point in query}, policy.max_postings_per_hash
    )
    bins = defaultdict(lambda: defaultdict(set))
    for query_id, point in enumerate(query):
        for asset_id, reference_frame in postings.get(point.key, ()):
            bins[asset_id][reference_frame - point.frame].add(query_id)

    alignments = []
    for asset_id, track_bins in bins.items():
        offset, votes = best_offset(track_bins, policy.offset_radius_frames)
        matched = [query[query_id] for query_id in votes]
        frames = {point.frame for point in matched}
        alignments.append(
            Alignment(
                asset_id,
                offset,
                min(frames),
                max(frames),
                len(votes),
                len(frames),
                len({point.key for point in matched}),
            )
        )
    alignments.sort(
        key=lambda item: (
            -item.score,
            -item.anchors,
            -(item.last_frame - item.first_frame),
            item.asset_id,
        )
    )
    candidates = [
        describe_alignment(
            item,
            rank,
            index.tracks[item.asset_id],
            query_samples,
            len(query),
            index,
            policy,
        )
        for rank, item in enumerate(alignments[:limit], start=1)
    ]
    status = "matched" if candidates and candidates[0].passes_threshold else "no_match"
    return MatchResult(MATCH_SCHEMA_VERSION, status, duration, len(query), candidates)


def match_audio(
    path: Path,
    index: Index,
    *,
    limit: int = DEFAULT_LIMIT,
    policy: MatchPolicy = DEFAULT_POLICY,
) -> MatchResult:
    audio = load_audio(path, target_rate=index.config.sample_rate)
    return match_landmarks(
        fingerprint(audio.samples, index.config),
        len(audio.samples),
        index,
        limit=limit,
        policy=policy,
    )
