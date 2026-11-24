# Stage 6 matcher profiling and Rust voting

Echo keeps Python as its default and ships a faster opt-in Rust voting engine. On the measured warm workloads, Rust reduced median query time by **56.1%** on the ESC-50/FSD50K audit and **41.7%** on the ESC-50 crops versus tuned Python. Both engines reproduced all 267 Stage 4 match results and 1,335 published candidate rows.

## How Echo was measured

Both engines used the same source WAVs, SQLite index files, fingerprint configuration, match policies, and query order. The two frozen workloads cover all 30 Stage 2 development crops and controls against 200 ESC-50 tracks, and 32 Stage 4 queries against 290 official FSD50K eval tracks. The latter includes confirmed matches, control cases, unresolved clips, the confirmed miss, and both offset disagreements. This purposive sample measures latency across several query types. [Workload protocol](../../bench/stage6-protocol.md)

Each variant ran in a fresh Python process. Fresh-connection timings opened a new read-only SQLite connection for each query and included open and metadata loading in the total. Warm timings followed one full warmup pass and then repeated the same ordered workload three times on one connection. Both conditions used the normal filesystem cache, and query WAVs were checksummed before timing. The fresh condition is cold at the SQLite connection level. Timing starts at WAV decode, or at SQLite open for the fresh total. The figures exclude process startup, manifest/hash verification, connection close, and writing results. Median and p95 refer to individual query observations. The p95 uses inclusive linear interpolation. Stage shares divide summed phase time by summed match time. The SQLite phase includes collecting lookup keys, fetching rows, and materializing Python postings.

The November 24, 2026 measurements ran on an Apple M3 Mac (Mac15,12) with eight CPU cores, 16 GiB RAM, and the project and data on the external SSK. Peak RSS is the OS high-water mark of the whole profile process. The profile reports the exact system, Python and package versions, source commit, and input digests. Baseline was measured first. For the comparison runs, tuned Python preceded Rust on FSD50K, and Rust preceded tuned Python on ESC-50. Queries and builds were timed serially. In the first ESC-50 crop comparison, the warm tuned Python pass slowed across decode, SQLite retrieval, and voting. Its per-pass medians increased from 171 to 271 to 539 ms. Both engines were rerun with the reversed order for the reported crop comparison. The first series is preserved with the other raw data. The original Stage 2 baseline was collected earlier and had lower non-voting phase times. The Rust decision uses tuned Python and Rust from the paired repeat.

## What changed

Python now avoids copying isolated vote sets and looks up neighboring offsets directly under the released one-frame radius. Wider policy radii search populated offsets rather than iterating through empty frames.

