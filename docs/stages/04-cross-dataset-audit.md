# Stage 4 — Cross-dataset audit

**Outcome.** Use audio to audit a declared ESC-50/FSD50K cohort. Verify which candidates share audible content and explain how much of the known metadata overlap was eligible for the comparison.

## Build

1. Use the official metadata preflight to select the cohort. Start with FSD50K eval for the acoustic study. Include representative shared-ID pairs, same-class distractors from different sources, and a seeded broader background. Freeze the IDs and split definitions before checking matcher results.
2. Choose and record the acquisition method. Budget for both FSD50K eval split archive parts and local extraction. Log bytes transferred, files kept, unavailable recordings, and the selected audio digests. If using Freesound files as substitutes, label the run by the audio actually used. [Archive and cohort rules](../evaluation-protocol.md#acquisition-sequence)
3. Build the FSD50K index with the Stage 3 fingerprint configuration and use the [frozen match policy](../results/stage-3-policy.json) for decisions. Search the eligible ESC-50 files against it. Have the acoustic path rank on sound, then append source IDs and label information to candidate evidence.
4. Verify a stratified sample of accepted, borderline, discrepant-ID and missed known-source cases. Compare aligned excerpts by listening and inspecting the time offset. Record confirmed, rejected or unresolved verdicts and keep metadata-only agreement visible. Audit genuinely missing or differing IDs separately from cases where IDs were hidden for a benchmark.
5. Report published metadata totals, Echo's reproduced join on the full metadata, and eligible results in the indexed cohort. Show how missing assets, disjoint source excerpts and matcher misses contribute to the gaps. Report both pair/row and unique-source units where meaningful.

## Check and capture

- Re-run a selected query with the saved manifest, index configuration, and source URLs. Verify the output identifies the run and published coverage.
- Confirm that counts distinguish out-of-cohort records, rejected matches, audio-confirmed pairs and unreviewed candidates.
- Capture the frozen cohort manifest, audit JSON/CSV, review decisions, coverage table, and an aligned example if a pair can be verified.

**Done when** the acoustic claim is scoped to the actual cohort and reviewed evidence, with uncertainty and any lack of confirmed pairs visible in the results.

[Stage index](README.md) · [Next stage](05-paired-ml-experiment.md)
