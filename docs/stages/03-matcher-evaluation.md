# Stage 3 — Matcher evaluation

**Outcome.** Echo has a measurable operating point and a held-out evaluation that includes both matching clips and convincing distractors.

## Build

1. Freeze calibration and test source groups separately. Keep every derivative of a recording in one query group. Record the indexed background, reference availability, and exclusion reason for each query.
2. Generate a small comparison grid with clean crops, MP3 re-encodes, resampled clips and a labeled noise slice. Record crop duration and position, codec parameters, and random seeds. Include quiet signal, repetitive ambience, and different recordings of the same class.
3. Implement byte-hash and source-ID baselines. The acoustic matcher receives only audio and opaque asset IDs. Add a slice that masks IDs for known pairs. Keep genuinely missing IDs separately identifiable in the audit.
4. Tune minimum landmark support, coverage, and any score margin using calibration data. Record the candidate settings tried, the chosen decision rule, and its digest. Use the same frozen rule for test and cross-dataset audit runs.
5. Run the frozen benchmark and save per-query results. Report top-1 and top-5 retrieval, accepted correct matches, false accepts on valid absent-source queries, offset error and abstentions. Break down at least clean, codec, and same-class-negative cases. Flag groups with a smaller eligible sample. [Matcher metrics and denominators](../evaluation-protocol.md#metrics-and-decision-rules)

## Check and capture

- Validate known reference inclusion, source-disjoint query groups, and one output per trial including rejected and failed inputs.
- Check the benchmark metrics on hand-computable fixtures. Distinguish reporting by query from reporting by original recording group.
- For a missed slice, retain the frozen result and use a separately versioned experiment with a fresh holdout if the result motivates tuning.

**Done when** a repeatable run produces per-query evidence and aggregate tables for the recorded calibration and test configuration.

[Stage index](README.md) · [Next stage](04-cross-dataset-audit.md)
