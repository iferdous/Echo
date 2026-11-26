"""Build the small public listening pack from verified official dataset WAVs."""

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_json
from echo.evidence import require

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/results"
ESC_LICENSE = "https://creativecommons.org/licenses/by/3.0/"
FS_LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"
REFERENCES = (
    ("catalog-dog", "207124"),
    ("catalog-rain", "21189"),
    ("catalog-other-dog", "32318"),
)
ESC_QUERIES = (
    ("esc-dog", "4-207124-A-0.wav", "Dog bark from ESC-50", "catalog-dog"),
    ("esc-rain", "1-21189-A-10.wav", "Rain from ESC-50", "catalog-rain"),
)


def rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def prepare(args):
    import imageio_ffmpeg

    official = {
        a["fsd_source_id"]: a for a in rows(RESULTS / "stage-4-acquisition.csv")
    }
    esc_manifest = {
        Path(a["path"]).name: a for a in rows(RESULTS / "stage-4-query-manifest.csv")
    }
    esc_meta = {a["filename"]: a for a in rows(args.esc_root / "meta/esc50.csv")}
    with ZipFile(args.fsd_metadata) as archive:
        metadata = json.loads(
            archive.read("FSD50K.metadata/eval_clips_info_FSD50K.json")
        )
    with new_output_directory(args.out):
        audio = args.out / "audio"
        audio.mkdir()
        inputs = {}

        def register(asset_id, source_id, license_url, dataset, path, change):
            info = metadata[source_id]
            require(
                info["license"].replace("http:", "https:") == FS_LICENSE,
                f"Freesound {source_id}: expected the archived CC0 license",
            )
            inputs[asset_id] = {
                "path": f"audio/{path.name}",
                "sha256": sha256_file(path),
                "dataset": dataset,
                "source_id": source_id,
                "source_url": f"https://freesound.org/s/{source_id}/",
                "title": info["title"].strip(),
                "uploader": info["uploader"],
                "license": license_url,
                "change": change,
            }

        for name, source in (*REFERENCES, ("other-dog", "274471")):
            origin = args.fsd_root / "audio" / f"{source}.wav"
            require(
                sha256_file(origin) == official[source]["sha256"],
                f"{origin}: bytes differ from the acquisition ledger",
            )
            destination = audio / f"{name}.wav"
            shutil.copyfile(origin, destination)
            register(
                name, source, FS_LICENSE, "FSD50K eval", destination, "Official WAV"
            )
        variants = []
        for name, original, label, expected in ESC_QUERIES:
            meta = esc_meta[original]
            origin = args.esc_root / "audio" / original
            require(meta["esc10"] == "True", f"{original}: expected an ESC-10 asset")
            require(
                sha256_file(origin) == esc_manifest[original]["sha256"],
                f"{origin}: bytes differ from the frozen query manifest",
            )
            destination = audio / f"{name}.wav"
            shutil.copyfile(origin, destination)
            register(
                name,
                meta["src_file"],
                ESC_LICENSE,
                "ESC-10 subset of ESC-50",
                destination,
                f"Official excerpt {original}",
            )
            variants.append({"id": name, "label": label, "expected": expected})

        original = audio / "esc-dog.wav"
        samples, rate = sf.read(original, dtype="int16")
        clip = samples[round(1.6 * rate) : round(3.6 * rate)]
        trimmed = audio / "dog-trim.wav"
        sf.write(trimmed, clip, rate, subtype="PCM_16")
        mp3 = audio / "dog-mp3.mp3"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-loglevel",
                "error",
                "-i",
                str(trimmed),
                "-map_metadata",
                "-1",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "64k",
                str(mp3),
            ],
            check=True,
        )
        noise = np.random.default_rng(271).standard_normal(len(clip))
        clean = clip.astype(np.float64) / 32768
        snr_db = -5
        noise *= np.linalg.norm(clean) / np.linalg.norm(noise) * 10 ** (-snr_db / 20)
        noisy = clean + noise
        noisy *= min(1, 0.98 / np.max(np.abs(noisy)))
        noisy_cut = audio / "dog-noisy.wav"
        sf.write(noisy_cut, noisy, rate, subtype="PCM_16")
        for name, path, change, label in (
            ("dog-trim", trimmed, "ESC-10 dog clip, 1.6 to 3.6 s", "2-second dog crop"),
            ("dog-mp3", mp3, "Same 2-second crop, 64 kbps MP3", "64 kbps MP3 crop"),
            (
                "dog-noisy",
                noisy_cut,
                "Same crop with seeded white noise at −5 dB SNR",
                "Dog crop with heavy noise",
            ),
        ):
            register(name, "207124", ESC_LICENSE, "Derived from ESC-10", path, change)
            variants.append({"id": name, "label": label, "expected": "catalog-dog"})

        variants.append(
            {"id": "other-dog", "label": "Different dog recording", "expected": None}
        )
        manifest = {
            "schema_version": 1,
            "references": [name for name, _ in REFERENCES],
            "queries": variants,
            "audio": inputs,
            "dataset_urls": {
                "esc50": "https://github.com/karolpiczak/ESC-50/tree/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6",
                "fsd50k": "https://zenodo.org/records/4060432",
            },
        }
        write_json(args.out / "dataset.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esc-root", required=True, type=Path)
    parser.add_argument("--fsd-root", required=True, type=Path)
    parser.add_argument("--fsd-metadata", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    prepare(parser.parse_args())


if __name__ == "__main__":
    main()
