import json
import subprocess
import sys

import numpy as np
import soundfile as sf

from echo.cli import main


def test_fixture_cli_writes_sample_exact_crop(tmp_path):
    out = tmp_path / "fixture"
    assert main(["fixture", "--out", str(out)]) == 0
    expected = json.loads((out / "fixture.json").read_text())
    assert expected["seed"] == 137
    assert expected["crop_start_sample"] == 12_000
    assert expected["crop_samples"] == 32_000
    reference, reference_rate = sf.read(out / "reference.wav", dtype="int16")
    query, query_rate = sf.read(out / "query.wav", dtype="int16")
    distractor, _ = sf.read(out / "distractor.wav", dtype="int16")
    assert reference_rate == query_rate == 16_000
    assert np.array_equal(query, reference[12_000:44_000])
    assert not np.array_equal(query, distractor[12_000:44_000])

    another_out = tmp_path / "repeat"
    assert main(["fixture", "--out", str(another_out)]) == 0
    assert (out / "fixture.json").read_bytes() == (
        another_out / "fixture.json"
    ).read_bytes()


def test_fixture_refuses_existing_output(tmp_path):
    sentinel = tmp_path / "previous-run"
    sentinel.write_text("keep me")
    assert main(["fixture", "--out", str(tmp_path)]) == 1
    assert sentinel.read_text() == "keep me"


def test_module_help_and_version():
    help_result = subprocess.check_output(
        [sys.executable, "-m", "echo", "--help"], text=True
    )
    assert "fixture" in help_result
    version_result = subprocess.check_output(
        [sys.executable, "-m", "echo", "--version"], text=True
    )
    assert version_result.startswith("echo-audit ")
