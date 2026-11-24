"""In-memory and persistent lookup for audio fingerprint postings."""

import os
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from echo.artifacts import sha256_file
from echo.audio import load_audio
from echo.datasets import read_manifest
from echo.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintConfig,
    Landmark,
    fingerprint,
)

SCHEMA_VERSION = 1
APPLICATION_ID = 0x4543484F
LOOKUP_BATCH = 500


class IndexFormatError(ValueError):
    """The index cannot be read by this matcher."""


@dataclass(frozen=True, slots=True)
class Track:
    asset_id: str
    samples: int
    landmarks: int


@dataclass(frozen=True, slots=True)
class FingerprintedTrack:
    track: Track
    landmarks: list[Landmark]


Posting = tuple[str, int]


class Index(Protocol):
    config: FingerprintConfig
    tracks: dict[str, Track]

    def lookup(self, keys: set[int], max_postings: int) -> dict[int, list[Posting]]: ...


def fingerprint_manifest(
    manifest: Path, root: Path, config: FingerprintConfig
) -> Iterator[FingerprintedTrack]:
    for asset in read_manifest(manifest):
        path = asset.local_path(root)
        if asset.sha256 and sha256_file(path) != asset.sha256:
            raise ValueError(
                f"{asset.asset_id}: audio does not match the manifest checksum"
            )
        audio = load_audio(path, target_rate=config.sample_rate)
        landmarks = fingerprint(audio.samples, config)
        yield FingerprintedTrack(
            Track(asset.asset_id, len(audio.samples), len(landmarks)), landmarks
        )


class MemoryIndex:
    def __init__(
        self, config: FingerprintConfig, fingerprints: Iterable[FingerprintedTrack]
    ) -> None:
        self.config = config
        self.tracks: dict[str, Track] = {}
        self._postings: dict[int, list[Posting]] = defaultdict(list)
        for item in fingerprints:
            asset_id = item.track.asset_id
            if asset_id in self.tracks:
                raise ValueError(f"duplicate indexed asset ID {asset_id}")
            self.tracks[asset_id] = item.track
            for landmark in item.landmarks:
                self._postings[landmark.key].append((asset_id, landmark.frame))

    def lookup(self, keys: set[int], max_postings: int) -> dict[int, list[Posting]]:
        return {
            key: postings
            for key in keys
            if (postings := self._postings.get(key)) and len(postings) <= max_postings
        }


_SCHEMA = f"""
PRAGMA application_id = {APPLICATION_ID};
PRAGMA user_version = {SCHEMA_VERSION};
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE tracks (
    track_id INTEGER PRIMARY KEY,
    asset_id TEXT UNIQUE NOT NULL,
    samples INTEGER NOT NULL,
    landmarks INTEGER NOT NULL
);
CREATE TABLE postings (
    hash INTEGER NOT NULL,
    track_id INTEGER NOT NULL REFERENCES tracks(track_id),
    frame INTEGER NOT NULL,
    PRIMARY KEY (hash, track_id, frame)
) WITHOUT ROWID;
CREATE TABLE hash_counts (
    hash INTEGER PRIMARY KEY,
    postings INTEGER NOT NULL
);
"""


