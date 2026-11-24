import csv

from echo.artifacts import sha256_file
from echo.cli import main
from echo.datasets import Asset, write_manifest
from echo.fixtures import write_fixture


def test_batch_cli_records_accept_reject_and_input_error(tmp_path):
    fixture = tmp_path / "fixture"
    write_fixture(fixture)
    index = tmp_path / "fixture.sqlite"
    assert main(["index", str(fixture / "index.csv"), "--out", str(index)]) == 0
    queries = fixture / "queries.csv"
    write_manifest(
        queries,
        [
            Asset(
                "positive",
                "fixture",
                "1",
                "query.wav",
                "query",
                sha256=sha256_file(fixture / "query.wav"),
            ),
            Asset("control", "fixture", "1", "distractor.wav", "query"),
            Asset("missing", "fixture", "1", "missing.wav", "query"),
        ],
    )
    out = tmp_path / "audit"
    assert main(["audit", str(queries), "--index", str(index), "--out", str(out)]) == 1
    with (out / "queries.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert [row["decision"] for row in rows] == ["matched", "no_match", "input_error"]
    assert rows[0]["best_reference"] == "fixture:reference"
    assert abs(float(rows[0]["offset_seconds"]) - 0.75) < 0.008
    assert len({row["run_id"] for row in rows}) == 1
    assert "missing.wav" in rows[2]["message"]
