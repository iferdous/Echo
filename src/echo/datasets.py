"""Track manifests, ESC-50 inventory, and metadata-only overlap audit."""

import csv
import io
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import TextIO
from zipfile import ZipFile

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.audio import load_audio

ESC50_REVISION = "33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6"
ESC50_METADATA_SHA256 = (
    "ca660da60191a97de289983a05821c9382d852a38a2ba8428980816b68cf6246"
)
FSD50K_REVISION = "10.5281/zenodo.4060432"
FSD50K_GROUND_TRUTH_SHA256 = (
    "db2396260a7b1fb06feb6ccac71685794fc89917d71c3a8d64a1de85c2cc0ebf"
)


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    dataset: str
    revision: str
    path: str
    role: str
    source_service: str = ""
    source_id: str = ""
    label: str = ""
    fold: str = ""
    sha256: str = ""
    attribution: str = ""

    def __post_init__(self) -> None:
        if not all((self.asset_id, self.dataset, self.revision, self.role)):
            raise ValueError("asset ID, dataset, revision, and role are required")
        if any(part in {"", ".", ".."} for part in self.path.split("/")) or any(
            char in self.path for char in ("\\", ":", "\x00")
        ):
            raise ValueError(f"expected a relative POSIX asset path: {self.path!r}")
        if bool(self.source_service) != bool(self.source_id):
            raise ValueError("source service and source ID must be supplied together")
        if self.sha256 and not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError(f"invalid SHA-256 for {self.asset_id}")

    def local_path(self, root: Path) -> Path:
        root = root.resolve()
        resolved = (root / self.path).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"{self.asset_id}: path points outside the dataset root")
        return resolved


ASSET_COLUMNS = tuple(field.name for field in fields(Asset))


def csv_rows(
    file: TextIO, required: Iterable[str], *, name: str
) -> Iterator[dict[str, str]]:
    reader = csv.DictReader(file, strict=True)
    header = reader.fieldnames or []
    if len(header) != len(set(header)) or not set(required).issubset(header):
        raise ValueError(f"{name}: missing or duplicate CSV columns")
    for row in reader:
        if None in row or None in row.values():
            raise ValueError(f"{name}:{reader.line_num}: wrong number of fields")
        yield row


def read_manifest(path: Path) -> list[Asset]:
    assets = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv_rows(file, ASSET_COLUMNS, name=str(path)):
            asset = Asset(**{name: row[name] for name in ASSET_COLUMNS})
            if asset.asset_id in seen:
                raise ValueError(f"{path}: duplicate asset ID {asset.asset_id}")
            seen.add(asset.asset_id)
            assets.append(asset)
    return assets


def write_manifest(path: Path, assets: Iterable[Asset]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, ASSET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(asset) for asset in assets)


def parse_esc50(file: TextIO) -> list[Asset]:
    assets = []
    seen = set()
    columns = ("filename", "fold", "target", "category", "src_file", "take")
    for row in csv_rows(file, columns, name="ESC-50 metadata"):
        filename, source, fold = row["filename"], row["src_file"], row["fold"]
        if (
            fold not in {"1", "2", "3", "4", "5"}
            or not re.fullmatch(r"[0-9]+", source)
            or not re.fullmatch(r"[A-Z]+", row["take"])
            or not re.fullmatch(r"[0-9]+", row["target"])
            or not row["category"]
            or filename != f"{fold}-{source}-{row['take']}-{row['target']}.wav"
        ):
            raise ValueError(f"invalid ESC-50 metadata row for {filename!r}")
        if filename in seen:
            raise ValueError(f"duplicate ESC-50 filename {filename}")
        seen.add(filename)
        assets.append(
            Asset(
                f"esc50:{filename}",
                "esc50",
                ESC50_REVISION,
                f"audio/{filename}",
                "source",
                "freesound",
                source,
                row["category"],
                fold,
                attribution="LICENSE",
            )
        )
    return sorted(assets, key=lambda asset: asset.asset_id)


def load_esc50_metadata(path: Path) -> list[Asset]:
    if sha256_file(path) != ESC50_METADATA_SHA256:
        raise ValueError(f"{path}: does not match the pinned ESC-50 metadata digest")
    with path.open(encoding="utf-8-sig", newline="") as file:
        return parse_esc50(file)


