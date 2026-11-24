"""Prepare, calibrate, or score the Stage 3 matcher benchmark."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from echo.evaluation import calibrate, evaluate_test
from echo.evaluation_data import prepare


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    phases = parser.add_subparsers(dest="command", required=True)
    generate = phases.add_parser("prepare")
    generate.add_argument("--inventory", type=Path, required=True)
    generate.add_argument("--development", type=Path, required=True)
    generate.add_argument("--spec", type=Path, default=Path("bench/stage3-spec.json"))
    calibration = phases.add_parser("calibrate")
    test = phases.add_parser("test")
    for phase in (generate, calibration, test):
        phase.add_argument("--root", type=Path, required=True)
        phase.add_argument("--out", type=Path, required=True)
    for phase in (calibration, test):
        phase.add_argument("--design", type=Path, required=True)
    test.add_argument("--calibration", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "prepare":
            report = prepare(
                args.root, args.inventory, args.development, args.spec, args.out
            )
            print(json.dumps(report["splits"], sort_keys=True))
            return 0
        if args.command == "calibrate":
            report = calibrate(args.root, args.design, args.out)
        else:
            report = evaluate_test(args.root, args.design, args.calibration, args.out)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"echo benchmark: {error}", file=sys.stderr)
        return 1

    print(json.dumps(report["metrics"]["match"], sort_keys=True))
    return int(report["metrics"]["input_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
