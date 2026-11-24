# Echo

Echo audits audio datasets for shared recordings. Give it a clip or a manifest and an index of reference audio. It reports candidate recordings, timestamps, and the evidence behind each decision. A controlled training experiment shows how prior exposure to test audio changes a classifier's score.

A five-second excerpt can come from the same recording as a longer file with a different name and encoding. Echo uses acoustic fingerprints to find shared audio and return a timestamp and matching evidence. The two datasets for the first study are ESC-50 and FSD50K. LAION has already documented overlap in their source IDs. Echo uses those IDs to measure coverage after it ranks candidates by sound. [ESC-50](https://github.com/karolpiczak/ESC-50) · [FSD50K](https://zenodo.org/records/4060432) · [LAION overlap analysis](https://github.com/LAION-AI/audio-dataset/blob/main/laion-audio-630k/ICASSP.md#potential-data-leakage)

## Getting started

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use its locked environment. The project pins Python 3.12.16. The locked environment is verified on Apple Silicon macOS and Ubuntu 24.04.

```bash
uv sync --locked
uv run echo-audit --help
uv run echo-audit fixture --out .local/fixture
uv run --group benchmark pytest
```

The fixture writes a reference WAV, a related crop with a known sample offset, and an unrelated distractor. Use a fresh output path for each run. The command is also available as `uv run python -m echo`. The benchmark dependency group supplies FFmpeg for codec evaluation.

## Try the matcher

```bash
uv run echo-audit fixture --out .local/quickstart
uv run echo-audit index .local/quickstart/index.csv --out .local/quickstart/index.sqlite
uv run echo-audit match .local/quickstart/query.wav --index .local/quickstart/index.sqlite --json
uv run echo-audit match .local/quickstart/distractor.wav --index .local/quickstart/index.sqlite
```

The fixture's expected recording is `fixture:reference` around **+0.750 s**. The separate recording returns `no_match`. Offsets are reference time minus query time. For ESC-50 manifests, pass `--root .local/esc50` to `index`. [Stage 2 measurements and reproduction](docs/results/stage-2.md)

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

## Stage 3 benchmark

The matcher accepted **333 of 360** held-out matching trials and **0 of 360** absent-source trials. Each side used 40 recordings with nine variants per recording. The report includes the calibration and test protocol, individual conditions, the frozen policy, and reproduction commands. [Stage 3 report](docs/results/stage-3.md)

## Stage 4 cross-dataset audit

Echo scored 267 ESC-50 clips against a frozen cohort of 290 official FSD50K eval recordings. An independent waveform check confirmed shared audio in 140 same-source pairs. Echo accepted the right recording at the supported offset for 137. The report includes the misses, unresolved cases, and replay instructions. [Stage 4 report and evidence](docs/results/stage-4.md)

To audit your own dataset, build a reference index and pass a query manifest with the same [asset columns](src/echo/datasets.py). All runs write query decisions and ranked candidates to CSV.

```bash
uv run echo-audit index references.csv --root reference-audio --out references.sqlite
uv run echo-audit audit queries.csv --root query-audio --index references.sqlite \
  --policy docs/results/stage-3-policy.json --out .local/my-audit
```

## Stage 5 model experiment

On the same 400 ESC-50 test clips, mean accuracy rose from **47.4% to 57.0%** when training included three-second crops from selected test recordings. Both models in each of five seed pairs trained on 1,096 examples. On the 164 directly exposed clips, accuracy rose by **19.27 percentage points**. [Stage 5 report, predictions, and reproduction](docs/results/stage-5.md)

## Implementation stages

Follow the [numbered stages, 0 through 9](docs/stages/README.md). Start with [Stage 0, Environment and scaffold](docs/stages/00-environment-and-scaffold.md).

## Build documents

- [Build plan](docs/build-plan.md) covers shared scope, architecture, commands, and implementation decisions.
- [Evaluation protocol](docs/evaluation-protocol.md) covers the dataset audit, how to verify audio matches, and the controlled model experiment.

## Dataset baseline

The implemented metadata audit reproduced 630 ESC-50 rows with IDs shared by FSD50K. It also found four ESC-50 source IDs that span more than one fold in the inspected metadata. These observations define the starting point for the acoustic audit and the experiment's source-group checks. [Audit inputs, counts, and reproduction](docs/evaluation-protocol.md#metadata-preflight)
