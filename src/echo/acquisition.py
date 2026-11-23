"""Fetch pinned public dataset inputs into local storage."""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

from echo.artifacts import sha256_file
from echo.datasets import (
    ESC50_REVISION,
    FSD50K_GROUND_TRUTH_SHA256,
    load_esc50_metadata,
)

ESC50_URL = f"https://codeload.github.com/karolpiczak/ESC-50/zip/{ESC50_REVISION}"
ESC50_ARCHIVE_SHA256 = (
    "661183a6f53ef04f12c9bd618fed0ddc1713280d6c94a5a5431e844ba6f6a21f"
)
FSD50K_URL = (
    "https://zenodo.org/records/4060432/files/FSD50K.ground_truth.zip?download=1"
)


def verify_digest(path: Path, expected: str) -> None:
    if sha256_file(path) != expected:
        raise ValueError(f"SHA-256 mismatch for {path}; expected {expected}")


def download_verified(url: str, destination: Path, expected: str) -> None:
    if destination.exists():
        verify_digest(destination, expected)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as folder:
        partial = Path(folder) / destination.name
        with urlopen(url, timeout=60) as response, partial.open("wb") as file:
            shutil.copyfileobj(response, file, length=1024 * 1024)
        verify_digest(partial, expected)
        partial.replace(destination)


def extract_esc50(archive_path: Path, destination: Path) -> None:
    prefix = f"ESC-50-{ESC50_REVISION}/"
    if destination.exists():
        raise FileExistsError(f"dataset destination already exists: {destination}")
    with (
        TemporaryDirectory(dir=destination.parent) as folder,
        ZipFile(archive_path) as archive,
    ):
        staging = Path(folder)
        # Extract only known members and paths named by the validated metadata.
        (staging / "meta").mkdir()
        (staging / "audio").mkdir()
        for relative in ("LICENSE", "meta/esc50.csv"):
            (staging / relative).write_bytes(archive.read(prefix + relative))
        for asset in load_esc50_metadata(staging / "meta/esc50.csv"):
            with (
                archive.open(prefix + asset.path) as source,
                (staging / asset.path).open("wb") as target,
            ):
                shutil.copyfileobj(source, target)
        staging.rename(destination)


def fetch_stage_one(root: Path) -> tuple[Path, Path]:
    esc50_archive = root / "downloads/esc50.zip"
    fsd50k_metadata = root / "downloads/fsd50k-ground-truth.zip"
    download_verified(ESC50_URL, esc50_archive, ESC50_ARCHIVE_SHA256)
    download_verified(FSD50K_URL, fsd50k_metadata, FSD50K_GROUND_TRUTH_SHA256)
    esc50_root = root / "esc50"
    if esc50_root.exists():
        load_esc50_metadata(esc50_root / "meta/esc50.csv")
    else:
        extract_esc50(esc50_archive, esc50_root)
    return esc50_root, fsd50k_metadata
