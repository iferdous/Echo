"""Freeze and acquire a reproducible official FSD50K eval cohort."""

import hashlib
import io
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from random import Random
from shutil import copyfile
from zipfile import ZipFile

from echo.acquisition import verify_digest
from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.audio import load_audio
from echo.datasets import (
    FSD50K_GROUND_TRUTH_SHA256,
    FSD50K_REVISION,
    Asset,
    csv_rows,
    read_fsd50k_partitions,
    read_manifest,
    write_manifest,
)
from echo.evaluation import read_design
from echo.evaluation_data import development_sources
from echo.fsd_archive import PART_URL, PARTS, SplitArchive, ZenodoRanges

METADATA_MD5 = "b9ea0c829a411c1d42adb9da539ed237"
ACQUISITION_COLUMNS = (
    "reference_id",
    "fsd_source_id",
    "cohort",
    "status",
    "bytes",
    "sha256",
    "source_url",
    "license",
    "archive_part",
    "zip_crc32",
    "duration_seconds",
    "message",
)


def eval_labels(path: Path) -> dict[str, tuple[str, ...]]:
    verify_digest(path, FSD50K_GROUND_TRUTH_SHA256)
    labels = {}
    with (
        ZipFile(path) as archive,
        archive.open("FSD50K.ground_truth/eval.csv") as member,
        io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as file,
    ):
        for row in csv_rows(file, ("fname", "labels"), name="FSD50K eval"):
            source = row["fname"]
            if (
                not re.fullmatch(r"[0-9]+", source)
                or source in labels
                or not row["labels"]
            ):
                raise ValueError(f"invalid FSD50K eval row for {source!r}")
            labels[source] = tuple(row["labels"].split(","))
    return labels


def plan_cohort(
    esc: list[Asset], fsd: dict[str, tuple[str, ...]], prior: set[str], spec: dict
) -> tuple[list[Asset], list[Asset], list[dict]]:
    rng = Random(spec["seed"])
    shared = sorted(
        (item for item in esc if item.source_id in fsd), key=lambda item: item.asset_id
    )
    queries = [replace(item, role="shared_eval_id") for item in shared]
    reference_roles = {item.source_id: "shared_eval_id" for item in shared}
    if any(
        item.dataset != "esc50" or item.source_service != "freesound" or not item.sha256
        for item in esc
    ):
        raise ValueError(
            "the ESC-50 input must be a verified inventory with Freesound IDs"
        )
    all_esc_sources = {item.source_id for item in esc}
    allowed_esc = sorted(
        (
            item
            for item in esc
            if item.source_id not in fsd and item.source_id not in prior
        ),
        key=lambda item: item.asset_id,
    )
    allowed_fsd = sorted(set(fsd) - all_esc_sources - prior)
    rng.shuffle(allowed_esc)
    rng.shuffle(allowed_fsd)
    used_esc = set()
    class_coverage = []

    def choose_esc(candidates, count, role):
        taken = 0
        for item in candidates:
            if taken == count:
                break
            if item.source_id not in used_esc:
                used_esc.add(item.source_id)
                queries.append(replace(item, role=role))
                taken += 1
        return taken

    for esc_label, fsd_label in sorted(spec["class_map"].items()):
        fsd_pool = [source for source in allowed_fsd if fsd_label in fsd[source]]
        if not fsd_pool:
            raise ValueError(f"no official eval clips tagged {fsd_label}")
        # Reuse a multilabel reference across class controls instead of indexing it twice.
        selected = fsd_pool[: spec["class_references_per_label"]]
        for source in selected:
            reference_roles[source] = "class_distractor"
        selected_queries = choose_esc(
            (item for item in allowed_esc if item.label == esc_label),
            spec["class_queries_per_label"],
            "same_class_control",
        )
        class_coverage.append(
            {
                "esc50_label": esc_label,
                "fsd50k_label": fsd_label,
                "reference_source_ids": selected,
                "query_count": selected_queries,
            }
        )

    candidates = [source for source in allowed_fsd if source not in reference_roles]
    if len(candidates) < spec["background_references"]:
        raise ValueError("not enough distinct FSD50K background references")
    reference_roles.update(
        (source, "background") for source in candidates[: spec["background_references"]]
    )
    if (
        choose_esc(allowed_esc, spec["background_queries"], "background_control")
        != spec["background_queries"]
    ):
        raise ValueError("not enough independent ESC-50 background queries")

    ids = sorted(reference_roles)
    rng.shuffle(ids)
    references = [
        Asset(
            f"reference-{number:04}",
            "fsd50k",
            FSD50K_REVISION,
            f"audio/{source}.wav",
            reference_roles[source],
            "freesound",
            source,
            "|".join(fsd[source]),
            "eval",
            attribution=f"https://freesound.org/s/{source}/",
        )
        for number, source in enumerate(ids, start=1)
    ]
    return references, queries, class_coverage


