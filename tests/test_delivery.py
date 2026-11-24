import csv
from shutil import copyfile

from echo.cli import main
from echo.datasets import read_manifest
from echo.fixtures import write_fixture


def test_folder_to_review_keeps_errors_and_escapes_identifiers(tmp_path):
    fixture = tmp_path / "fixture"
    write_fixture(fixture)
    reference = tmp_path / "train"
    query = tmp_path / "test"
    reference.mkdir()
    (query / "sub").mkdir(parents=True)
    copyfile(fixture / "reference.wav", reference / "original.WAV")
    copyfile(fixture / "query.wav", query / "sub/crop.wav")
    copyfile(fixture / "distractor.wav", query / "different.wav")
    (query / "corrupt.wav").write_text("this is a damaged local clip")
    (query / "notes.txt").write_text("excluded by the file suffix allowlist")
    refs, queries = tmp_path / "refs.csv", tmp_path / "queries.csv"
    dataset = "eval<svg onload=alert(1)>"
    flags = ["--dataset", dataset, "--role", "query"]
    assert main(["data", "manifest", str(query), *flags, "--out", str(queries)]) == 0
    assert main(["data", "manifest", str(query), *flags, "--out", str(queries)]) == 1
    assert (
        main(
            [
                "data",
                "manifest",
                str(reference),
                "--dataset",
                "train",
                "--role",
                "reference",
                "--out",
                str(refs),
            ]
        )
        == 0
    )
    assert [item.path for item in read_manifest(queries)] == [
        "corrupt.wav",
        "different.wav",
        "sub/crop.wav",
    ]
    index = tmp_path / "index.sqlite"
    run = tmp_path / "audit"
    report = run / "review.html"
    assert (
        main(["index", str(refs), "--root", str(reference), "--out", str(index)]) == 0
    )
    assert (
        main(
            [
                "audit",
                str(queries),
                "--root",
                str(query),
                "--index",
                str(index),
                "--out",
                str(run),
            ]
        )
        == 1
    )
    assert main(["review", str(run), "--out", str(report)]) == 0
    html = report.read_text()
    assert "eval&lt;svg onload=alert(1)&gt;" in html
    assert "<svg onload=alert(1)>" not in html
    assert "train:original.WAV" in html and "Input error" in html
    with (run / "queries.csv").open(newline="") as evidence:
        decisions = list(csv.DictReader(evidence))
    assert [row["decision"] for row in decisions] == [
        "input_error",
        "no_match",
        "matched",
    ]
    with (run / "queries.csv").open("a") as evidence:
        evidence.write("\n")
    destination = tmp_path / "bad.html"
    assert main(["review", str(run), "--out", str(destination)]) == 1
    assert not destination.exists()


def test_manifest_refuses_symlinked_audio_without_publishing_a_partial_file(tmp_path):
    real = tmp_path / "original.wav"
    real.write_text("audit input")
    root = tmp_path / "audio"
    root.mkdir()
    (root / "linked.wav").symlink_to(real)
    out = tmp_path / "manifest.csv"
    flags = ["--dataset", "incoming", "--role", "query"]
    assert main(["data", "manifest", str(root), *flags, "--out", str(out)]) == 1
    assert not out.exists()
