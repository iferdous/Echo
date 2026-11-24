# Stage 3 matcher evaluation

## Design

Calibration and test each used 120 indexed recordings, 40 positive query sources and 40 absent-source query sources. Each absent source had a separate same-class recording in its split's index. Query variants stayed with their original source. The complete source groups, including index background, were disjoint across the two splits, and all 210 Stage 2 development source IDs were excluded. Identical reference bytes were also excluded when selecting across source groups.

Each source produced nine trials. They include an identical-file control, one-, two-, and four-second clean crops, 64 and 128 kbps MP3 versions of the two-second crop, an 8 kHz version, a 10 dB white-noise version, and a 24 dB quieter version. Crop offsets, per-source seeds, audio digests, and the index and query manifest hashes come from the frozen design. Echo uses opaque index identifiers for acoustic search. Source IDs are visible to the provenance baseline on half of the groups and intentionally hidden on the others. [Frozen design](stage-3-design.json) · [Benchmark specification](../../bench/stage3-spec.json)

## Calibration

The selected rule accepted 336 of 360 positive trials. The Stage 2 rule accepted 331 of 360. The selected rule used 14% minimum coverage, 2% minimum landmark support fraction, and a lead of at least 12 aligned landmarks over the runner-up. It accepted 0 of 360 absent-source trials and 0 incorrect recording IDs on positive trials.

The eight predeclared rules were ranked by fewer false accepts among controls, fewer incorrect accepts on positive trials, then more correct accepts. The earlier rule in the grid wins a tie. Each rule reused the same candidate rankings. The policy and calibration record were committed before scoring the held-out audio. [Calibration selection](stage-3-calibration.json) · [Frozen CLI policy](stage-3-policy.json)

## Held-out results

| Input | Correct top 1 | Correct top 5 | Correct accepted | Accepted absent-source |
| --- | ---: | ---: | ---: | ---: |
| Identical file | 40 / 40 | 40 / 40 | 40 / 40 | 0 / 40 |
| Clean crop, 1 s | 39 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| Clean crop, 2 s | 39 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| Clean crop, 4 s | 39 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| MP3, 64 kbps | 39 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| MP3, 128 kbps | 39 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| Resampled to 8 kHz | 39 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| Added noise, 10 dB SNR | 38 / 40 | 38 / 40 | 27 / 40 | 0 / 40 |
| Reduced gain, 24 dB | 38 / 40 | 39 / 40 | 38 / 40 | 0 / 40 |
| **Total** | **350 / 360** | **351 / 360** | **333 / 360** | **0 / 360** |

Echo recorded 0 incorrect accepts and 27 abstentions on positive trials. The weakest condition was added noise at a 10 dB signal-to-noise ratio, with 27 correct accepts out of 40.

The 360 absent-source trials came from 40 recordings. 0 of those recordings had an accepted trial. The approximate 95% Wilson interval for an absent-source recording having any accepted trial is 0.0% to 8.8%. The positive source-group bootstrap interval for average acceptance across the nine conditions is 85.6% to 97.5%.

For the 350 positives with a correct top-ranked result, offset error had a median of 0 ms and a p95 of 4 ms. The maximum was 8 ms.

Byte hashing retrieved 40 of 360 positive trials. The source-ID baseline retrieved 180 of 180 positives with visible IDs and was unavailable for 360 of 720 total trials. Acoustic correct accepts were 168 of 180 visible-ID positives and 165 of 180 masked-ID positives.

On an Apple M3 using the SSD checkout, the 19.8 MiB index built in 5.99 s. Median decode, fingerprint and ranking times were 1.45, 8.12, and 54.42 ms. Total query latency was 64.69 ms median and 199.51 ms p95. Peak process RSS was 150.5 MiB.

The byte-hash and source-ID baselines provide different evidence. Byte hashing can identify identical file bytes. Source IDs can identify a shared original recording without an audio timestamp. The masked-ID baseline reports unavailable. Its coverage and conditional results come from the visible subset of the same evaluation. [Test summary](stage-3-test-summary.json) · [Test per-query results](stage-3-test-queries.csv) · [Calibration per-query results](stage-3-calibration-queries.csv)

## Previous-stage verification

The SSD checkout regenerated the Stage 1 inventory, metadata overlap, and spike manifests byte for byte. The full Stage 2 development spike reproduced all published counts after the move. A replay using the current matcher and the saved Stage 2 SQLite index reproduced each of its 30 decisions, top candidate IDs, and offsets. The generated fixture and the full 41-test suite also passed.

## Reproduce

Run the [Stage 1 dataset workflow](stages-0-1.md#reproduction) first. The benchmark group provides a locked local FFmpeg binary. Each output directory must be fresh.

```bash
uv sync --locked --group benchmark
uv run --group benchmark python scripts/run_stage3.py prepare \
  --root .local/esc50 --inventory .local/stage1/inventory/assets.csv \
  --development .local/stage1/spike --out .local/stage3/design
uv run --group benchmark python scripts/run_stage3.py calibrate \
  --root .local/esc50 --design .local/stage3/design --out .local/stage3/calibration-run
uv run --group benchmark python scripts/run_stage3.py test \
  --root .local/esc50 --design .local/stage3/design \
  --calibration .local/stage3/calibration-run --out .local/stage3/test-run
```

Use this policy explicitly when applying the calibrated rule to an index.

```bash
uv run echo-audit match QUERY.wav --index INDEX.sqlite \
  --policy docs/results/stage-3-policy.json --json
```

The test command validates the design, calibration summary and policy before opening held-out audio. The run summaries record checkout and dependency digests, SQLite index size, per-query decode, fingerprint and ranking timings, and peak process RSS. Compare the regenerated manifest digests with the published design on the same platform and codec build. In a Stage 4 dataset audit, use fresh source cohorts and report any eligibility or coverage differences with the same frozen decision rule.
