"""Freeze grouped ESC-50 splits and prepare same-class exposure swaps."""

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from random import Random

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.datasets import ESC50_REVISION, Asset, csv_rows, read_manifest, write_manifest


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    schema_version: int
    selection_seed: int
    max_crops_per_class: int
    crop_seconds: int
    calibration_seed: int
    paired_seeds: list[int]
    learning_rates: list[float]
    epochs: int
    batch_size: int
    cpu_threads: int

    def __post_init__(self) -> None:
        positive = (
            self.max_crops_per_class,
            self.crop_seconds,
            self.epochs,
            self.batch_size,
            self.cpu_threads,
        )
        seeds = [self.selection_seed, self.calibration_seed, *self.paired_seeds]
        if (
            self.schema_version != 1
            or any(type(value) is not int or value < 1 for value in positive)
            or not 1 <= self.crop_seconds < 5
            or len(self.paired_seeds) < 3
            or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)
            or len(set(seeds)) != len(seeds)
            or not self.learning_rates
            or any(not 0 < rate < 1 for rate in self.learning_rates)
            or len(set(self.learning_rates)) != len(self.learning_rates)
        ):
            raise ValueError("invalid Stage 5 selection or training specification")


@dataclass(frozen=True, slots=True)
class Pairing:
    slot: str
    label: str
    test: Asset
    donor: Asset
    test_group: str
    donor_group: str


@dataclass(frozen=True, slots=True)
class Crop:
    slot: str
    arm: str
    label: str
    original_id: str
    group: str
    path: str
    start_sample: int
    frames: int
    sample_rate: int
    pcm_sum_squares: int
    sha256: str


CROP_COLUMNS = tuple(field.name for field in fields(Crop))
EXCLUSION_COLUMNS = ("asset_id", "group", "fold", "reason")
SPLIT_NAMES = ("test", "validation", "train_base", "donors")
ARMS = ("comparison", "exposed")
CROP_POLICY = "native_pcm16_maximum_energy_crop_center_then_earliest_tie"


@dataclass(frozen=True, slots=True)
class Splits:
    groups: dict[str, str]
    assets: dict[str, list[Asset]]
    pairs: list[Pairing]
    exclusions: list[dict]


@dataclass(frozen=True, slots=True)
class ExperimentDesign:
    spec: ExperimentSpec
    metadata: dict
    splits: Splits
    crops: dict[str, list[Crop]]


def recording_groups(assets: list[Asset]) -> dict[str, str]:
    """Join original source IDs and byte-identical WAVs transitively."""
    parent = {asset.source_id: asset.source_id for asset in assets}

    def find(source):
        while source != parent[source]:
            parent[source] = parent[parent[source]]
            source = parent[source]
        return source

    by_hash = {}
    for asset in assets:
        original = by_hash.setdefault(asset.sha256, asset.source_id)
        first, second = sorted((find(asset.source_id), find(original)))
        parent[second] = first
    return {asset.asset_id: f"freesound:{find(asset.source_id)}" for asset in assets}


def make_plan(assets: list[Asset], spec: ExperimentSpec) -> Splits:
    if not assets or any(
        a.dataset != "esc50"
        or a.revision != ESC50_REVISION
        or a.source_service != "freesound"
        or not a.source_id
        or not a.sha256
        or not a.label
        or a.fold not in {"1", "2", "3", "4", "5"}
        for a in assets
    ):
        raise ValueError("expected a checksummed ESC-50 inventory with recording IDs")
    groups = recording_groups(assets)
    group = lambda asset: groups[asset.asset_id]
    partitions = {name: [] for name in SPLIT_NAMES}
    assignment = {}
    exclusions = []
    for asset in sorted(assets, key=lambda a: (a.fold, a.asset_id)):
        partition = {"1": "test", "2": "validation"}.get(asset.fold, "train_base")
        owner = assignment.setdefault(group(asset), partition)
        if partition == owner:
            partitions[partition].append(asset)
        else:
            exclusions.append(
                {
                    "asset_id": asset.asset_id,
                    "group": group(asset),
                    "fold": asset.fold,
                    "reason": f"precedence_{owner}",
                }
            )
    test, val, train = (partitions[key] for key in SPLIT_NAMES[:3])
    classes = sorted({asset.label for asset in test})
    if not classes or any(
        {asset.label for asset in split} != set(classes) for split in (val, train)
    ):
        raise ValueError("test, validation, and training must cover the same classes")

    rng = Random(spec.selection_seed)
    test_count = Counter(map(group, test))
    test_by_label = defaultdict(list)
    train_by_label = defaultdict(list)
    for asset in test:
        if test_count[group(asset)] == 1:
            test_by_label[asset.label].append(asset)
    for asset in train:
        train_by_label[asset.label].append(asset)

    pairs = []
    reserved = set()
    test_classes = Counter(a.label for a in test)
    for label in classes:
        eligible = test_by_label[label]
        count = min(spec.max_crops_per_class, len(eligible), test_classes[label] - 1)
        if count == 0:
            continue
        chosen = rng.sample(eligible, count)
        candidates = train_by_label[label].copy()
        rng.shuffle(candidates)
        donors = []
        for asset in candidates:
            if group(asset) in reserved:
                continue
            reserved.add(group(asset))
            donors.append(asset)
            if len(donors) == count:
                break
        if len(donors) != count:
            raise ValueError(
                f"{label}: cannot assign distinct independent donor groups"
            )
        for exposed, donor in zip(chosen, donors, strict=True):
            pairs.append(
                Pairing(
                    f"slot-{len(pairs) + 1:03}",
                    label,
                    exposed,
                    donor,
                    group(exposed),
                    group(donor),
                )
            )

    if not pairs:
        raise ValueError("test set has no eligible single-row exposure groups")
    partitions["donors"] = [pair.donor for pair in pairs]
    donor_ids = {a.asset_id for a in partitions["donors"]}
    partitions["train_base"] = [
        asset for asset in train if group(asset) not in reserved
    ]
    for asset in train:
        if group(asset) in reserved and asset.asset_id not in donor_ids:
            exclusions.append(
                {
                    "asset_id": asset.asset_id,
                    "group": group(asset),
                    "fold": asset.fold,
                    "reason": "reserved_donor_group",
                }
            )
    if {a.label for a in partitions["train_base"]} != set(classes):
        raise ValueError(
            "donor reservation removed a class from the common training base"
        )
    return Splits(groups, partitions, pairs, exclusions)


