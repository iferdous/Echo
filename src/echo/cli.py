"""Command-line entry point for Echo."""

import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from echo.fixtures import write_fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="echo-audit", description="Audit shared recordings across audio datasets."
    )
    parser.add_argument(
        "--version", action="version", version=f"echo-audit {version('echo-audit')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser(
        "fixture", help="write deterministic synthetic WAV fixtures"
    )
    fixture.add_argument("--out", required=True, type=Path, help="new output directory")
    args = parser.parse_args(argv)

    try:
        write_fixture(args.out)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"echo-audit: {error}", file=sys.stderr)
        return 1
    print(f"Wrote audio fixture to {args.out}")
    return 0
