# Reproduce Echo’s benchmark evidence

The fixture profile checks whether a build can index a known recording, recover a crop at the expected timestamp, reject separate audio, and distinguish silence. The full local profile checks the published corpus and replays the cross-dataset audit. Teams can use the fixture in CI and use a versioned batch audit to review each proposed training and test split. [Run Echo on your own audio](demo/ENGINEER-GUIDE.md)

## Reproduce the fixture in a fresh checkout

The fixture uses generated WAVs and the default matcher policy. It needs the pinned Python environment and runs without a dataset download or model weights.

```bash
uv sync --locked
uv run --no-sync echo-audit bench --profile fixture --out .local/ci-profile
uv run --no-sync echo-audit report .local/ci-profile --out .local/ci-report
uv run --no-sync echo-audit bundle .local/ci-profile --out .local/ci-evidence.zip
```

Keep the manifest and CSVs as CI artifacts when debugging matcher behavior. The generated benchmark checks decisions and offset tolerance. It records runtime without imposing a latency threshold on shared runners. Its run ID depends on the fixture and recipe digests. System clocks and elapsed measurements are recorded separately.

## Rebuild the published report without datasets

Download the [published evidence ZIP](results/echo-evidence.zip) or use the copy in the repository. The ZIP includes an approved set of public text artifacts and generated SVGs. It omits WAVs, SQLite indexes, model checkpoints, and the demo video. The manifest binds input identities and result checksums to the profile. The generated reports are also covered by the ZIP’s checksum list.

```bash
uv sync --locked --group demo
uv run --no-sync echo-audit report docs/results/echo-evidence.zip --out .local/from-bundle
uv run --no-sync echo-audit report . --check
```

The first command reads the ZIP directly and recomputes statistics from its validated contents. The second compares the generated README table, report, metrics JSON, plots, and ZIP contents against the checked-in release evidence. Regenerate the committed outputs after an intentional evidence update with `uv run --no-sync python scripts/publish_stage8.py`. [Generated report](results/stage-8.md)

## Reproduce the full local profile

Use the pinned **2,000-file ESC-50** inventory and the **290 official FSD50K eval** reference recordings from the selected Stage 4 cohort. The earlier stage guides show how to fetch the pinned ESC-50 and FSD50K metadata, freeze the manifests, acquire the selected official WAVs, and build the FSD50K index. [ESC-50 and metadata setup](results/stages-0-1.md#reproduction) · [Official FSD50K acquisition and audit](results/stage-4.md#reproduce)

The default paths are `.local/esc50`, `.local/stage1/inventory/assets.csv`, `.local/downloads/fsd50k-ground-truth.zip`, `.local/stage4/fsd50k-complete` or `.local/stage4/fsd50k`, and `.local/stage4/audit-run/index.sqlite`. Use `--fsd-root` and `--index` if those two inputs live elsewhere. The full profile verifies file checksums and rejects missing or changed inputs. It reruns the Stage 4 queries against the saved corpus with the frozen Stage 3 matcher policy and compares decisions and candidates with the published evidence.

```bash
uv sync --locked --group demo
uv run --no-sync echo-audit bench --profile full --data-root .local --out .local/full-profile
uv run --no-sync echo-audit report .local/full-profile --out .local/full-report
uv run --no-sync echo-audit bundle .local/full-profile --out .local/full-evidence.zip
```

Choose new output paths on each run. Python is the default matcher. After building the optional native wheel, use `--engine rust` for the same profile and compare the replay evidence. A separately rebuilt index can have different bytes across SQLite builds. Its manifest, fingerprint configuration, decisions, and candidate payloads still need to agree. [Optional Rust install](results/stage-6.md#reproduce)

The profile reuses the held-out matcher, paired-model predictions, and profiler samples as historical measurements. For fresh measurements, follow each stage’s commands. For the training run, the saved summary names its source commit and dependency-lock digest. Use that revision to recreate the original locked environment, or regenerate calibration and training with the current lock. Scores can vary with backend or platform and timings vary with hardware, caches, and concurrent load. Keep the original receipt alongside each new run. [Held-out matching](results/stage-3.md#reproduce) · [Paired training](results/stage-5.md#reproduce) · [Profiling](results/stage-6.md#reproduce)

An absent-source decision applies to the checked corpus and policy. Keep failed decodes, unreviewed pairs, and unsupported offsets visible when deciding whether an evaluation split is ready.
