"""Write a local A/B excerpt from a waveform-confirmed Stage 4 pair."""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file
from echo.audio import load_audio
from echo.datasets import csv_rows, read_manifest
from echo.waveform_review import MIN_CORRELATION, SAMPLE_RATE, WINDOW_SAMPLES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--esc-root", type=Path, required=True)
    parser.add_argument("--fsd-root", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--reference-id", required=True)
    parser.add_argument(
        "--query-start",
        type=float,
        help="start time in seconds within the reviewed span",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    columns = (
        "query_id",
        "reference_id",
        "verdict",
        "offset_seconds",
        "query_start_seconds",
        "query_end_seconds",
    )
    with args.reviews.open(encoding="utf-8", newline="") as file:
        review = next(
            (
                row
                for row in csv_rows(file, columns, name=str(args.reviews))
                if row["query_id"] == args.query_id
                and row["reference_id"] == args.reference_id
                and row["verdict"] == "confirmed"
            ),
            None,
        )
    if review is None:
        parser.error("the requested pair has no confirmed waveform alignment")

    query_start = float(review["query_start_seconds"])
    if args.query_start is not None:
        if not query_start <= args.query_start or (
            args.query_start + WINDOW_SAMPLES / SAMPLE_RATE
            > float(review["query_end_seconds"])
        ):
            parser.error(
                "query start must leave a full window inside the reviewed span"
            )
        query_start = args.query_start
    offset = float(review["offset_seconds"])
    query_sample = round(query_start * SAMPLE_RATE)
    reference_sample = round((query_start + offset) * SAMPLE_RATE)
    queries = {asset.asset_id: asset for asset in read_manifest(args.queries)}
    references = {asset.asset_id: asset for asset in read_manifest(args.references)}
    query_asset, reference_asset = queries[args.query_id], references[args.reference_id]
    query_path = query_asset.local_path(args.esc_root)
    reference_path = reference_asset.local_path(args.fsd_root)
    for asset, path in ((query_asset, query_path), (reference_asset, reference_path)):
        if not asset.sha256 or asset.sha256 != sha256_file(path):
            parser.error(f"{asset.asset_id}: audio differs from the reviewed manifest")
    query = load_audio(query_path, target_rate=SAMPLE_RATE).samples
    reference = load_audio(reference_path, target_rate=SAMPLE_RATE).samples
    # The median lag can extend a few samples outside the first confirmed window.
    trim = max(0, -query_sample, -reference_sample)
    length = min(
        WINDOW_SAMPLES, len(query) - query_sample, len(reference) - reference_sample
    )
    if length <= trim:
        parser.error("the recorded alignment does not overlap the input files")
    first = query[query_sample + trim : query_sample + length]
    second = reference[reference_sample + trim : reference_sample + length]
    correlation = abs(float(np.corrcoef(first, second)[0, 1]))
    if not correlation >= MIN_CORRELATION:
        parser.error(
            "this excerpt has insufficient waveform correlation at the recorded lag"
        )
    with new_output_directory(args.out):
        sf.write(args.out / "esc50.wav", first, SAMPLE_RATE)
        sf.write(args.out / "fsd50k.wav", second, SAMPLE_RATE)
        sf.write(
            args.out / "compare.wav",
            np.concatenate((first, np.zeros(SAMPLE_RATE // 5), second)),
            SAMPLE_RATE,
        )


if __name__ == "__main__":
    main()
