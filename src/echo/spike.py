"""Reproducible ESC-50 crops and same-class absent-source queries."""

import csv
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from random import Random

import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.audio import load_audio
from echo.datasets import Asset, write_manifest

DEFAULT_SEED = 137
DEFAULT_INDEX_SIZE = 200
STRATA = {
    "transient": (
        "can_opening",
        "clapping",
        "door_wood_knock",
        "fireworks",
        "glass_breaking",
    ),
    "tonal": ("car_horn", "chirping_birds", "church_bells", "crow", "siren"),
    "repetitive": (
        "clock_tick",
        "footsteps",
        "keyboard_typing",
        "train",
        "washing_machine",
    ),
    "noise_like": ("crackling_fire", "rain", "sea_waves", "thunderstorm", "wind"),
}
QUERY_COLUMNS = (
    "query_id",
    "query_path",
    "source_asset_id",
    "source_id",
    "label",
    "stratum",
    "crop_start_sample",
    "crop_samples",
    "source_sample_rate",
    "expected_asset_id",
    "distractor_asset_id",
    "sha256",
)


@dataclass(frozen=True, slots=True)
class Query:
    query_id: str
    source: Asset
    stratum: str
    start_half_seconds: int
    expected_asset_id: str = ""
    distractor_asset_id: str = ""


def plan_spike(
    assets: list[Asset], *, seed: int, index_size: int
) -> tuple[list[Asset], list[Query]]:
    rng = Random(seed)
    pool = sorted(assets, key=lambda asset: asset.asset_id)
    if any(
        asset.dataset != "esc50"
        or asset.source_service != "freesound"
        or not asset.sha256
        for asset in pool
    ):
        raise ValueError(
            "spike input must be a verified ESC-50 inventory with source IDs"
        )

    rng.shuffle(pool)
    chosen_sources = set()
    references = []
    positives = []
    for stratum, labels in STRATA.items():
        for label in labels:
            asset = next(
                (
                    item
                    for item in pool
                    if item.label == label and item.source_id not in chosen_sources
                ),
                None,
            )
            if asset is None:
                raise ValueError(
                    f"no unused ESC-50 recording for positive label {label}"
                )
            chosen_sources.add(asset.source_id)
            references.append(asset)
            positives.append(
                Query(
                    f"pos-{len(positives) + 1:03}",
                    asset,
                    stratum,
                    rng.randint(1, 5),
                    asset.asset_id,
                )
            )

    negatives = []
    for positive in rng.sample(positives, 10):
        label = positive.source.label
        asset = next(
            (
                item
                for item in pool
                if item.label == label and item.source_id not in chosen_sources
            ),
            None,
        )
        if asset is None:
            raise ValueError(
                f"no independent ESC-50 recording for absent-source label {label}"
            )
        chosen_sources.add(asset.source_id)
        negatives.append(
            Query(
                f"abs-{len(negatives) + 1:03}",
                asset,
                positive.stratum,
                rng.randint(1, 5),
                distractor_asset_id=positive.source.asset_id,
            )
        )

    if index_size < len(references):
        raise ValueError(
            f"index size must be at least {len(references)} for the positive references"
        )
    for asset in pool:
        if len(references) == index_size:
            break
        if asset.source_id not in chosen_sources:
            chosen_sources.add(asset.source_id)
            references.append(asset)
    if len(references) != index_size:
        raise ValueError(f"only {len(references)} eligible indexed recording groups")
    return [replace(asset, role="index") for asset in references], positives + negatives


def write_spike(
    root: Path,
    assets: list[Asset],
    out: Path,
    *,
    seed: int,
    index_size: int,
    manifest_sha256: str,
) -> dict:
    index, queries = plan_spike(assets, seed=seed, index_size=index_size)
    used = {asset.asset_id: asset for asset in index}
    used.update((query.source.asset_id, query.source) for query in queries)
    for asset in used.values():
        if sha256_file(asset.local_path(root)) != asset.sha256:
            raise ValueError(
                f"{asset.asset_id}: file differs from the verified inventory"
            )

    with new_output_directory(out):
        (out / "queries").mkdir()
        write_manifest(out / "index.csv", index)
        with (out / "queries.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, QUERY_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for query in queries:
                audio = load_audio(query.source.local_path(root))
                start = query.start_half_seconds * audio.sample_rate // 2
                length = 2 * audio.sample_rate
                crop = audio.samples[start : start + length]
                if len(crop) != length:
                    raise ValueError(
                        f"{query.source.asset_id}: too short for the planned crop"
                    )
                path = out / "queries" / f"{query.query_id}.wav"
                sf.write(path, crop, audio.sample_rate, subtype="PCM_16")
                writer.writerow(
                    {
                        "query_id": query.query_id,
                        "query_path": path.relative_to(out).as_posix(),
                        "source_asset_id": query.source.asset_id,
                        "source_id": query.source.source_id,
                        "label": query.source.label,
                        "stratum": query.stratum,
                        "crop_start_sample": start,
                        "crop_samples": length,
                        "source_sample_rate": audio.sample_rate,
                        "expected_asset_id": query.expected_asset_id,
                        "distractor_asset_id": query.distractor_asset_id,
                        "sha256": sha256_file(path),
                    }
                )
        report = {
            "schema_version": 1,
            "seed": seed,
            "inventory_sha256": manifest_sha256,
            "index_sha256": sha256_file(out / "index.csv"),
            "queries_sha256": sha256_file(out / "queries.csv"),
            "indexed_assets": len(index),
            "positive_queries": sum(bool(query.expected_asset_id) for query in queries),
            "absent_source_queries": sum(
                not query.expected_asset_id for query in queries
            ),
            "query_strata": dict(Counter(query.stratum for query in queries)),
            "index_policy": "one asset per source; all references plus seeded background",
        }
        write_json(out / "spike.json", report)
    return report
