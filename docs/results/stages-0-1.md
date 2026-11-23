# Stages 0 and 1 verification

Validation date: November 23, 2026.

## Stage 0

The Python package installs from the uv lockfile. The CLI runs as `echo-audit` or `python -m echo`. The executable name avoids the shell's built-in `echo` command.

| Environment | Verification |
| --- | --- |
| Apple Silicon macOS | Native ARM64, CPython 3.12.16, uv 0.13.9, NumPy 2.5.5, SciPy 1.18.1, SoundFile 0.14.0 |
| Ubuntu 24.04 GitHub Actions | Locked install, format check, lint, tests, and generated-fixture smoke ran on the scaffold commit. [Stage 0 CI](https://github.com/iferdous/Echo-/actions/runs/45291952162) |

The fixture contains a four-second reference, a distinct distractor, and a two-second crop starting at sample 12,000 at 16 kHz. Validation checked the crop against the original PCM samples. Stage 1 also reads this fixture through the production audio loader and verifies resampling behavior and an invalid-input path in tests.

## Stage 1

| Evidence | Observed result |
| --- | --- |
| [ESC-50 inventory](stage-1-inventory.json) | 2,000 of 2,000 clips decoded and checksummed. All were five seconds of mono PCM16 at 44.1 kHz. Zero missing or rejected assets and zero unlisted WAVs. |
| [Metadata overlap](stage-1-overlap.json) | 630 ESC-50 rows share 577 distinct source IDs with FSD50K. Four ESC-50 source IDs span folds. |
| [Spike generation](stage-1-spike.json) | Seed 137 produced 200 index items from 200 source groups, 20 known crops and 10 queries whose original source IDs were absent from the index. Each absent-source query has at least one indexed distractor in the same class. |

The ESC-50 archive digest is checked before extraction and its metadata digest is checked before loading. The FSD50K input for these stages is the pinned ground-truth ZIP. The overlap output measures original source IDs. Acoustic matching begins in [Stage 2](../stages/02-python-fingerprint-matcher.md).

Two independent output directories produced identical inventory reports and manifests, overlap reports, and spike manifests and WAVs. All 30 generated crops were checked against the original PCM bytes and recorded offsets using Python's WAV reader. The source distribution and wheel also built locally, and all 24 automated tests passed on Apple Silicon.

## Reproduction

Use a fresh output path for each run. The data and per-asset inventory remain under `.local`. The smaller reports linked above can be compared with the generated outputs.

```bash
uv sync --locked
uv run ruff format --check src tests
uv run ruff check src tests
uv run pytest
uv run echo-audit fixture --out .local/stage1/fixture
uv run echo-audit audio .local/stage1/fixture/query.wav --target-rate 12000
uv run echo-audit data fetch --root .local
uv run echo-audit data inventory --esc50 .local/esc50 --out .local/stage1/inventory
uv run echo-audit data audit \
  --esc50-metadata .local/esc50/meta/esc50.csv \
  --fsd50k .local/downloads/fsd50k-ground-truth.zip \
  --out .local/stage1/overlap
uv run echo-audit data spike \
  --esc50 .local/esc50 \
  --inventory .local/stage1/inventory/assets.csv \
  --out .local/stage1/spike --seed 137 --index-size 200
```

The paths in `spike/index.csv` resolve against the ESC-50 root. The paths in `spike/queries.csv` resolve against the spike output directory. Crop starts and lengths use the original file's sample rate.