def prepare_cohort(
    esc_inventory: Path,
    ground_truth: Path,
    stage2: Path,
    stage3: Path,
    spec_path: Path,
    out: Path,
) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if any(
        type(spec[key]) is not int or spec[key] < 1
        for key in (
            "class_queries_per_label",
            "class_references_per_label",
            "background_queries",
            "background_references",
        )
    ):
        raise ValueError("cohort sample sizes must be positive integers")
    design, partitions = read_design(stage3)
    prior = development_sources(stage2) | set.union(
        *(part.source_ids for part in partitions.values())
    )
    esc = read_manifest(esc_inventory)
    fsd = eval_labels(ground_truth)
    refs, queries, coverage = plan_cohort(esc, fsd, prior, spec)
    all_fsd_ids = set(read_fsd50k_partitions(ground_truth))
    with new_output_directory(out):
        references = out / "references.csv"
        query_manifest = out / "queries.csv"
        write_manifest(references, refs)
        write_manifest(query_manifest, queries)
        summary = {
            "schema_version": 1,
            "fsd50k_revision": FSD50K_REVISION,
            "fsd50k_partition": "eval",
            "spec": spec,
            "spec_sha256": sha256_file(spec_path),
            "esc_inventory_sha256": sha256_file(esc_inventory),
            "ground_truth_sha256": sha256_file(ground_truth),
            "stage3_design_sha256": sha256_file(stage3 / "design.json"),
            "stage2_queries_sha256": sha256_file(stage2 / "queries.csv"),
            "stage2_index_sha256": sha256_file(stage2 / "index.csv"),
            "stage3_seed": design["spec"]["seed"],
            "references_sha256": sha256_file(references),
            "queries_sha256": sha256_file(query_manifest),
            "full_esc50_rows": len(esc),
            "official_eval_sources": len(fsd),
            "all_fsd_partitions_shared_rows": sum(
                item.source_id in all_fsd_ids for item in esc
            ),
            "index_cohorts": dict(Counter(item.role for item in refs)),
            "query_cohorts": dict(Counter(item.role for item in queries)),
            "shared_eval_unique_sources": len(
                {item.source_id for item in queries if item.role == "shared_eval_id"}
            ),
            "previously_seen_query_sources": sorted(
                {item.source_id for item in queries if item.source_id in prior}
            ),
            "all_prior_source_groups": len(prior),
            "class_controls": coverage,
        }
        write_json(out / "cohort.json", summary)
    return summary


def read_cohort(path: Path) -> tuple[dict, list[Asset], list[Asset]]:
    cohort = json.loads((path / "cohort.json").read_text(encoding="utf-8"))
    refs, queries = path / "references.csv", path / "queries.csv"
    if cohort.get("schema_version") != 1 or (
        sha256_file(refs) != cohort["references_sha256"]
        or sha256_file(queries) != cohort["queries_sha256"]
    ):
        raise ValueError("cohort manifests differ from their frozen checksums")
    return cohort, read_manifest(refs), read_manifest(queries)


def read_licenses(path: Path) -> dict:
    with path.open("rb") as file:
        digest = hashlib.file_digest(file, "md5").hexdigest()
    if digest != METADATA_MD5:
        raise ValueError("FSD50K metadata archive differs from the Zenodo MD5")
    with ZipFile(path) as archive:
        return json.loads(archive.read("FSD50K.metadata/eval_clips_info_FSD50K.json"))


def collect_member(asset, root, archive, catalog, licenses):
    row = {
        "reference_id": asset.asset_id,
        "fsd_source_id": asset.source_id,
        "cohort": asset.role,
        "source_url": asset.attribution,
        "license": licenses.get(asset.source_id, {}).get("license", ""),
    }
    path = asset.local_path(root)
    try:
        member = catalog[asset.source_id]
        data = archive.extract(member)
        path.write_bytes(data)
        audio = load_audio(path)
    except (OSError, ValueError, KeyError) as error:
        path.unlink(missing_ok=True)
        return None, {**row, "status": "unavailable", "message": str(error)}
    checksummed = replace(asset, sha256=hashlib.sha256(data).hexdigest())
    return checksummed, {
        **row,
        "status": "available",
        "bytes": len(data),
        "sha256": checksummed.sha256,
        "archive_part": PARTS[member.disk][0],
        "zip_crc32": f"{member.checksum:08x}",
        "duration_seconds": audio.source_duration,
    }