def split_validation(plan: Splits) -> dict:
    groups = {
        name: {plan.groups[a.asset_id] for a in assets}
        for name, assets in plan.assets.items()
    }
    expected = {pair.test_group for pair in plan.pairs}
    comparison = groups["train_base"] | groups["donors"]
    exposed = groups["train_base"] | expected
    if (
        groups["test"] & groups["validation"]
        or groups["train_base"] & groups["donors"]
        or comparison & (groups["test"] | groups["validation"])
        or exposed & groups["validation"]
        or exposed & groups["test"] != expected
        or len(expected) != len(plan.pairs)
        or len(groups["donors"]) != len(plan.pairs)
    ):
        raise ValueError(
            "recording groups violate the declared train/validation/test separation"
        )
    a = Counter(row.label for row in plan.assets["train_base"])
    b = a + Counter(pair.test.label for pair in plan.pairs)
    if b != a + Counter(pair.donor.label for pair in plan.pairs):
        raise ValueError("paired arms have different training class counts")
    return {
        "rows": {name: len(assets) for name, assets in plan.assets.items()},
        "groups": {name: len(values) for name, values in groups.items()},
        "confirmation": {
            "comparison_train_test_groups": [],
            "training_validation_groups": [],
            "validation_test_groups": [],
            "intentional_exposure_groups": sorted(expected),
            "exposed_train_test_groups": sorted(exposed & groups["test"]),
        },
        "training_rows_per_arm": b.total(),
        "training_class_counts_per_arm": dict(b),
        "test_class_counts": dict(Counter(row.label for row in plan.assets["test"])),
        "directly_exposed_per_class": dict(Counter(pair.label for pair in plan.pairs)),
        "directly_exposed_test_rows": len(plan.pairs),
        "unexposed_test_rows": len(plan.assets["test"]) - len(plan.pairs),
        "exclusions_by_reason": dict(Counter(row["reason"] for row in plan.exclusions)),
    }


def checked_audio(asset: Asset, root: Path) -> Path:
    file = asset.local_path(root)
    if sha256_file(file) != asset.sha256:
        raise ValueError(f"{asset.asset_id}: WAV differs from its recorded SHA-256")
    return file


def make_crop(
    pair: Pairing,
    arm: str,
    asset: Asset,
    group: str,
    root: Path,
    out: Path,
    seconds: int,
) -> Crop:
    source = checked_audio(asset, root)
    path = f"crops/{arm}/{pair.slot}.wav"
    with sf.SoundFile(source) as wave:
        if wave.format != "WAV" or wave.subtype != "PCM_16":
            raise ValueError(f"{asset.asset_id}: expected native PCM-16 WAV")
        rate = wave.samplerate
        frames = seconds * rate
        if wave.frames < frames:
            raise ValueError(
                f"{asset.asset_id}: recording is too short for the frozen crop"
            )
        original = wave.read(dtype="int16", always_2d=True)
    frame_energy = np.sum(original.astype(np.int64) ** 2, axis=1)
    energy = np.concatenate(([0], np.cumsum(frame_energy, dtype=np.int64)))
    window_energy = energy[frames:] - energy[:-frames]
    max_energy = int(window_energy.max())
    if not max_energy:
        raise ValueError(f"{asset.asset_id}: recording is silent throughout")
    strongest = np.flatnonzero(window_energy == max_energy)
    middle = (len(original) - frames) // 2
    start = int(strongest[np.abs(strongest - middle).argmin()])
    samples = original[start : start + frames]
    sf.write(out / path, samples, rate, subtype="PCM_16")
    return Crop(
        pair.slot,
        arm,
        pair.label,
        asset.asset_id,
        group,
        path,
        start,
        frames,
        rate,
        max_energy,
        sha256_file(out / path),
    )