The optional Rust extension receives the same query landmarks and SQLite postings. It groups votes by track and offset and uses a sliding window over populated offset bins to count unique supporting query landmarks. Echo still ranks candidates and applies thresholds in Python. The native measurements include converting inputs at the PyO3 boundary and returning alignments, so the comparison measures the cost that users see. Both paths read the same SQLite format. The release wheel used Rust 1.95.0, PyO3 0.30.1, and maturin 1.16.0. The native profiles record the installed binary digest. [PyO3](https://pyo3.rs/v0.30.1/) · [maturin](https://pypi.org/project/maturin/1.16.0/)

## Query latency and memory

| Workload | Voting engine | Warm p50 (ms) | Warm p95 (ms) | Fresh p50 (ms) | Fresh p95 (ms) | Peak RSS (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ESC-50 crop | Original Python | 112.5 | 157.4 | 104.2 | 221.0 | 137.0 |
| ESC-50 crop | Tuned Python | 175.4 | 239.9 | 162.6 | 315.2 | 138.7 |
| ESC-50 crop | Rust | 102.3 | 164.8 | 105.1 | 156.2 | 131.7 |
| ESC-50 → FSD50K | Original Python | 451.1 | 997.4 | 436.2 | 958.3 | 313.0 |
| ESC-50 → FSD50K | Tuned Python | 429.6 | 1032.4 | 432.9 | 924.3 | 313.2 |
| ESC-50 → FSD50K | Rust | 188.8 | 456.5 | 196.4 | 427.5 | 250.4 |

### Median warm time by phase

| Workload | Voting engine | Decode and resample (ms) | Spectral peaks (ms) | Pair hashes (ms) | SQLite retrieval (ms) | Vote, rank and decide (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ESC-50 crop | Original Python | 1.5 | 1.7 | 11.4 | 40.0 | 59.2 |
| ESC-50 crop | Tuned Python | 2.3 | 2.6 | 17.9 | 63.0 | 86.2 |
| ESC-50 crop | Rust | 2.3 | 2.7 | 17.9 | 60.4 | 18.0 |
| ESC-50 → FSD50K | Original Python | 3.8 | 3.4 | 19.2 | 122.5 | 304.7 |
| ESC-50 → FSD50K | Tuned Python | 3.8 | 3.4 | 18.6 | 116.8 | 285.0 |
| ESC-50 → FSD50K | Rust | 2.4 | 3.5 | 19.9 | 119.6 | 41.9 |

Individual phase medians can come from different queries, so their sum can differ from the median end-to-end latency.

## Index builds

| Workload | Indexed tracks | Postings | Index (MiB) | Build times (s) | Median tracks/s | Median postings/s | Peak RSS (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ESC-50 crop | 200 | 2,203,046 | 35.6 | 15.54, 15.87 | 12.74 | 140,283 | 109.2 |
| ESC-50 → FSD50K | 290 | 7,042,993 | 111.6 | 53.80, 71.91 | 4.71 | 114,427 | 169.1 |

Build timings cover source checksums, audio decoding, fingerprinting, SQLite writes, and publication. Each build used a fresh destination. The Python index builder is shared by both query paths.

## Verification and decision

The default remains Python. Rust is available explicitly for `match` and `audit` and met the predeclared requirement of at least 15% lower warm median latency on both workloads with no material p95 regression. Both paths produced identical complete result digests for all 62 timed queries and their repetitions. On the full Stage 4 audit, the two engines agreed on every result and reproduced all published decisions, candidate rankings, scores, offsets, and spans. Each index rebuild matched the timed index byte for byte.

SQLite retrieval accounts for roughly 60% of the measured Rust query time on both workloads, so it is the largest remaining cost. Keeping the extra build and install step optional preserves the Python installation workflow. Both engines passed the Apple Silicon checks, and the Linux CI job builds and runs the native parity tests. [Native CI job](https://github.com/iferdous/Echo/actions/runs/45495222593)

A separate production `echo-audit audit` pass on the 32 cross-dataset queries produced byte-identical candidate CSVs and the same ordered decisions. Its per-query medians, including input verification and return from the matcher, were 609.1 ms in Python and 300.4 ms in Rust. This single pass includes the first query on a new connection. All 58 local tests passed. [Production CLI check](stage-6/cli-parity.json)

## Reproduce

Keep the verified Stage 2 and Stage 4 index and audio directories from the [Stage 2 report](stage-2.md#reproduce) and [Stage 4 report](stage-4.md#reproduce). Use a new output directory for each profile.

```bash
uv sync --locked --group benchmark --group experiment
uv tool run --from maturin==1.16.0 maturin build --release --locked \
  --manifest-path native/Cargo.toml --interpreter .venv/bin/python \
  --out .local/stage6/wheels
uv pip install --no-deps .local/stage6/wheels/*.whl

uv run --no-sync python scripts/run_stage6.py query --workload esc50-fsd50k \
  --manifest bench/stage6-stage4-queries.csv --root .local/esc50 \
  --index .local/stage4/audit-run/index.sqlite \
  --policy docs/results/stage-3-policy.json --engine rust --out .local/stage6/profile-fsd-rust

uv run --no-sync python scripts/run_stage6.py query --workload esc50-crops \
  --manifest bench/stage6-stage2-queries.csv --root .local/stage1/spike \
  --index .local/stage2/local-floor/index.sqlite --engine rust --out .local/stage6/profile-crops-rust

uv run --no-sync python scripts/run_stage6.py build --workload esc50-fsd50k \
  --manifest .local/stage4/fsd50k-complete/index.csv --root .local/stage4/fsd50k-complete \
  --out .local/stage6/build-fsd

uv run --no-sync python scripts/run_stage6.py build --workload esc50-crops \
  --manifest .local/stage1/spike/index.csv --root .local/esc50 \
  --out .local/stage6/build-crops
```

Use `--engine python` and a fresh destination to profile the tuned Python path. To reproduce the original baseline, run the same two query commands without the `--engine` option at [commit `e3800f6`](https://github.com/iferdous/Echo/commit/e3800f6). For full-audit parity, profile `docs/results/stage-4-query-manifest.csv` with each engine using `--warm 0 --fresh 1`, then compare `result_sha256` per query. The hashes cover the complete result payload, including ranked candidates, decisions, and offsets.

Use `--engine rust` with `echo-audit match` or `echo-audit audit` to opt in. `uv run --no-sync` keeps the manually installed optional wheel available. Standard installs continue to use Python. If working on the SSK, point `CARGO_HOME` and `CARGO_TARGET_DIR` to folders on that drive before building to keep dependencies and build outputs there.

## Evidence

- [Comparison and artifact checksums](stage-6/comparison.json) · [Full Stage 4 equivalence](stage-6/full-parity.json).
- ESC-50 crops, [original Python](stage-6/baseline-stage2.json), [tuned Python](stage-6/tuned-stage2.json), and [Rust](stage-6/rust-stage2.json). Raw timings for [original Python](stage-6/baseline-stage2.csv), [tuned Python](stage-6/tuned-stage2.csv), and [Rust](stage-6/rust-stage2.csv).
- ESC-50/FSD50K, [original Python](stage-6/baseline-stage4.json), [tuned Python](stage-6/tuned-stage4.json), and [Rust](stage-6/rust-stage4.json). Raw timings for [original Python](stage-6/baseline-stage4.csv), [tuned Python](stage-6/tuned-stage4.csv), and [Rust](stage-6/rust-stage4.csv).
- First ESC-50 comparison series, including the host slowdown, [tuned Python samples](stage-6/tuned-stage2-first-pass.csv) and [Rust samples](stage-6/rust-stage2-first-pass.csv).
- Build details for [ESC-50](stage-6/build-stage2.json) and [FSD50K](stage-6/build-stage4.json). Individual measurements for [ESC-50](stage-6/build-stage2.csv) and [FSD50K](stage-6/build-stage4.csv).