def read_fsd50k_partitions(path: Path) -> dict[str, str]:
    sources = {}
    with ZipFile(path) as archive:
        for partition, allowed in (("dev", {"train", "val"}), ("eval", {"eval"})):
            with (
                archive.open(f"FSD50K.ground_truth/{partition}.csv") as member,
                io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as file,
            ):
                required = ("fname", "split") if partition == "dev" else ("fname",)
                for row in csv_rows(file, required, name=f"FSD50K {partition}.csv"):
                    source = row["fname"]
                    split = row.get("split") or partition
                    if not re.fullmatch(r"[0-9]+", source) or split not in allowed:
                        raise ValueError(
                            f"invalid FSD50K entry {source!r} in {split!r}"
                        )
                    if source in sources:
                        raise ValueError(f"duplicate FSD50K source ID {source}")
                    sources[source] = split
    return sources


def overlap_report(assets: list[Asset], fsd_sources: dict[str, str]) -> dict:
    folds_by_source = defaultdict(set)
    for asset in assets:
        folds_by_source[asset.source_id].add(asset.fold)
    shared = [asset for asset in assets if asset.source_id in fsd_sources]
    fsd_counts = Counter(fsd_sources.values())
    partitions = {}
    for split in ("train", "val", "eval"):
        matches = [asset for asset in shared if fsd_sources[asset.source_id] == split]
        by_fold = Counter(asset.fold for asset in matches)
        partitions[split] = {
            "fsd50k_rows": fsd_counts[split],
            "shared_esc50_rows": len(matches),
            "shared_source_ids": len({asset.source_id for asset in matches}),
            "shared_esc50_rows_by_fold": {
                str(fold): by_fold[str(fold)] for fold in range(1, 6)
            },
        }
    return {
        "schema_version": 1,
        "esc50_rows": len(assets),
        "esc50_source_ids": len(folds_by_source),
        "esc50_cross_fold_sources": {
            source: sorted(folds)
            for source, folds in sorted(folds_by_source.items())
            if len(folds) > 1
        },
        "fsd50k_rows": len(fsd_sources),
        "shared_esc50_rows": len(shared),
        "shared_source_ids": len({asset.source_id for asset in shared}),
        "partitions": partitions,
    }


def inventory_esc50(root: Path, assets: list[Asset], out: Path) -> dict:
    verified = []
    rejected = []
    rates = Counter()
    channels = Counter()
    formats = Counter()
    durations = []
    for asset in assets:
        try:
            path = asset.local_path(root)
            if not path.is_file():
                raise FileNotFoundError(f"missing or unreadable file {asset.path}")
            audio = load_audio(path)
            checksum = sha256_file(path)
        except (OSError, ValueError) as error:
            rejected.append({"asset_id": asset.asset_id, "reason": str(error)})
            continue
        verified.append(replace(asset, sha256=checksum))
        rates[str(audio.source_rate)] += 1
        channels[str(audio.source_channels)] += 1
        formats[f"{audio.source_format}/{audio.source_subtype}"] += 1
        durations.append(audio.source_duration)

    listed = {asset.path for asset in assets}
    unlisted = sorted(
        f"audio/{path.name}"
        for path in (root / "audio").glob("*.wav")
        if f"audio/{path.name}" not in listed
    )
    with new_output_directory(out):
        manifest = out / "assets.csv"
        write_manifest(manifest, verified)
        report = {
            "schema_version": 1,
            "dataset": "esc50",
            "revision": ESC50_REVISION,
            "metadata_sha256": sha256_file(root / "meta/esc50.csv"),
            "manifest_sha256": sha256_file(manifest),
            "expected_assets": len(assets),
            "decoded_assets": len(verified),
            "sample_rates": dict(rates),
            "channel_counts": dict(channels),
            "formats": dict(formats),
            "min_duration_seconds": min(durations, default=None),
            "max_duration_seconds": max(durations, default=None),
            "total_duration_seconds": sum(durations),
            "rejected": rejected,
            "unlisted_wavs": unlisted,
        }
        write_json(out / "inventory.json", report)
    return report