def read_acquisition(
    root: Path, cohort_path: Path, references: list[Asset]
) -> tuple[dict, dict[str, Asset], dict[str, dict]]:
    summary = json.loads((root / "acquisition.json").read_text(encoding="utf-8"))
    digests = {
        "cohort_sha256": cohort_path / "cohort.json",
        "index_sha256": root / "index.csv",
        "acquisition_sha256": root / "acquisition.csv",
    }
    if summary.get("schema_version") != 1 or any(
        summary[key] != sha256_file(path) for key, path in digests.items()
    ):
        raise ValueError("acquisition differs from its recorded checksums")
    available = {asset.asset_id: asset for asset in read_manifest(root / "index.csv")}
    with digests["acquisition_sha256"].open(encoding="utf-8", newline="") as file:
        records = list(csv_rows(file, ACQUISITION_COLUMNS, name=str(file.name)))
    rows = {row["reference_id"]: row for row in records}
    if (
        len(records) != len(references)
        or rows.keys() != {asset.asset_id for asset in references}
        or len(available) != summary["available_references"]
        or len(references) != summary["selected_references"]
        or len(references) - len(available) != summary["unavailable_references"]
        or available.keys()
        != {key for key, row in rows.items() if row["status"] == "available"}
    ):
        raise ValueError(
            "acquisition counts or reference IDs differ from the frozen cohort"
        )
    for asset in references:
        row = rows[asset.asset_id]
        indexed = available.get(asset.asset_id)
        if row["fsd_source_id"] != asset.source_id or row["cohort"] != asset.role:
            raise ValueError(f"{asset.asset_id}: inconsistent acquisition metadata")
        if indexed and (
            not indexed.sha256
            or indexed.sha256 != row["sha256"]
            or indexed != replace(asset, sha256=indexed.sha256)
        ):
            raise ValueError(
                f"{asset.asset_id}: index manifest differs from the frozen reference"
            )
    return summary, available, rows


def acquire_cohort(
    cohort_path: Path, metadata_zip: Path, out: Path, *, resume: Path | None = None
) -> dict:
    cohort, references, _ = read_cohort(cohort_path)
    licenses = read_licenses(metadata_zip)
    source = ZenodoRanges()
    archive = SplitArchive(source.sizes, source.read)
    catalog = archive.catalog()
    if (
        len(catalog) != cohort["official_eval_sources"]
        or catalog.keys() != licenses.keys()
    ):
        raise ValueError(
            "ZIP catalog and official eval metadata contain different recording IDs"
        )
    prior, existing, previous_rows = (
        read_acquisition(resume, cohort_path, references) if resume else ({}, {}, {})
    )
    with new_output_directory(out):
        (out / "audio").mkdir()
        for asset in existing.values():
            target = asset.local_path(out)
            copyfile(asset.local_path(resume), target)
            if sha256_file(target) != asset.sha256:
                raise ValueError(f"{asset.asset_id}: previously acquired WAV changed")

        pending = [asset for asset in references if asset.asset_id not in existing]
        with ThreadPoolExecutor(max_workers=2 if resume else 6) as workers:
            retry_results = {
                asset.asset_id: result
                for asset, result in zip(
                    pending,
                    workers.map(
                        lambda asset: collect_member(
                            asset, out, archive, catalog, licenses
                        ),
                        pending,
                    ),
                    strict=True,
                )
            }
        results = {key: (asset, previous_rows[key]) for key, asset in existing.items()}
        results.update(retry_results)
        ordered = [results[asset.asset_id] for asset in references]
        verified = [asset for asset, _ in ordered if asset is not None]
        rows = [row for _, row in ordered]
        manifest = out / "index.csv"
        write_manifest(manifest, verified)
        write_csv(out / "acquisition.csv", ACQUISITION_COLUMNS, rows)
        summary = {
            "schema_version": 1,
            "method": "official_split_zip_http_ranges",
            "catalog_entries": len(catalog),
            "cohort_sha256": sha256_file(cohort_path / "cohort.json"),
            "index_sha256": sha256_file(manifest),
            "acquisition_sha256": sha256_file(out / "acquisition.csv"),
            "metadata_md5": METADATA_MD5,
            "parts": [
                {"url": PART_URL.format(name=name), "bytes": size, "published_md5": md5}
                for name, size, md5 in PARTS
            ],
            "archive_payload_bytes_received": prior.get(
                "archive_payload_bytes_received", 0
            )
            + source.payload_bytes,
            "range_responses": prior.get("range_responses", 0) + source.requests,
            "previously_available_references": len(existing),
            "retried_references": len(pending) if resume else 0,
            "selected_references": len(references),
            "available_references": len(verified),
            "unavailable_references": len(references) - len(verified),
            "wav_bytes_kept": sum(int(row.get("bytes") or 0) for row in rows),
        }
        write_json(out / "acquisition.json", summary)
    return summary
