"""Helpers for writing local evidence without replacing existing runs."""

import csv
import hashlib
import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def new_output_directory(path: Path) -> Iterator[None]:
    """Reserve a fresh output path and remove it if the run fails."""
    path.mkdir(parents=True)
    try:
        yield
    except BaseException:
        shutil.rmtree(path)
        raise


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_csv(path: Path, columns, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
