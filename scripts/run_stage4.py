"""Prepare and acquire the Stage 4 cross-dataset cohort."""

import argparse
import json
import sys
from pathlib import Path

from echo.cross_dataset import acquire_cohort, prepare_cohort


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    prepare = modes.add_parser(
        "prepare", help="freeze ESC-50 queries and official FSD50K eval references"
    )
    prepare.add_argument("--esc-inventory", type=Path, required=True)
    prepare.add_argument("--ground-truth", type=Path, required=True)
    prepare.add_argument("--stage2", type=Path, required=True)
    prepare.add_argument("--stage3", type=Path, required=True)
    prepare.add_argument("--spec", type=Path, default=Path("bench/stage4-spec.json"))
    prepare.add_argument("--out", type=Path, required=True)

    acquire = modes.add_parser(
        "acquire", help="extract the selected WAVs from official archive ranges"
    )
    acquire.add_argument("--cohort", type=Path, required=True)
    acquire.add_argument("--metadata", type=Path, required=True)
    acquire.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            report = prepare_cohort(
                args.esc_inventory,
                args.ground_truth,
                args.stage2,
                args.stage3,
                args.spec,
                args.out,
            )
            print(
                json.dumps(
                    {key: report[key] for key in ("index_cohorts", "query_cohorts")},
                    sort_keys=True,
                )
            )
        else:
            report = acquire_cohort(args.cohort, args.metadata, args.out)
            print(
                json.dumps(
                    {
                        key: report[key]
                        for key in (
                            "available_references",
                            "unavailable_references",
                            "archive_payload_bytes_received",
                        )
                    },
                    sort_keys=True,
                )
            )
    except (OSError, ValueError, KeyError) as error:
        print(f"echo cross-dataset audit: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
