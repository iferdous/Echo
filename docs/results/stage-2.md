# Stage 2 verification

## Implementation

Echo extracts spectral peaks from 16 kHz mono audio using a 512-sample Hann window and a 128-sample hop. It selects at most five peaks per frame, pairs each anchor with up to eight later peaks, and packs the two frequency bins and quantized time separation into a 30-bit key. The default floor measures the peak level within 16 frames on each side of an anchor. A radius of zero selects the whole-file floor for comparison. [Audio fingerprinting method](https://www.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf)

The matcher groups posting hits by recording and signed offset. Each distinct query hash at a given frame can contribute at most one vote to an offset neighborhood. It suppresses keys with more than 256 stored postings and tests the top-ranked candidate against support, anchor diversity, and coverage requirements. Scores are counts of aligned landmarks. Coverage is the span between matched query anchors divided by the query duration.

Both the in-memory and SQLite implementations use the same fingerprint and matching code. SQLite persists the corpus digest, complete fingerprint configuration and digest, track inventory, posting lists, and schema version. It opens indexes read-only. The CLI checks manifest audio checksums when present and publishes a completed database atomically. An existing index can be rebuilt with `--replace`.

## ESC-50 development spike

Both runs used the same 200 references and the same 30 queries generated in Stage 1. The ground truth comes from the recorded crop offsets. Controls have source IDs absent from the index and include indexed same-class distractors. These are development results used while choosing the fingerprint floor. Stage 3 uses separate source groups for calibration and evaluation.

| Metric | Whole-file floor | Local floor |
| --- | ---: | ---: |
| Correct top-ranked crops | 17 / 20 | 19 / 20 |
| Correct accepted crops | 15 / 20 | 18 / 20 |
| Accepted absent-source controls | 0 / 10 | 0 / 10 |
| Largest offset error among correct top-ranked crops | 4 ms | 4 ms |
| Stored hash postings | 1,535,633 | 2,203,046 |
| SQLite index size | 25.6 MiB | 35.6 MiB |
| SQLite build time | 26.20 s | 20.99 s |
| SQLite query median | 107.6 ms | 370.4 ms |
| SQLite query p95 | 473.1 ms | 604.5 ms |

The runs use the same native Apple Silicon machine and locked Python environment. Wall-clock figures are one observation per setting across the 30 development queries. The source checkout was clean at [commit `9a2ec0b`](https://github.com/iferdous/Echo-/commit/9a2ec0b2e113afefa89256b937267ae0d9483776).

- The silent can-opening crop had zero landmarks and returned `insufficient_evidence`. It stays in the denominator.
- The door-knock crop ranked first at the correct offset under the local floor. Its aligned anchor span covered 15.2% of the query, below the 20% acceptance threshold, so Echo returned `no_match`.
- The local floor recovered three additional accepted correct crops while adding postings. Both settings returned zero accepted matches on the ten controls. This sample offers a development check on false accepts.

SQLite and memory agreed on all 30 complete result payloads for each setting. A fresh CLI process also opened the generated fixture index and recovered the declared source within one 8 ms hop of the expected 0.750 s offset. Tests cover negative offsets, stable ties, duplicate votes, empty indexes, malformed inputs, wrong schemas, configuration mismatches, and failed or interrupted rebuilds.

[Whole-file summary](stage-2-global-summary.json) · [Whole-file per-query results](stage-2-global-queries.csv) · [Local-floor summary](stage-2-local-summary.json) · [Local-floor per-query results](stage-2-local-queries.csv)

## Reproduce

Start from the [Stage 1 dataset commands](stages-0-1.md#reproduction) and use fresh output paths.

```bash
uv run python scripts/run_stage2_spike.py \
  --root .local/esc50 --spike .local/stage1/spike --out .local/stage2/local-floor
printf '%s\n' '{"peak_floor_radius_frames":0}' > .local/stage2/global-floor.json
uv run python scripts/run_stage2_spike.py \
  --root .local/esc50 --spike .local/stage1/spike --out .local/stage2/baseline \
  --config .local/stage2/global-floor.json
uv run echo-audit match .local/stage1/spike/queries/pos-002.wav \
  --index .local/stage2/local-floor/index.sqlite --json
```

Run `uv run pytest` for the generated-data checks. The ESC-50 run writes per-query decision, best candidate, rank, offset error and elapsed time in its output directory. Query rows with input errors retain their IDs and descriptions. Benchmark timings include decoding, fingerprinting, SQLite lookups and ranking over an open connection.
