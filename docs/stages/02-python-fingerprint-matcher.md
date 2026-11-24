# Stage 2 — Python fingerprint matcher

**Outcome.** A cropped recording returns its original and where it starts. The lookup works first in memory and then through a persisted local index.

## Build

1. Make a spectrogram from resampled mono audio. Start with 16 kHz, a 512-sample Hann window, and a 128-sample hop. Use deterministic local maxima and record the levels and neighborhood rules. The configuration belongs with the index.
2. Pair each peak with a bounded number of later peaks in a fixed time window. Start around eight target peaks per anchor over a 50–750 ms window. Pack anchor frequency, target frequency, and frame separation into a stable integer. Verify the fields fit in the assigned widths and compare results across independent processes.
3. Store each hash with a track ID and anchor frame. Match query hashes against postings. Vote by track and by reference-minus-query offset. Rank by independent evidence concentrated near one offset. Record support, coverage, score, offset, rank, and whether the result was accepted.
4. Prove the alignment on generated fixtures first. Then run the recorded 20 clean crops and 10 absent-source queries. Initial development targets are 16 correct top-ranked crops and zero accepted absent-source queries in this small sample. Report actual counts and timing errors. Inspect repetitive or quiet failures before changing the parameters.
5. Persist the index with SQLite once the in-memory matcher works. Record schema version, manifest digest, complete fingerprint configuration, and track inventory. Build to a temporary database and replace the target after success. Keep the match decision and output fields stable across backends. Implement the planned `index` and `match` commands. [CLI and data contracts](../build-plan.md#cli-and-data-contracts)

## Check and capture

- Verify known crop offsets and signed offsets, stable ties, empty indexes, insufficient evidence, and non-overcounting of repeated landmarks.
- Reopen the SQLite index in a fresh process and compare ranks, offsets and decisions against the in-memory results. Test a configuration mismatch and an interrupted build.
- Save a row per query with expected reference or absence, actual candidate, estimated offset, decision, and elapsed time.

**Done when** a reader can run the CLI on a generated crop and an ESC-50 sample and inspect the results. Record failures and development-target gaps for Stage 3.

[Implementation results](../results/stage-2.md) · [Stage index](README.md) · [Next stage](03-matcher-evaluation.md)