def build_index(
    manifest: Path,
    root: Path,
    out: Path,
    config: FingerprintConfig,
    *,
    replace_existing: bool = False,
) -> dict:
    if out.exists() and not replace_existing:
        raise FileExistsError(f"{out} already exists. Pass --replace to rebuild it.")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_digest = sha256_file(manifest)
    track_count = posting_count = 0

    with TemporaryDirectory(dir=out.parent) as directory:
        prepared = Path(directory) / "index.sqlite"
        with closing(sqlite3.connect(prepared)) as connection, connection:
            connection.executescript(_SCHEMA)
            for item in fingerprint_manifest(manifest, root, config):
                track_count += 1
                posting_count += item.track.landmarks
                connection.execute(
                    "INSERT INTO tracks VALUES (?, ?, ?, ?)",
                    (
                        track_count,
                        item.track.asset_id,
                        item.track.samples,
                        item.track.landmarks,
                    ),
                )
                connection.executemany(
                    "INSERT INTO postings VALUES (?, ?, ?)",
                    (
                        (landmark.key, track_count, landmark.frame)
                        for landmark in item.landmarks
                    ),
                )
            if sha256_file(manifest) != manifest_digest:
                raise ValueError("manifest changed during indexing")
            connection.execute(
                "INSERT INTO hash_counts SELECT hash, COUNT(*) FROM postings GROUP BY hash"
            )
            connection.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                {
                    "manifest_sha256": manifest_digest,
                    "fingerprint_version": str(FINGERPRINT_VERSION),
                    "fingerprint_config": config.to_json(),
                    "fingerprint_config_sha256": config.digest,
                }.items(),
            )
        if replace_existing:
            prepared.replace(out)
        else:
            # A link publishes the finished file atomically without clobbering another writer.
            os.link(prepared, out)
    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "manifest_sha256": manifest_digest,
        "fingerprint_config_sha256": config.digest,
        "indexed_assets": track_count,
        "postings": posting_count,
        "bytes": out.stat().st_size,
    }


class SQLiteIndex:
    def __init__(
        self, connection: sqlite3.Connection, expected_config: FingerprintConfig | None
    ) -> None:
        self._connection = connection
        (application_id,) = connection.execute("PRAGMA application_id").fetchone()
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        if application_id != APPLICATION_ID or version != SCHEMA_VERSION:
            raise IndexFormatError("unsupported Echo index schema; rebuild the index")
        metadata = dict(connection.execute("SELECT name, value FROM metadata"))
        try:
            if metadata["fingerprint_version"] != str(FINGERPRINT_VERSION):
                raise IndexFormatError(
                    "unsupported fingerprint version; rebuild the index"
                )
            self.config = FingerprintConfig.from_json(metadata["fingerprint_config"])
            if self.config.digest != metadata["fingerprint_config_sha256"]:
                raise IndexFormatError(
                    "index fingerprint configuration checksum mismatch"
                )
            self.manifest_sha256 = metadata["manifest_sha256"]
        except (KeyError, ValueError) as error:
            raise IndexFormatError(f"invalid Echo index metadata: {error}") from error
        if expected_config is not None and self.config != expected_config:
            raise IndexFormatError("fingerprint configuration does not match the index")
        self._tracks_by_row = {
            row_id: Track(asset_id, samples, landmarks)
            for row_id, asset_id, samples, landmarks in connection.execute(
                "SELECT track_id, asset_id, samples, landmarks FROM tracks"
            )
        }
        self.tracks = {track.asset_id: track for track in self._tracks_by_row.values()}

    def lookup(self, keys: set[int], max_postings: int) -> dict[int, list[Posting]]:
        result = defaultdict(list)
        for batch in batched(sorted(keys), LOOKUP_BATCH):
            placeholders = ", ".join("?" for _ in batch)
            rows = self._connection.execute(
                f"""
                SELECT postings.hash, postings.track_id, postings.frame
                FROM hash_counts JOIN postings USING (hash)
                WHERE hash_counts.hash IN ({placeholders})
                    AND hash_counts.postings <= ?
                """,
                (*batch, max_postings),
            )
            for key, row_id, frame in rows:
                result[key].append((self._tracks_by_row[row_id].asset_id, frame))
        return dict(result)


@contextmanager
def open_index(
    path: Path, expected_config: FingerprintConfig | None = None
) -> Iterator[SQLiteIndex]:
    if not path.is_file():
        raise FileNotFoundError(f"index does not exist: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        try:
            index = SQLiteIndex(connection, expected_config)
        except sqlite3.DatabaseError as error:
            raise IndexFormatError(f"cannot read Echo index {path}: {error}") from error
        yield index