def prepare_design(inventory: Path, root: Path, spec_path: Path, out: Path) -> dict:
    spec = ExperimentSpec(**json.loads(spec_path.read_text(encoding="utf-8")))
    plan = make_plan(read_manifest(inventory), spec)
    validation = split_validation(plan)
    with new_output_directory(out):
        for arm in ARMS:
            (out / "crops" / arm).mkdir(parents=True)
        for name, assets in plan.assets.items():
            write_manifest(out / f"{name}.csv", assets)
        write_csv(out / "exclusions.csv", EXCLUSION_COLUMNS, plan.exclusions)
        crops = []
        for pair in plan.pairs:
            crops.append(
                make_crop(
                    pair,
                    "comparison",
                    pair.donor,
                    pair.donor_group,
                    root,
                    out,
                    spec.crop_seconds,
                )
            )
            crops.append(
                make_crop(
                    pair,
                    "exposed",
                    pair.test,
                    pair.test_group,
                    root,
                    out,
                    spec.crop_seconds,
                )
            )
        write_csv(out / "crops.csv", CROP_COLUMNS, (asdict(crop) for crop in crops))
        report = {
            "schema_version": 1,
            "dataset_revision": ESC50_REVISION,
            "inventory_sha256": sha256_file(inventory),
            "spec_sha256": sha256_file(spec_path),
            "spec": asdict(spec),
            "policy": CROP_POLICY,
            "files": {f.name: sha256_file(f) for f in sorted(out.glob("*.csv"))},
            "validation": validation,
        }
        write_json(out / "design.json", report)
    return report


def read_experiment_design(path: Path, inventory: Path) -> ExperimentDesign:
    metadata = json.loads((path / "design.json").read_text(encoding="utf-8"))
    files = {f"{name}.csv" for name in SPLIT_NAMES} | {"crops.csv", "exclusions.csv"}
    if (
        metadata["schema_version"] != 1
        or metadata["policy"] != CROP_POLICY
        or metadata["inventory_sha256"] != sha256_file(inventory)
        or metadata["files"].keys() != files
        or any(
            sha256_file(path / file) != digest
            for file, digest in metadata["files"].items()
        )
    ):
        raise ValueError(
            "experimental design or inventory differs from its frozen checksums"
        )
    spec = ExperimentSpec(**metadata["spec"])
    plan = make_plan(read_manifest(inventory), spec)
    if metadata["validation"] != split_validation(plan) or any(
        read_manifest(path / f"{name}.csv") != plan.assets[name] for name in SPLIT_NAMES
    ):
        raise ValueError(
            "frozen experiment split differs from its recording-group plan"
        )
    with (path / "crops.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv_rows(file, CROP_COLUMNS, name=str(file.name)))
    crops = {arm: [] for arm in ARMS}
    if len(rows) != 2 * len(plan.pairs):
        raise ValueError("expected two crop rows per paired slot")
    for pair, (comparison, exposure) in zip(
        plan.pairs, zip(rows[::2], rows[1::2], strict=True), strict=True
    ):
        for row, arm, asset, group in (
            (comparison, "comparison", pair.donor, pair.donor_group),
            (exposure, "exposed", pair.test, pair.test_group),
        ):
            for key in ("start_sample", "frames", "sample_rate", "pcm_sum_squares"):
                row[key] = int(row[key])
            item = Crop(**{key: row[key] for key in CROP_COLUMNS})
            if (
                (
                    item.slot,
                    item.arm,
                    item.label,
                    item.original_id,
                    item.group,
                    item.path,
                )
                != (
                    pair.slot,
                    arm,
                    pair.label,
                    asset.asset_id,
                    group,
                    f"crops/{arm}/{pair.slot}.wav",
                )
                or item.start_sample < 0
                or item.sample_rate <= 0
                or item.pcm_sum_squares <= 0
                or item.frames != spec.crop_seconds * item.sample_rate
            ):
                raise ValueError(
                    f"{pair.slot}: crop row differs from the frozen paired slot policy"
                )
            crops[arm].append(item)
    return ExperimentDesign(spec, metadata, plan, crops)
