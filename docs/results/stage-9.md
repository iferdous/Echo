# Stage 9 release verification

This closes the initial Echo preview. The release includes the CLI, the generated-audio walkthrough and captions, the benchmark evidence bundle, and an evaluation-split case using official ESC-50 and FSD50K audio. [Preview notes](../preview-release.md) · [Real-world case](../real-world-case.md) · [Résumé and interview notes](../resume-bullets.md)

## Previous stages

| Stage and recorded delivery | Release verification |
| --- | --- |
| [0 · Scaffold](https://github.com/iferdous/Echo/commit/20ebfcf) | A locked Python 3.12 install, built wheel, CLI entry point, and generated fixture run from a clean checkout. |
| [1 · Dataset foundations](https://github.com/iferdous/Echo/commit/2171a92) | Rebuilt the ESC-50 inventory, metadata overlap, and spike ledgers. The published inventory and overlap JSON and the saved spike manifests were byte-identical. |
| [2 · Fingerprint matcher](https://github.com/iferdous/Echo/commit/057c1ea) | Reran both fingerprint configurations. All 60 scored rows matched the published rows apart from measured time. The local floor correctly accepted 18/20 positives and the global floor accepted 15/20. |
| [3 · Held-out evaluation](https://github.com/iferdous/Echo/commit/152a689) | Re-ran calibration and the holdout. All 1,440 trial rows matched their published decision and ranking evidence apart from measured time. Calibration regenerated the identical frozen policy. |
| [4 · Cross-dataset audit](https://github.com/iferdous/Echo/commit/210974d) | Verified 2,290 WAV hashes and re-ran the original 267-query audit through the normal CLI with Rust, reproducing 1,335 ranked candidate rows and every query decision. The new case also re-ran the 95 retained rows with the default Python engine. |
| [5 · Paired model experiment](https://github.com/iferdous/Echo/commit/4abd3b5) | Trained both arms for all five seeds from the pinned source tree. All 2,000 paired predictions, per-class results and training logs were byte-identical. Recalibration and training with the current lock produced the same prediction, training and classification payloads under a new run ID. |
| [6 · Profiling and Rust](https://github.com/iferdous/Echo/commit/325a0a9) | Recalculated the historical benchmark from raw timing samples. Verified the optional Rust path on the actual FSD50K index and CI’s native tests. The published timing numbers come from the historical Apple M3 runs. |
| [7 · Walkthrough](https://github.com/iferdous/Echo/commit/b997c69) | Regenerated the walkthrough and offline review from the documented clean setup. Verified the delivered video, captions, chart and screenshot against their saved digests. |
| [8 · Benchmark evidence](https://github.com/iferdous/Echo/commit/27f8c04) | Regenerated the fixture bundle and the published report from the evidence ZIP, and checked the README, tables and figures against their pinned evidence. |

The paired classifier's historical run ID is `2c117167672477d6faa6c8591f527ff84d17e223529a458135c6e4a348ba889b`. Recalibration with the current lock gave run `1058e2fef6d204d62de4f42b134e4359cc4f9716859d9cbafb1ced381dbfba26`. Both stayed at +9.60 percentage points on the fixed 400-clip evaluation. [Historical protocol and output digests](stage-5.md) · [Benchmark evidence manifest](stage-8.md)

## Failure handling and dataset checks

The test suite checks malformed or missing inputs, nonfinite audio, empty and extremely short audio, silence, repeated hashes, offsets and ranking ties, malformed manifests, and interrupted index replacement. The new release tests added 100 deterministic malformed byte samples plus corrupt and truncated WAV cases. Valid one-sample, 96 kHz stereo, and 60-second silence inputs produced explicit insufficient-evidence results. A hop-aligned translation test checks the interior of the signal where the analysis windows have equivalent context.

The Apple Silicon test run passed **65 tests** with the optional Rust module loaded. It exercised **2,815 of 3,364** executable statements in `src/echo` (83.7% in the coverage process). The launcher module, plot generation, report rendering, and remote range acquisition have the lowest unit coverage. The release checks also invoke the launcher, report and plots through separate CLI processes. Python CI runs on Ubuntu 24.04 and Windows Server 2025. The native job builds the Rust module on Ubuntu and runs parity tests. The core jobs skip two wheel-dependent tests. Windows release tooling records peak RSS as unavailable when its platform does not provide the Unix resource API. [CI workflow](../../.github/workflows/ci.yml)

The dataset validator decoded and checksummed all **2,000 ESC-50** and **290 selected FSD50K** WAVs. All were mono PCM16 at 44.1 kHz. No checksum or decode failed. It flagged 55 ESC-50 and four FSD50K recordings with at least 1% of samples at the PCM16 ceiling. One FSD50K clip is shorter than one 0.5-second waveform review window. The published matcher runs retain these valid recordings and the case study keeps the waveform review limitation visible. [Per-file validation](stage-9-dataset-validation.json) · [Data sources and release terms](../data-sources.md)

```bash
uv run --no-sync python scripts/validate_datasets.py \
  --esc-root .local/esc50 --esc-manifest .local/stage1/inventory/assets.csv \
  --fsd-root .local/stage4/fsd50k-complete \
  --fsd-manifest docs/results/stage-4-index-manifest.csv \
  --out .local/stage9/dataset-check.json
```

## Verify the release checkout

```bash
uv sync --locked --group benchmark --group experiment --group demo
uv run --no-sync ruff format --check src tests scripts
uv run --no-sync ruff check src tests scripts
uv run --no-sync pytest
uv run --no-sync python -m echo --version
uv run --no-sync echo-audit bench --profile fixture --out .local/preview-fixture
uv run --no-sync python scripts/run_stage7.py --out .local/preview-demo
uv run --no-sync echo-audit report docs/results/echo-evidence.zip --out .local/preview-report
uv run --no-sync echo-audit report . --check
uv run --no-sync python scripts/run_stage9_case.py --check --out .local/preview-case
uv build --out-dir .local/preview-packages
```

The release attaches the evidence ZIP, the video and its WebVTT captions, the core Python wheel and source distribution, and a SHA-256 file for the attachments. The GitHub tag identifies the verified checkout. For real-audio replay, follow the upstream acquisition and licensed use instructions. [Preview release](https://github.com/iferdous/Echo/releases/tag/v0.1.0-preview.1) · [Evidence reproduction](../reproduce-evidence.md)
