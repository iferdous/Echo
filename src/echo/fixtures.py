"""Small, deterministic audio fixtures generated independently of public corpora."""

from pathlib import Path

import numpy as np
import soundfile as sf

from echo.artifacts import new_output_directory, sha256_file, write_json

FIXTURE_SEED = 137
SAMPLE_RATE = 16_000
CROP_START = 12_000
CROP_SAMPLES = 32_000


def write_fixture(out: Path) -> None:
    rng = np.random.default_rng(FIXTURE_SEED)
    time = np.arange(4 * SAMPLE_RATE, dtype=np.float64) / SAMPLE_RATE
    reference = 0.32 * np.sin(2 * np.pi * (230 * time + 78 * time**2))
    for center in (0.35, 1.15, 2.3, 3.55):
        pulse = np.exp(-(((time - center) / 0.016) ** 2))
        reference += 0.22 * pulse * rng.uniform(-1, 1, time.size)
    distractor = 0.31 * np.sin(2 * np.pi * (740 * time + 6 * time**2))

    # Quantize the source before slicing so the crop shares exact PCM samples.
    pcm = np.rint(reference * 32767).astype(np.int16)
    recordings = {
        "reference.wav": pcm,
        "query.wav": pcm[CROP_START : CROP_START + CROP_SAMPLES],
        "distractor.wav": np.rint(distractor * 32767).astype(np.int16),
    }
    with new_output_directory(out):
        for name, audio in recordings.items():
            sf.write(out / name, audio, SAMPLE_RATE, subtype="PCM_16")
        write_json(
            out / "fixture.json",
            {
                "schema_version": 1,
                "seed": FIXTURE_SEED,
                "sample_rate": SAMPLE_RATE,
                "crop_start_sample": CROP_START,
                "crop_samples": CROP_SAMPLES,
                "sha256": {name: sha256_file(out / name) for name in recordings},
            },
        )
