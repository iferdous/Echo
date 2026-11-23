# Stage 1 — Audio foundations and datasets

**Outcome.** Echo can load and validate audio consistently, preserve where each recording came from, and produce manifests before it ranks any matches.

## Build

1. Retrieve ESC-50 from the pinned upstream revision in the evaluation protocol. Validate audio paths against the metadata and record counts, sample rates, durations and missing files. Fetch the FSD50K v1.0 ground-truth archive for metadata work and verify its digest. [Dataset inputs](../evaluation-protocol.md#dataset-inputs)
2. Implement manifest loading with stable asset IDs, dataset revision, local path, optional original source ID, class, split role, and checksum. Keep an asset ID distinct from its source recording ID. Reject duplicate asset IDs and emit a useful message for an unresolvable or unreadable file.
3. Implement the audio loader. Decode to float32 PCM, check for finite samples and a valid sample rate, convert to mono, and use band-limited resampling. Save the original rate and channel count for diagnostics. A quiet recording remains valid if it contains samples. Silence can lead to an insufficient-evidence decision downstream.
4. Reproduce the ESC-50/FSD50K ID join from the protocol. Record row and distinct source counts separately. Detect original recording IDs that cross ESC-50 folds. For any later split, validate actual source group membership after applying the declared precedence rule. [Metadata preflight](../evaluation-protocol.md#metadata-preflight)
5. Create deterministic spike manifests with distinct source groups for 20 positive crops and 10 absent-source queries. Record crop offsets, expected reference files, same-class distractors, and corpus inclusion rules. Add a tiny generated corpus for CI. Seed the selection before tuning.

## Check and capture

- Test mono and stereo fixtures, resampling time alignment, invalid metadata, missing and corrupt inputs, and consistent IDs across repeated loads.
- Check that spike positives have indexed references and that every source for an absent-source query is absent from the index.
- Save the pinned input versions, manifest digests, source-group report, and counts of skipped assets with reasons.

**Done when** the fixture and ESC-50 data can pass through the same loader, and the spike corpus and query lists can be regenerated with fixed inputs.

[Implementation results](../results/stages-0-1.md) · [Stage index](README.md) · [Next stage](02-python-fingerprint-matcher.md)
