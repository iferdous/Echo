# Echo

Echo is an audio dataset auditing project. The current build prepares pinned datasets, reads and resamples audio, checks for shared recording IDs, and generates a reproducible crop benchmark. Upcoming stages will match clips from the sound itself and measure how training on shared audio changes a classifier's score.

A five-second excerpt can come from the same recording as a longer file with a different name and encoding. Echo will use acoustic fingerprints to find the shared audio and return a timestamp and matching evidence. The two datasets for the first study are ESC-50 and FSD50K. LAION has already documented overlap in their source IDs. Echo will use those IDs to check its work and test what it can recover from the audio itself. [ESC-50](https://github.com/karolpiczak/ESC-50) · [FSD50K](https://zenodo.org/records/4060432) · [LAION overlap analysis](https://github.com/LAION-AI/audio-dataset/blob/main/laion-audio-630k/ICASSP.md#potential-data-leakage)

## Getting started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use its locked environment. The project pins Python 3.12.16. The locked environment is verified on Apple Silicon macOS and Ubuntu 24.04.

```bash
uv sync --locked
uv run echo-audit --help
uv run echo-audit fixture --out .local/fixture
uv run pytest
```

The fixture writes a reference WAV, a related crop with a known sample offset, and an unrelated distractor. Use a fresh output path for each run. The command is also available as `uv run python -m echo`. FFmpeg is optional until codec evaluation.

## Stage 1 dataset workflow

```bash
uv run echo-audit data fetch --root .local
uv run echo-audit data inventory --esc50 .local/esc50 --out .local/stage1/inventory
uv run echo-audit data audit \
  --esc50-metadata .local/esc50/meta/esc50.csv \
  --fsd50k .local/downloads/fsd50k-ground-truth.zip \
  --out .local/stage1/overlap
uv run echo-audit data spike \
  --esc50 .local/esc50 \
  --inventory .local/stage1/inventory/assets.csv \
  --out .local/stage1/spike
```

The fetch uses a roughly 616 MiB ESC-50 archive and a small FSD50K metadata ZIP. Use new output directories for reruns. See the [Stage 0 and 1 results](docs/results/stages-0-1.md) for the verified environment, reports, and output layout.

## Implementation stages

Follow the [numbered stages, 0 through 9](docs/stages/README.md). Start with [Stage 0, Environment and scaffold](docs/stages/00-environment-and-scaffold.md).

## Build documents

- [Build plan](docs/build-plan.md) covers shared scope, architecture, commands, and implementation decisions.
- [Evaluation protocol](docs/evaluation-protocol.md) covers the dataset audit, how to verify audio matches, and the controlled model experiment.

## Dataset baseline

The implemented metadata audit reproduced 630 ESC-50 rows with IDs shared by FSD50K. It also found four ESC-50 source IDs that span more than one fold in the inspected metadata. These observations define the starting point for the acoustic audit and the experiment's source-group checks. [Audit inputs, counts, and reproduction](docs/evaluation-protocol.md#metadata-preflight)
