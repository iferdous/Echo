"""Portable inputs and checksums for the fixture and published benchmark runs."""

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from echo.artifacts import write_json
from echo.datasets import csv_rows

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024

PUBLIC_RESULTS = (
    "stage-1-inventory.json",
    "stage-1-overlap.json",
    "stage-2-global-summary.json",
    "stage-2-global-queries.csv",
    "stage-2-local-summary.json",
    "stage-2-local-queries.csv",
    "stage-3-design.json",
    "stage-3-policy.json",
    "stage-3-calibration.json",
    "stage-3-calibration-summary.json",
    "stage-3-calibration-queries.csv",
    "stage-3-test-summary.json",
    "stage-3-test-queries.csv",
    "stage-4-cohort.json",
    "stage-4-acquisition.json",
    "stage-4-acquisition.csv",
    "stage-4-index-manifest.csv",
    "stage-4-reference-manifest.csv",
    "stage-4-query-manifest.csv",
    "stage-4-summary.json",
    "stage-4-batch-queries.csv",
    "stage-4-audit-queries.csv",
    "stage-4-candidates.csv",
    "stage-4-reviews.csv",
    "stage-4-example.json",
    "stage-5-calibration.json",
    "stage-5-smoke.json",
    "stage-5-summary.json",
    "stage-5-per-class.csv",
    "stage-5-predictions.csv",
    "stage-5-training.csv",
    "stage-5-verification.json",
    *(
        f"stage-5-design/{name}"
        for name in (
            "design.json",
            "crops.csv",
            "donors.csv",
            "exclusions.csv",
            "test.csv",
            "train_base.csv",
            "validation.csv",
        )
    ),
    "stage-6/comparison.json",
    *(
        f"stage-6/{name}.{ext}"
        for name in (
            "baseline-stage2",
            "baseline-stage4",
            "build-stage2",
            "build-stage4",
            "rust-stage2",
            "rust-stage2-first-pass",
            "rust-stage4",
            "tuned-stage2",
            "tuned-stage2-first-pass",
            "tuned-stage4",
        )
        for ext in ("csv", "json")
    ),
    "stage-6/cli-parity.json",
    "stage-6/full-parity.json",
)
SPECS = (
    "bench/stage3-spec.json",
    "bench/stage4-spec.json",
    "bench/stage5-spec.json",
    "bench/stage6-protocol.md",
    "bench/stage6-stage2-queries.csv",
    "bench/stage6-stage4-queries.csv",
)
PUBLIC_FILES = (
    tuple(f"results/{name}" for name in PUBLIC_RESULTS)
    + SPECS
    + (".python-version", "uv.lock")
)
FIXTURE_FILES = tuple(
    f"fixture/{name}"
    for name in (
        "recipe.json",
        "references.csv",
        "query-manifest.csv",
        "audit.json",
        "queries.csv",
        "candidates.csv",
    )
)
REPLAY_FILES = tuple(
    f"replay/{name}"
    for name in ("audit.json", "queries.csv", "candidates.csv", "verification.json")
)
PROFILE_FILES = {
    "fixture": FIXTURE_FILES,
    "published": PUBLIC_FILES,
    "full": (*PUBLIC_FILES, *REPLAY_FILES),
}
EXPORT_FILES = {
    "REPORT.md",
    "REPRODUCE.md",
    "metrics.json",
    "model-accuracy.svg",
    "timing.svg",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def identity_digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def json_record(data: bytes, name: str) -> dict:
    value = json.loads(data)
    require(isinstance(value, dict), f"{name}: expected a JSON object")
    return value


def read_text_file(root: Path, path: str) -> bytes:
    source = root / path
    if not source.is_file():
        raise ValueError(
            f"missing evidence file {source}; see docs/reproduce-evidence.md"
        )
    require(
        source.resolve().is_relative_to(root.resolve()),
        f"{source}: evidence path leaves its root",
    )
    require(
        source.stat().st_size <= MAX_FILE_BYTES,
        f"{source}: evidence file exceeds size limit",
    )
    return source.read_bytes()


@dataclass(frozen=True)
class Evidence:
    manifest: dict
    payload: dict[str, bytes]

    @property
    def profile(self) -> str:
        return self.manifest["profile"]

    @property
    def run_id(self) -> str:
        return self.manifest["run_id"]

    def json(self, file: str) -> dict:
        return json_record(self.payload[file], file)

    def rows(self, file: str, columns=()) -> list[dict[str, str]]:
        with io.StringIO(self.payload[file].decode("utf-8-sig"), newline="") as stream:
            return list(csv_rows(stream, columns, name=file))

    def check_digest(self, file: str, expected: str) -> None:
        require(
            sha256(self.payload[file]) == expected,
            f"{file}: checksum disagrees with its source record",
        )


def make_evidence(
    profile: str, payload: dict[str, bytes], provenance: dict
) -> Evidence:
    require(
        isinstance(profile, str) and profile in PROFILE_FILES,
        f"unknown evidence profile {profile!r}",
    )
    require(
        payload.keys() == set(PROFILE_FILES[profile]),
        f"{profile}: missing or unexpected evidence files",
    )
    require(isinstance(provenance, dict), "evidence provenance must be an object")
    digests = {path: sha256(data) for path, data in payload.items()}
    # Elapsed time is captured in each execution. It does not rename the input workload.
    identity_files = FIXTURE_FILES[:3] if profile == "fixture" else PUBLIC_FILES
    identity = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "inputs": {path: digests[path] for path in identity_files},
    }
    return Evidence(
        {
            **identity,
            "run_id": identity_digest(identity),
            "artifacts": digests,
            "provenance": provenance,
        },
        payload,
    )


