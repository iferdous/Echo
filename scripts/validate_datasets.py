"""Check decoded audio against the release corpus expectations."""

import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from echo.artifacts import new_output_file, sha256_file, write_json
from echo.audio import load_audio
from echo.datasets import read_manifest

SAMPLE_RATE = 44_100
# Include the positive PCM16 ceiling (32767 / 32768) as well as -1.0.
PCM16_CEILING = 32767 / 32768
CLIPPING_FRACTION = 0.01
REVIEW_MIN_SECONDS = 0.5


def validate(manifest, root, dataset):
    assets = read_manifest(manifest)
    issues = []
    rates = Counter()
    channels = Counter()
    formats = Counter()
    durations = []
    decoded = 0
    for asset in assets:
        findings = []
        try:
            path = asset.local_path(root)
            if not asset.sha256 or asset.sha256 != sha256_file(path):
                findings.append("manifest_checksum_mismatch")
            audio = load_audio(path)
        except (OSError, ValueError) as error:
            issues.append(
                {
                    "asset_id": asset.asset_id,
                    "path": asset.path,
                    "findings": [*findings, "unanalyzable_audio"],
                    "error": str(error),
                }
            )
            continue
        decoded += 1
        rates[str(audio.source_rate)] += 1
        channels[str(audio.source_channels)] += 1
        formats[f"{audio.source_format}/{audio.source_subtype}"] += 1
        durations.append(audio.source_duration)
        if audio.source_rate != SAMPLE_RATE:
            findings.append("unexpected_sample_rate")
        if audio.source_channels != 1:
            findings.append("unexpected_channel_count")
        if dataset == "esc50" and audio.source_duration != 5:
            findings.append("unexpected_esc50_duration")
        if dataset == "fsd50k_eval" and audio.source_duration > 30.001:
            findings.append("over_30_seconds")
        if audio.source_duration < REVIEW_MIN_SECONDS:
            findings.append("shorter_than_waveform_review_window")
        clipped = float(np.mean(np.abs(audio.samples) >= PCM16_CEILING))
        if clipped >= CLIPPING_FRACTION:
            findings.append("one_percent_or_more_samples_at_pcm16_ceiling")
        if findings:
            issues.append(
                {
                    "asset_id": asset.asset_id,
                    "path": asset.path,
                    "duration_seconds": audio.source_duration,
                    "mono_ceiling_fraction": clipped,
                    "findings": findings,
                }
            )
    return {
        "dataset": dataset,
        "manifest_sha256": sha256_file(manifest),
        "assets": len(assets),
        "decoded": decoded,
        "sample_rates_hz": dict(rates),
        "channels": dict(channels),
        "formats": dict(formats),
        "duration_seconds": {
            "min": min(durations, default=None),
            "max": max(durations, default=None),
        },
        "counts": dict(
            Counter(finding for row in issues for finding in row["findings"])
        ),
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esc-root", required=True, type=Path)
    parser.add_argument("--esc-manifest", required=True, type=Path)
    parser.add_argument("--fsd-root", required=True, type=Path)
    parser.add_argument("--fsd-manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    results = [
        validate(args.esc_manifest, args.esc_root, "esc50"),
        validate(args.fsd_manifest, args.fsd_root, "fsd50k_eval"),
    ]
    with new_output_file(args.out) as file:
        write_json(
            file,
            {
                "schema_version": 1,
                "mono_pcm16_ceiling_fraction_threshold": CLIPPING_FRACTION,
                "review_min_seconds": REVIEW_MIN_SECONDS,
                "corpora": results,
            },
        )
    print(f"Dataset validation saved to {args.out}")
    if any(
        {"unanalyzable_audio", "manifest_checksum_mismatch"} & report["counts"].keys()
        for report in results
    ):
        parser.exit(1, "Dataset validation found changed or unreadable audio.\n")


if __name__ == "__main__":
    main()
