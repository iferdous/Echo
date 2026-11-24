"""Freeze source-disjoint matcher trials and their audio transforms."""

import csv
import hashlib
import json
import shutil
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from random import Random

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.audio import load_audio
from echo.datasets import Asset, csv_rows, read_manifest, write_manifest
from echo.spike import STRATA

SPLITS = ("calibration", "test")


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    seconds: int | None
    transform: str = "pcm"
    value: int = 0


VARIANTS = (
    Variant("identity", None, "copy"),
    Variant("crop_1s", 1),
    Variant("crop_2s", 2),
    Variant("crop_4s", 4),
    Variant("mp3_64k", 2, "mp3", 64),
    Variant("mp3_128k", 2, "mp3", 128),
    Variant("resample_8khz", 2, "resample", 8_000),
    Variant("noise_10db", 2, "snr", 10),
    Variant("quiet_24db", 2, "gain", -24),
)


@dataclass(frozen=True, slots=True)
class Cohort:
    asset: Asset
    stratum: str
    expected_id: str
    distractor_id: str
    expose_id: bool
    start_half_seconds: int
    seed: int


@dataclass(frozen=True, slots=True)
class Split:
    index: list[Asset]
    cohorts: list[Cohort]


@dataclass(frozen=True, slots=True)
class Trial:
    query_id: str
    query_path: str
    variant: str
    kind: str
    source_asset_id: str
    source_id: str
    stratum: str
    label: str
    provenance_service: str
    provenance_id: str
    expected_id: str
    distractor_id: str
    offset_samples: int
    source_rate: int
    seed: int
    sha256: str
    exclusion_reason: str = ""

    @property
    def expected_offset(self) -> float:
        return self.offset_samples / self.source_rate


TRIAL_COLUMNS = tuple(field.name for field in fields(Trial))


def read_trials(path: Path) -> list[Trial]:
    trials = []
    seen = set()
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv_rows(file, TRIAL_COLUMNS, name=str(path)):
            for field in ("offset_samples", "source_rate", "seed"):
                row[field] = int(row[field])
            trial = Trial(**{name: row[name] for name in TRIAL_COLUMNS})
            if trial.query_id in seen or not trial.query_id:
                raise ValueError(
                    f"{path}: duplicate or empty query ID {trial.query_id!r}"
                )
            if trial.kind not in {"positive", "absent"} or bool(trial.expected_id) != (
                trial.kind == "positive"
            ):
                raise ValueError(f"{trial.query_id}: inconsistent ground truth")
            if trial.offset_samples < 0 or trial.source_rate <= 0:
                raise ValueError(
                    f"{trial.query_id}: invalid crop offset or sample rate"
                )
            seen.add(trial.query_id)
            trials.append(trial)
    return trials


def development_sources(path: Path) -> set[str]:
    sources = {item.source_id for item in read_manifest(path / "index.csv")}
    with (path / "queries.csv").open(newline="", encoding="utf-8") as file:
        sources.update(
            row["source_id"]
            for row in csv_rows(file, ("source_id",), name="development queries")
        )
    return sources


def plan_splits(
    assets: list[Asset],
    excluded: set[str],
    *,
    seed: int,
    groups_per_label_and_kind: int,
    background_references_per_split: int,
) -> dict[str, Split]:
    if groups_per_label_and_kind < 1 or background_references_per_split < 0:
        raise ValueError("split sizes must allow at least one group per label and kind")
    if any(
        item.dataset != "esc50" or item.source_service != "freesound" or not item.sha256
        for item in assets
    ):
        raise ValueError("evaluation requires a verified ESC-50 inventory")

    rng = Random(seed)
    pool = sorted(assets, key=lambda item: item.asset_id)
    rng.shuffle(pool)
    used_sources = set(excluded)
    used_digests = {item.sha256 for item in pool if item.source_id in excluded}
    by_label = defaultdict(list)
    for item in pool:
        by_label[item.label].append(item)

    def select(candidates, description):
        for item in candidates:
            if item.source_id not in used_sources and item.sha256 not in used_digests:
                used_sources.add(item.source_id)
                used_digests.add(item.sha256)
                return item
        raise ValueError(f"insufficient eligible source groups for {description}")

    # Reserve labeled groups in both splits before sampling background.
    chosen = {}
    for split in SPLITS:
        pairs = []
        for stratum, labels in STRATA.items():
            for label in labels:
                for _ in range(groups_per_label_and_kind):
                    pairs.append(
                        (
                            stratum,
                            select(by_label[label], f"{split} {label} positive"),
                            select(by_label[label], f"{split} {label} absent control"),
                        )
                    )
        chosen[split] = pairs

    design = {}
    for split, pairs in chosen.items():
        references = [positive for _, positive, _ in pairs]
        references.extend(
            select(pool, f"{split} background")
            for _ in range(background_references_per_split)
        )
        rng.shuffle(references)
        index = [
            replace(item, asset_id=f"recording-{number:04}", role="index")
            for number, item in enumerate(references, start=1)
        ]
        keys = {item.source_id: item.asset_id for item in index}
        cohorts = []
        for pair_number, (stratum, positive, absent) in enumerate(pairs):
            match_id = keys[positive.source_id]
            exposed = pair_number % 2 == 0
            cohorts.extend(
                [
                    Cohort(
                        positive,
                        stratum,
                        match_id,
                        "",
                        exposed,
                        rng.randint(1, 2),
                        rng.getrandbits(32),
                    ),
                    Cohort(
                        absent,
                        stratum,
                        "",
                        match_id,
                        exposed,
                        rng.randint(1, 2),
                        rng.getrandbits(32),
                    ),
                ]
            )
        rng.shuffle(cohorts)
        design[split] = Split(index, cohorts)
    return design


