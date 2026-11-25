import json
from pathlib import Path
from zipfile import ZipFile

from echo.cli import main
from echo.evidence import open_evidence


def test_fixture_run_is_repeatable_and_report_reopens_a_portable_zip(tmp_path):
    first, second = tmp_path / "fixture-1", tmp_path / "fixture-2"
    for out in (first, second):
        assert main(["bench", "--profile", "fixture", "--out", str(out)]) == 0
    assert open_evidence(first).run_id == open_evidence(second).run_id

    archive = tmp_path / "fixture.zip"
    assert main(["bundle", str(first), "--out", str(archive)]) == 0
    with ZipFile(archive) as contents:
        assert all(
            not name.endswith((".wav", ".sqlite")) for name in contents.namelist()
        )
        assert "fixture/candidates.csv" in contents.namelist()
    assert main(["report", str(archive), "--out", str(tmp_path / "rendered")]) == 0
    metrics = json.loads((tmp_path / "rendered/metrics.json").read_text())
    assert [row["decision"] for row in metrics["fixture"]["queries"]] == [
        "matched",
        "no_match",
        "insufficient_evidence",
    ]
    assert metrics["fixture"]["expected_offset_seconds"] == 0.75
    assert metrics["run_id"] == open_evidence(first).run_id
    with ZipFile(archive, "a") as contents:
        contents.writestr("../audio.wav", b"unapproved")
    rejected = tmp_path / "bad-archive"
    assert main(["report", str(archive), "--out", str(rejected)]) == 1
    assert not rejected.exists()


def test_reports_fail_closed_on_missing_data_and_changed_run_receipts(tmp_path, capsys):
    repo = Path(__file__).resolve().parents[1]
    run = tmp_path / "fixture"
    assert main(["bench", "--profile", "fixture", "--out", str(run)]) == 0
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["run_id"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    destination = tmp_path / "invalid-report"
    assert main(["report", str(run), "--out", str(destination)]) == 1
    assert "run ID" in capsys.readouterr().err
    assert not destination.exists()
    manifest_path.write_text(json.dumps(manifest))
    (run / "fixture/candidates.csv").unlink()
    assert main(["report", str(run), "--out", str(tmp_path / "missing-artifact")]) == 1
    assert "missing evidence file" in capsys.readouterr().err

    assert (
        main(
            [
                "bench",
                "--profile",
                "full",
                "--repo",
                str(repo),
                "--data-root",
                str(tmp_path),
                "--out",
                str(tmp_path / "empty-full"),
            ]
        )
        == 1
    )
    assert "missing local input" in capsys.readouterr().err
    assert not (tmp_path / "empty-full").exists()
