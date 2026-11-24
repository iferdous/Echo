import numpy as np
import soundfile as sf

from echo.batch import Batch, ScannedQuery
from echo.cross_audit import coverage_rows, review_pairs
from echo.datasets import Asset
from echo.matcher import Candidate, MatchResult
from echo.waveform_review import SAMPLE_RATE, WINDOW_SAMPLES


def test_review_finds_audio_in_a_different_source_and_preserves_known_misses(tmp_path):
    rng = np.random.default_rng(740)
    original = rng.normal(0, 0.1, 8 * WINDOW_SAMPLES)
    reference = Asset(
        "ref", "fsd50k", "test", "ref.wav", "shared_eval_id", "freesound", "100"
    )
    query = Asset(
        "known", "esc50", "test", "known.wav", "shared_eval_id", "freesound", "100"
    )
    different = Asset(
        "other", "esc50", "test", "other.wav", "same_class_control", "freesound", "200"
    )
    sf.write(tmp_path / "ref.wav", original, SAMPLE_RATE)
    sf.write(tmp_path / "known.wav", original[3 * WINDOW_SAMPLES :], SAMPLE_RATE)
    sf.write(tmp_path / "other.wav", original[WINDOW_SAMPLES:], SAMPLE_RATE)
    candidate = Candidate(
        "ref", 1, 0, 0.5, [0, 3], [0.5, 3.5], 30, 10, 12, 0.8, 0.8, True
    )
    rejected = ScannedQuery(query, MatchResult(1, "no_match", 2.5, 100, []), 0)
    accepted = ScannedQuery(
        different, MatchResult(1, "matched", 3.5, 100, [candidate]), 0
    )
    batch = Batch({}, [rejected, accepted])
    refs = {reference.asset_id: reference}
    reviews = review_pairs(
        batch, refs, refs, {"ref": {"license": "CC0"}}, tmp_path, tmp_path
    )
    assert (
        reviews["known", "ref"]["review_reasons"] == "known_source|missed_known_source"
    )
    assert reviews["known", "ref"]["offset_seconds"] == 1.5
    assert reviews["known", "ref"]["matcher_rank"] is None
    assert (
        reviews["other", "ref"]["review_reasons"] == "accepted_top|different_source_id"
    )
    assert reviews["other", "ref"]["offset_agrees"] is True
    rows = coverage_rows(batch, refs, refs, reviews, {"100"})
    assert [row["outcome"] for row in rows] == [
        "confirmed_audio_matcher_miss",
        "control_confirmed_audio_matched",
    ]
    assert [row["previously_seen_source"] for row in rows] == [True, False]
