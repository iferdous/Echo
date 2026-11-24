import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from echo.artifacts import sha256_file
from echo.fixtures import write_fixture


def test_stage2_report_records_offset_and_bad_inputs(tmp_path):
    spike = tmp_path / "fixture"
    write_fixture(spike)
    columns = (
        "query_id",
        "query_path",
        "label",
        "stratum",
        "expected_asset_id",
        "crop_start_sample",
        "source_sample_rate",
        "sha256",
    )
    positive = (
        "pos",
        "query.wav",
        "example",
        "synthetic",
        "fixture:reference",
        12_000,
        16_000,
        sha256_file(spike / "query.wav"),
    )
    negative = (
        "abs",
        "distractor.wav",
        "example",
        "synthetic",
        "",
        0,
        16_000,
        sha256_file(spike / "distractor.wav"),
    )
    bad = ("bad", *positive[1:5], 12_000, 0, positive[-1])
    with (spike / "queries.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows((positive, negative, bad))

    script = Path(__file__).resolve().parents[1] / "scripts/run_stage2_spike.py"
    out = tmp_path / "run"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(spike),
            "--spike",
            str(spike),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    summary = json.loads((out / "summary.json").read_text())["results"]
    assert summary["correct_accepted"] == 1
    assert summary["absent_source_accepted"] == 0
    assert summary["input_errors"] == 1
    assert summary["backend_agreements"] == 2
    with (out / "queries.csv").open(newline="", encoding="utf-8") as file:
        query_rows = {row["query_id"]: row for row in csv.DictReader(file)}
    assert float(query_rows["pos"]["correct_offset_error_seconds"]) == pytest.approx(
        0, abs=0.008
    )
    assert query_rows["pos"]["expected_offset_seconds"] == "0.75"
    assert query_rows["abs"]["expected_offset_seconds"] == ""
    assert query_rows["bad"]["status"] == "input_error"
