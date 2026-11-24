# Echo evaluation protocol

Echo has two measurements. The matcher experiment asks whether a query contains audio from an indexed recording. The classifier experiment asks how access to that recording changes a test score. Establish the truth for the classifier experiment independently of the matcher wherever possible. Otherwise a poor matcher can select only its easiest examples and distort the interpretation.

## Dataset inputs

| Input | How we will use it |
| --- | --- |
| ESC-50 | Start with the published metadata and audio. The labels describe 50 environmental sound classes. Use it for the first matcher corpus and for the controlled classifier study. |
| FSD50K v1.0 | Use ground-truth metadata for the primary ID join and clip metadata for attribution. Acquire a reproducible audio cohort for acoustic verification. Keep the original train/validation/eval memberships in all generated manifests. |
| Generated fixtures | Create short paired signals, known offsets, and different recordings for CI. Version the generation code or seed and configuration. |
| Edited query corpus | Generate crops and re-encodes from local dataset files using a versioned specification. Save file IDs, crop positions, edit parameters and expected timings. |

Use the pinned ESC-50 revision from the metadata preflight and the v1.0 Zenodo record for the first report. Read upstream terms and per-recording attribution, especially for any clip used in a public demo. Keep dataset audio and generated derivatives out of the repository and release by default. Publish fixture code, IDs and manifests when appropriate, and retrieval instructions so readers can fetch audio from its source. [ESC-50 data and license](https://github.com/karolpiczak/ESC-50/tree/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6) · [FSD50K release](https://zenodo.org/records/4060432)

### Acquisition sequence

1. Fetch ESC-50 first and FSD50K metadata next. Verify download hashes, inspect the CSV schema, and report loaded assets, durations, format exceptions and provenance coverage. Metadata is enough to test group and split logic.
2. Freeze a small FSD50K audio cohort before opening acoustic results. Sample known source-ID matches across classes and durations in one declared partition, then add separate-source same-class candidates and a seeded broad background sample. Favor the FSD50K eval partition for the first acoustic-only study because its official split is small enough to manage and provides annotations. Any later natural training experiment should use the declared FSD50K train partition for both sets of training additions.
3. The official eval audio archive has two parts totaling about 6.2 GB before extraction. The conventional route downloads, merges and extracts selected files. Keep room for the split files, merged archive and output during the operation. Stage 4 extracted official files using validated byte-range reads across both ZIP parts. The acquisition ledger records payload bytes, CRC checks, and decoded file digests. [Stage 4 acquisition](results/stage-4.md#official-audio-and-integrity)

   A subset of files on disk alone gives no assurance of a smaller network transfer. If individual public upstream clips are available and suitable, record the retrieval path and decoded checksum, and describe that study as a source-recording comparison if the bytes differ from the released FSD50K assets. Missing or changed files are reported explicitly. [Official archive instructions and file sizes](https://zenodo.org/records/4060432#files)
4. Store a corpus manifest with selection seed, selected IDs, exclusions, archive and extracted counts, audio seconds, sizes and checksums. Track which indexed assets were available for every query. A source known to the complete metadata that is outside the audio cohort is out of coverage for that acoustic test.

## Metadata preflight

This audit was run on November 23, 2026, using the official ESC-50 CSV and FSD50K v1.0 ground-truth archive. It joins ESC-50's original Freesound source field, `src_file`, to FSD50K's recording ID, `fname`. An ESC-50 row can describe an excerpt, so the row and source-ID counts both matter. [Pinned ESC-50 metadata](https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/meta/esc50.csv) · [FSD50K v1.0](https://zenodo.org/records/4060432)

| FSD50K partition | FSD50K rows | Matching ESC-50 rows | Distinct shared source IDs | Matching ESC-50 fold 1 rows |
| --- | ---: | ---: | ---: | ---: |
| Train | 36,796 | 399 | 374 | 86 |
| Validation | 4,170 | 60 | 51 | 5 |
| Eval | 10,231 | 171 | 152 | 38 |
| Total | 51,197 | 630 | 577 | 129 |

The 630 rows reproduce LAION's published metadata totals. The 86 fold-1 rows sharing a source ID with FSD50K train are candidates for a controlled follow-up. The Stage 4 study measures acoustic coverage and alignment for official FSD50K eval. The training candidates require their own eligibility and alignment checks. [Stage 4 results](results/stage-4.md) LAION and other benchmarks have already reported or acted on overlaps. The deliverable here is the sound-based audit and reproducible classifier experiment. [LAION overlap table](https://github.com/LAION-AI/audio-dataset/blob/main/laion-audio-630k/ICASSP.md#potential-data-leakage) · [probeBench](https://github.com/birdnet-team/probeBench#tasks)

The inspected ESC-50 file has 2,000 rows and 1,524 distinct source IDs. Four IDs span folds even though the upstream description says fragments from a source stay in one fold. Preserve this observation at the metadata level. Shared IDs alone do not establish waveform overlap, and several rows in these groups have different labels. [Upstream fold description](https://github.com/karolpiczak/ESC-50/tree/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6#dataset)

| Source ID | Folds present |
| --- | --- |
| 131943 | 2, 3 |
| 134049 | 2, 3 |
| 209698 | 4, 5 |
| 234879 | 4, 5 |

### Reproduce the metadata audit

Run the installed CLI against the pinned ESC-50 CSV and the FSD50K ground-truth ZIP. This path needs only those two metadata files. The command verifies both digests before joining them.

```bash
mkdir -p .local/metadata
curl -fsSL https://raw.githubusercontent.com/karolpiczak/ESC-50/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/meta/esc50.csv \
  -o .local/metadata/esc50.csv
curl -fsSL 'https://zenodo.org/records/4060432/files/FSD50K.ground_truth.zip?download=1' \
  -o .local/metadata/fsd50k-ground-truth.zip
uv run echo-audit data audit \
  --esc50-metadata .local/metadata/esc50.csv \
  --fsd50k .local/metadata/fsd50k-ground-truth.zip \
  --out .local/metadata/audit
```

The generated `overlap.json` includes the exact input digests, counts by FSD50K partition and ESC-50 fold, and the four cross-fold source groups. [Saved Stage 1 output](results/stage-1-overlap.json)

## Matcher evaluation

### Evidence types

Record the evidence in independent fields so one pair can carry several facts.

- **Identical file** means SHA-256 over input bytes matched. A re-encode can change all the bytes.
- **Shared source ID** means source service and source ID agree. The two assets can cover different parts of that source.
- **Acoustic alignment** means the matcher found a candidate with enough landmarks concentrated around a consistent offset. Store offsets, support and score for accepted and rejected candidates.
- **Reviewed overlap** means the available audio supports the same audible recording segment. Save the paired intervals and reviewer verdict as confirmed, rejected or unresolved. Source-ID agreement can help identify what to review. A same-source pair with disjoint excerpts is a provenance observation.
- **Uploader overlap** is descriptive metadata if present. Keep it outside the recording-match count and outside the primary claim.

### Calibration and test

1. Keep calibration and evaluation queries separated by original recording group. Derive all edits of a source within that group's designated set. Positives require the known reference to be in the index; absent-source negatives require all known source assets to be outside the index. Measure coverage before performance.
2. Predeclare a manageable grid. For example, compare clean crops at 1, 2 and 4 seconds when possible, fixed MP3 settings such as 64 and 128 kbps, sample-rate conversion, and a small labeled noise slice. Use the same eligible source cohorts when comparing edits where practical. Log unavailable variants explicitly. Keep near-silence, quiet clips, repetitive ambience and same-class differences in the set. Record distortion types that violate a constant offset, such as tempo changes, as a separate exploratory slice.
3. Set a minimum distinct-landmark count and time coverage, optionally a margin over the runner-up. Choose the operating point on calibration data based on the relative cost of false matches and missed matches. Record the complete rule and its digest before the frozen run. Keep uncertain matches visible to reviewers without automatically treating them as positives.
4. Compare exact file hashing, the source-ID join where IDs are populated, and the acoustic matcher. Add an ID-masked slice by hiding metadata from known pairs to show what the matcher can recover from sound. Keep those controlled pairs distinct from genuinely missing or disagreeing IDs. Include metric availability with each baseline.
5. For cross-dataset results, check reproducibility with a declared corpus and sample. Review stratified results across high-confidence, borderline and discordant-ID pairs, plus failures among eligible known-source positives. Listen where possible, inspect aligned segments, and capture uncertainty. For a small audit, peer review disputed and ID-disagreeing examples if a reviewer is available. Show the checked counts. Unreviewed candidates contribute candidate counts and can support clearly labeled sample estimates.

### Metrics and decision rules

| Metric | Denominator or interpretation |
| --- | --- |
| Top-1 / Top-5 retrieval | Eligible known-alignment positive queries with the reference indexed, regardless of acceptance threshold. |
| Accepted correct match rate | The same eligible positive queries, counting correct accepted top results. Report wrong accepted positives and abstentions as well. |
| False acceptance rate | Confirmed absent-source queries. Report same-class negatives separately and count all attempted, valid queries. |
| Reviewed precision | Confirmed among adjudicated accepted pairs. Show unresolved counts and the sampling design. Avoid projecting an unweighted convenience sample to the full population. |
| Offset error | Absolute predicted minus known offset, on correctly matched scored positives. Report median and a tail percentile with sample size. |
| Acoustic study coverage | Audio-covered eligible rows and distinct source groups relative to the manifest. Show missing assets, exclusions and unknown alignment eligibility. |
| Timing | Time index build, feature extraction and search separately. Also report end-to-end query latency with a named machine and warm/cold conditions. Include counts, p50/p95, disk size and peak RSS measurement method. |

Report counts alongside proportions. For repeatedly transformed queries, record uncertainty and resample or group by source for estimates across recordings. A small hard-negative sample cannot establish a very low false-acceptance rate. The frozen test is used for reporting. Any tuning prompted by test errors becomes a new version and uses a fresh holdout for a new primary result.

## Model experiment

### Main study with known exposure

Use ESC-50 and construct the exposure deliberately so Echo can finish a valid model study even if the FSD50K cohort is slow to acquire or has limited usable alignment pairs. This main result answers how a specific exposure changes one classifier's score under controlled conditions.

1. **Freeze the split.** Start with fold 1 as the fixed test set and fold 2 as validation. Build training and donor candidates from folds 3–5. Build source groups using original recording IDs and conservatively reviewed duplicate links. Apply precedence test, then validation, then training. Exclude conflicts from lower-precedence sets and log every exclusion. Validation and test keep their selected inputs after this step, and both arms evaluate exactly the same bytes.
2. **Choose treatment slots before looking at scores.** Choose eligible test recordings with distinct source groups and classes that support independent controls. Use one treated crop per selected source for the primary comparison. For every treated crop from the corresponding test recording, assign a donor crop from a different, group-disjoint recording in the same class. Draw donors from the training pool, reserve them out of the common base and avoid donor reuse in the primary run. Choose duration, crop rule, optional re-encoding and gain policy in advance and apply them equivalently to both arms. Retain exact offsets and the generated asset hashes. Record the number of exposed test rows and source groups, and freeze a subset of test rows that remains unexposed.
3. **Train two comparable arms.** Both use the same base and the same number of added slots. The exposed arm fills its slots with deliberately inserted crops of selected test recordings. The comparison arm fills them with the matched independent donor crops. Assert identical training set size and counts per class. Hold batch size, number of optimizer updates, validation schedule, model initialization, feature extraction, and checkpoint rule fixed within each seed pair. If augmentation is added, freeze the policy for both arms. Avoid labels or values obtained from test data in shared preprocessing; use fixed scaling or fit learned preprocessing using eligible training data, following a documented rule.
4. **Freeze the model before looking at the test.** Use a small CNN on log-mel inputs, random initialization, cross-entropy and a fixed training budget. Start with an unaugmented baseline and tune the training recipe on validation with the group-disjoint setup. Run a tiny CPU experiment first to verify wiring. Use at least three predeclared paired training seeds for the full run; five is a practical default if timing allows. Record the independent random seed for specimen selection, model initialization and sampling policy. Track the exact runtime and backend, including CPU/MPS and reproducibility constraints. [PyTorch reproducibility notes](https://docs.pytorch.org/docs/2.15/notes/randomness.html)
5. **Read the outcome as a signed difference.** Report exposed minus comparison accuracy in percentage points on the full fixed test and on directly exposed and unexposed slices. Include macro F1, per-class counts and paired prediction changes. Report per-seed deltas and their dispersion. A paired bootstrap across test source groups can summarize sample uncertainty conditional on the trained models. Keep that uncertainty distinct from variation across training seeds. A small or unstable difference is a result. Scope any positive difference to this model, dataset, exposure rate and crop policy.
6. **Check sensitivity only when it answers a question.** If the first run is stable, consider a second predeclared exposure rate or alternate donor seed. Record it as sensitivity analysis and preserve the original result.

| Experiment invariant | Check |
| --- | --- |
| Test untouched | Test asset IDs, labels, bytes and order match across both arms. |
| Expected exposure | Only declared treatment groups cross into the exposed train arm. Fold labels alone do not satisfy this check. |
| Comparison group separation | Comparison train, validation and test share zero eligible original recording groups. |
| Fair training | Added slot counts, class counts, base examples, crop policy and update budget match. |
| Reproducibility | Pair seed, manifests, config, model revision, log and predictions are recorded for both arms. |

### Optional real cross-dataset follow-up

Use the same fixed ESC-50 evaluation split and a reviewed FSD50K train cohort. Every exposed FSD50K asset must audibly align with a test recording, have a defensible mapped ESC-50 class and have documented split provenance. Compare it with an independent FSD50K train recording mapped to the same class, with comparable crop length and preprocessing. Keep both arms equal in originating dataset, training count and class counts. Log mapping ambiguity and omit ineligible pairs by a predeclared rule. If enough comparable pairs remain, train and report this result separately. A result from the controlled ESC-50 experiment gives evidence only about its deliberately created exposure.

## Results and release evidence

Each run should produce a manifest with repository commit, config and input digests, seeds, corpus revisions, dependency lock digest, OS/hardware, and start/end times. Save per-query outcomes, pair evidence, manifest coverage, split validation, per-seed predictions, aggregate metrics and generated tables. Record limits such as missing downloads, partial review, transformations with weak coverage, and timing environment in the run manifest. Generate the README table and figures from the saved outputs and verify them in CI.

Show one aligned clip with its offset, one clean rejection and one representative failure. Use the same named run in the README, demo and any résumé claim. Treat the metadata preflight, acoustic benchmark, ML experiment and optional acceleration as independently attributable evidence.