def get_ffmpeg() -> str:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError as error:
        raise ValueError(
            "install the benchmark dependency group with uv sync --group benchmark --locked"
        ) from error
    return get_ffmpeg_exe()


def mp3_encode(ffmpeg: str, source: Path, destination: Path, kbps: int) -> None:
    command = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-b:a",
        f"{kbps}k",
        str(destination),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def write_variant(path, original_path, audio, start, variant, seed, ffmpeg, scratch):
    if variant.transform == "copy":
        shutil.copyfile(original_path, path)
        return
    length = variant.seconds * audio.sample_rate
    samples = audio.samples[start : start + length]
    if len(samples) != length:
        raise ValueError("crop does not fit the decoded recording")

    rate = audio.sample_rate
    if variant.transform == "resample":
        sf.write(scratch, samples, rate, subtype="PCM_16")
        rate = variant.value
        samples = load_audio(scratch, target_rate=rate).samples
    elif variant.transform == "snr":
        noise = np.random.default_rng(seed).standard_normal(samples.size)
        signal_rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        noise_rms = np.sqrt(np.mean(noise**2))
        samples = samples + noise * (signal_rms / noise_rms) * 10 ** (
            -variant.value / 20
        )
        peak = float(np.max(np.abs(samples)))
        if peak > 0.999:
            samples = samples * (0.999 / peak)
    elif variant.transform == "gain":
        samples = samples * 10 ** (variant.value / 20)
    elif variant.transform == "mp3":
        sf.write(scratch, samples, rate, subtype="PCM_16")
        mp3_encode(ffmpeg, scratch, path, variant.value)
        return
    sf.write(path, samples, rate, subtype="PCM_16")


def write_split(root: Path, target: Path, split: Split, ffmpeg: str) -> dict:
    target.mkdir()
    query_dir = target / "audio"
    query_dir.mkdir()
    index_path = target / "index.csv"
    query_path = target / "queries.csv"
    scratch = target / "scratch.wav"
    write_manifest(index_path, split.index)

    with query_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, TRIAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for number, cohort in enumerate(split.cohorts, start=1):
            asset = cohort.asset
            original = asset.local_path(root)
            if sha256_file(original) != asset.sha256:
                raise ValueError(
                    f"{asset.asset_id}: recording differs from verified inventory"
                )
            audio = load_audio(original)
            for variant in VARIANTS:
                query_id = f"q-{number:03}-{variant.name}"
                suffix = ".mp3" if variant.transform == "mp3" else ".wav"
                path = query_dir / (query_id + suffix)
                start = (
                    cohort.start_half_seconds * audio.source_rate // 2
                    if variant.seconds
                    else 0
                )
                reason = ""
                if (
                    variant.seconds
                    and start + variant.seconds * audio.source_rate
                    > audio.source_frames
                ):
                    reason = "crop does not fit the source recording"
                else:
                    write_variant(
                        path,
                        original,
                        audio,
                        start,
                        variant,
                        cohort.seed,
                        ffmpeg,
                        scratch,
                    )
                trial = Trial(
                    query_id,
                    path.relative_to(target).as_posix(),
                    variant.name,
                    "positive" if cohort.expected_id else "absent",
                    asset.asset_id,
                    asset.source_id,
                    cohort.stratum,
                    asset.label,
                    asset.source_service if cohort.expose_id else "",
                    asset.source_id if cohort.expose_id else "",
                    cohort.expected_id,
                    cohort.distractor_id,
                    start,
                    audio.source_rate,
                    cohort.seed,
                    "" if reason else sha256_file(path),
                    reason,
                )
                writer.writerow(asdict(trial))
    scratch.unlink(missing_ok=True)
    return {
        "index_sha256": sha256_file(index_path),
        "queries_sha256": sha256_file(query_path),
        "indexed_references": len(split.index),
        "positive_source_groups": sum(bool(row.expected_id) for row in split.cohorts),
        "absent_source_groups": sum(not row.expected_id for row in split.cohorts),
        "planned_trials": len(split.cohorts) * len(VARIANTS),
    }


def prepare(
    root: Path, inventory: Path, development: Path, spec: Path, out: Path
) -> dict:
    settings = json.loads(spec.read_text(encoding="utf-8"))
    excluded = development_sources(development)
    design = plan_splits(read_manifest(inventory), excluded, **settings)
    ffmpeg = get_ffmpeg()
    version = subprocess.check_output([ffmpeg, "-version"], text=True).splitlines()[0]
    with new_output_directory(out):
        summary = {
            "schema_version": 1,
            "spec": settings,
            "spec_sha256": sha256_file(spec),
            "inventory_sha256": sha256_file(inventory),
            "stage2_excluded_source_groups": len(excluded),
            "stage2_index_sha256": sha256_file(development / "index.csv"),
            "stage2_queries_sha256": sha256_file(development / "queries.csv"),
            "ffmpeg": version,
            "variants": [asdict(variant) for variant in VARIANTS],
            "splits": {
                split: write_split(root, out / split, plan, ffmpeg)
                for split, plan in design.items()
            },
        }
        write_json(out / "design.json", summary)
    return summary


def design_digest(design: dict) -> str:
    encoded = json.dumps(design, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
