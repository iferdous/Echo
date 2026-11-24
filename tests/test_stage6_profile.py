import runpy
from pathlib import Path

from echo.fingerprint import FingerprintConfig
from echo.fixtures import write_fixture
from echo.index import build_index, open_index
from echo.matcher import DEFAULT_POLICY, match_audio


def test_phase_profile_preserves_the_full_match_and_accounts_for_time(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/run_stage6.py"
    sample = runpy.run_path(str(script))
    root = tmp_path / "fixture"
    write_fixture(root)
    database = tmp_path / "index.sqlite"
    build_index(root / "index.csv", root, database, FingerprintConfig())
    with open_index(database) as index:
        for filename in ("query.wav", "distractor.wav"):
            path = root / filename
            expected = match_audio(path, index)
            actual, timings = sample["profile_match"](path, index, DEFAULT_POLICY)
            assert actual == expected
            assert timings["match_ns"] == sum(timings[key] for key in sample["PHASES"])
            assert all(timing >= 0 for timing in timings.values())