def validate_evidence(manifest: dict, payload: dict[str, bytes]) -> Evidence:
    expected = make_evidence(manifest["profile"], payload, manifest["provenance"])
    require(
        manifest.get("artifacts") == expected.manifest["artifacts"],
        "evidence artifact checksums do not match",
    )
    require(
        manifest == expected.manifest,
        "evidence run ID, input identity, or schema does not match",
    )
    return expected


def published_evidence(repo: Path) -> Evidence:
    payload = {}
    for path in PUBLIC_FILES:
        source = f"docs/{path}" if path.startswith("results/") else path
        payload[path] = read_text_file(repo, source)
    return make_evidence(
        "published",
        payload,
        {"mode": "saved_public_results", "historical_measurement_metadata": "results/"},
    )


def write_evidence(evidence: Evidence, root: Path) -> None:
    for name, data in evidence.payload.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write_json(root / "manifest.json", evidence.manifest)


def unpack_bundle(path: Path) -> tuple[Evidence, dict[str, bytes]]:
    with ZipFile(path) as archive:
        info = archive.infolist()
        names = {member.filename for member in info}
        allowed = (
            {"manifest.json", "checksums.json"}
            | EXPORT_FILES
            | set(PUBLIC_FILES)
            | set(FIXTURE_FILES)
            | set(REPLAY_FILES)
        )
        require(
            len(names) == len(info) and names <= allowed,
            "bundle contains duplicate or unapproved files",
        )
        require(
            {"manifest.json", "checksums.json"} <= names,
            "bundle is missing its manifest or checksum list",
        )
        require(
            all(member.file_size <= MAX_FILE_BYTES for member in info)
            and sum(member.file_size for member in info) <= MAX_BUNDLE_BYTES,
            "bundle evidence exceeds size limit",
        )
        members = {name: archive.read(name) for name in names}
    checksums = json_record(members.pop("checksums.json"), "checksums.json")
    require(
        checksums == {name: sha256(data) for name, data in members.items()},
        "bundle checksums do not match its files",
    )
    manifest = json_record(members.pop("manifest.json"), "manifest.json")
    exports = {name: members.pop(name) for name in EXPORT_FILES if name in members}
    evidence = validate_evidence(manifest, members)
    expected = {"REPORT.md", "REPRODUCE.md", "metrics.json"}
    if evidence.profile != "fixture":
        expected |= {"model-accuracy.svg", "timing.svg"}
    require(exports.keys() == expected, "bundle is missing generated report files")
    return evidence, exports


def open_evidence(source: Path) -> Evidence:
    if source.is_file():
        return unpack_bundle(source)[0]
    if not (source / "manifest.json").is_file():
        return published_evidence(source)
    manifest = json_record(read_text_file(source, "manifest.json"), "manifest.json")
    require(
        isinstance(manifest.get("profile"), str)
        and manifest["profile"] in PROFILE_FILES,
        "unknown or missing evidence profile",
    )
    files = PROFILE_FILES[manifest["profile"]]
    return validate_evidence(
        manifest, {path: read_text_file(source, path) for path in files}
    )
