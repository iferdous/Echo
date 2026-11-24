# Stage 4 cross-dataset audio audit

Echo scored all **267 ESC-50 queries** against **290 official FSD50K eval recordings**. Independent waveform analysis confirmed that **140 of the 171 same-source pairs** share audio. Echo accepted the right file at the independently supported timestamp for **137 of those 140**. One confirmed pair failed the match policy, and two returned the right file with a different timestamp. One of 96 controls produced an accepted candidate, which remains unresolved.

## Cohort and coverage

The pinned release metadata shows 630 of the 2,000 ESC-50 rows share a Freesound ID with an FSD50K file across all splits. That reproduces the published count. Echo included all 171 rows with an ID present in FSD50K eval, representing 152 distinct sources. The 459 shared-source pairs from FSD50K train and validation are outside this study. An ESC-50 row can still be scored as a control against FSD50K eval when its source ID only appears in another FSD50K split. [Metadata preflight](../evaluation-protocol.md#metadata-preflight) · [LAION overlap analysis](https://github.com/LAION-AI/audio-dataset/blob/main/laion-audio-630k/ICASSP.md#potential-data-leakage)

| Cohort | ESC-50 queries | FSD50K eval references |
| --- | ---: | ---: |
| Known shared source ID | 171 | 152 |
| Same-class controls and distractors | 46 | 42 |
| Broader controls and background | 50 | 96 |
| Total | 267 | 290 |

The cohort covers all metadata-known eval overlaps and 290 of the 10,231 official eval references. It includes 46 ESC-50 controls across 23 mapped classes, with separate FSD50K sources bearing the corresponding labels. Multi-label FSD50K clips can serve more than one class. Both sets of controls exclude previously used Stage 2 and 3 source groups. The summary reports shared-source outcomes for new and previously used sources separately. The control results apply to these selected recordings. The remaining 1,733 ESC-50 rows and 9,941 FSD50K eval recordings were outside the comparison.

## Official audio and integrity

Echo read ranges from both official split ZIP files, parsed their central directory and extracted the selected release WAVs. The two parts total 6,258,901,239 bytes. The range acquisition consumed 194,922,436 archive payload bytes across 294 successful range responses and kept 267,543,840 bytes of decoded WAV input files. A second pass recovered all three members that initially hit HTTP 429. An exploratory full-download attempt was stopped after receiving 680,780,752 bytes. That earlier transfer and small range probes are separate from the reported selective acquisition. [Official FSD50K files](https://zenodo.org/records/4060432#files)

Each selected archive member passed its uncompressed length and ZIP CRC-32 check, decoded as audio, and received a local SHA-256, which Echo verified at index build. The separate official metadata ZIP passed the published MD5 and provided per-recording license links. The published MD5 values for the two full audio parts identify the archive inputs. Validation of the selected audio used member-level checks. [Acquisition ledger](stage-4-acquisition.csv)

## Scoring and independent review

The index uses the frozen Stage 3 fingerprint configuration and matcher policy. Reference identifiers are opaque to the acoustic matcher. Echo first ranked every query from waveform-derived landmarks, then joined the metadata. Review covered every accepted top hit, every available known-source pair, and the six highest-scoring rejected top candidates per query cohort where available. A pair can belong to multiple review groups.

An independent time-domain check searches for 0.5-second waveform windows after downmixing to 8 kHz mono. Confirmation requires two non-overlapping windows with absolute normalized correlation of at least 0.93, lags within 2 ms of a common window lag and a correlation margin of at least 0.03 over competing peaks farther than 40 ms away. Matcher offsets within 32 ms of the independently estimated offset count as agreement. The recorded interval spans the outer confirmed windows and can contain gaps. The waveform check is conservative on brief, repetitive or heavily altered audio. A same-source pair with no strong alignment is unresolved because the clips can be disjoint or the waveform test can miss shared audio.

## Results

| Outcome for the 171 same-source pairs | ESC-50 rows | Distinct source IDs |
| --- | ---: | ---: |
| Shared audio confirmed | 140 | 126 |
| Echo accepted the right file and offset | 137 | 124 |
| Echo accepted the right file with a different offset | 2 | 2 |
| Shared audio confirmed but Echo abstained | 1 | 1 |
| Shared source, waveform overlap unresolved | 31 | 30 |

Some sources have multiple ESC-50 cuts and can appear in multiple rows of the table. Among the 115 queries from sources new to Stage 4, the waveform check confirmed 95 and Echo accepted 93 at the supported offset. Among the 56 queries from earlier-stage sources, it confirmed 45 and Echo accepted 44 at the supported offset.

The matcher accepted 164 of the 171 known-source queries and selected the expected reference each time. Waveform review confirmed 139 of those 164 accepted pairs. Echo declined seven same-source pairs. Waveform review confirmed the clock example below and left six unresolved. Across the whole run, 184 pairs received independent waveform review, including all 165 accepted top results and the 18 highest-scoring rejected pairs selected across the three query cohorts. All 18 selected rejections remained unresolved.

- **Confirmed miss.** The [ticking clock recording](https://freesound.org/s/188033/) had four matching waveform windows at a 0 s offset. Echo ranked the correct file first, but its best landmark alignment used the wrong offset and only 0.31% of the query landmarks. It also led the second candidate by eight votes against the policy's twelve-vote minimum.
- **Offset disagreements.** The [sneezing recording](https://freesound.org/s/118104/) and the [baby crying recording](https://freesound.org/s/59579/) had independently confirmed windows at +11.811 s and +16.095 s. The matcher reported +0.000 s and +13.632 s.
- **Different-source control.** Echo declined all 46 same-class controls and 49 of the 50 broader controls. The single accepted control paired [ESC-50 source 14262](https://freesound.org/s/14262/) with [FSD50K source 198841](https://freesound.org/s/198841/). The two alarms had dominant spectral peaks near 3.89 and 3.94 kHz, while the best waveform-window correlation was 0.852 and no windows met the confirmation rule. This is a candidate for manual adjudication.
- **Unresolved known pairs.** Twenty-five lacked a stable waveform alignment, five had ambiguous repeated waveforms, and one reference was shorter than a single 0.5 s review window. These rows cannot establish whether the dataset excerpts are disjoint.

The study measured shared audio in the selected corpus. Stage 5 measures whether exposure to shared recordings changes a classifier's test score.

## Replayed example

The ESC-50 dog bark `4-207124-A-0.wav` returned FSD50K `reference-0249` at **+0.616 s** in a fresh CLI process. The waveform check independently aligned eight half-second windows at **+0.613125 s**, with median correlation **0.99959**. The CLI and batch decisions, reference IDs, scores and offsets agreed. The local A/B export pairs ESC-50 time **2.500 s** with FSD50K time **3.113125 s**. The aligned waveform traces were inspected visually. The recorded review is waveform-based and leaves human listening for follow-up. [Freesound recording and attribution](https://freesound.org/s/207124/) · [Example evidence](stage-4-example.json)

The run used the locked Python 3.12.16 environment on Apple Silicon from a clean checkout at [`8ca24f3`](https://github.com/iferdous/Echo-/commit/8ca24f325d2f7cc08d95f95c37b59ee70b3a4942). All 49 tests passed locally. The Stage 1 metadata audit reproduced the published JSON byte for byte, and all 30 Stage 2 replayed queries reproduced their decisions, reference IDs and offsets.

## Reproduce

Run the [Stage 1 dataset setup](stages-0-1.md#reproduction) and the [Stage 3 `prepare` command](stage-3.md#reproduce). Those generate the inventory, development spike, and prior-source map. The manifests below freeze the cohort before indexing. Use fresh output directories for each operation.

```bash
mkdir -p .local/stage4
curl -fsSL 'https://zenodo.org/records/4060432/files/FSD50K.metadata.zip?download=1' \
  -o .local/stage4/FSD50K.metadata.zip

uv run python scripts/run_stage4.py prepare \
  --esc-inventory .local/stage1/inventory/assets.csv \
  --ground-truth .local/downloads/fsd50k-ground-truth.zip \
  --stage2 .local/stage1/spike --stage3 .local/stage3/design \
  --out .local/stage4/cohort

uv run python scripts/run_stage4.py acquire \
  --cohort .local/stage4/cohort --metadata .local/stage4/FSD50K.metadata.zip \
  --out .local/stage4/fsd50k

uv run python scripts/run_stage4.py audit \
  --cohort .local/stage4/cohort --esc-root .local/esc50 \
  --fsd-root .local/stage4/fsd50k --out .local/stage4/audit-run
```

If Zenodo returns missing assets, rerun `acquire` with `--resume .local/stage4/fsd50k` and a new output path. The retry copies and rechecks existing WAVs and fetches only unresolved assets. In the audit command point `--fsd-root` at the acquisition directory you intend to use.

`echo-audit audit` also accepts a general query manifest, an audio root, a reference index, and a match policy. It writes separate query-decision and candidate-ranking tables, including failed reads. The Stage 4 research script additionally checks the frozen cohort and adds provenance, waveform review and coverage.

### Replay the dog bark

Use the acquired reference directory that the audit indexed. The export checks both original WAV digests before writing the A/B sample and leaves the dataset files untouched.

```bash
uv run echo-audit match .local/esc50/audio/4-207124-A-0.wav \
  --index .local/stage4/audit-run/index.sqlite \
  --policy docs/results/stage-3-policy.json --json

uv run python scripts/export_stage4_pair.py \
  --reviews .local/stage4/audit-run/reviews.csv \
  --queries .local/stage4/cohort/queries.csv \
  --references .local/stage4/fsd50k/index.csv \
  --esc-root .local/esc50 --fsd-root .local/stage4/fsd50k \
  --query-id esc50:4-207124-A-0.wav --reference-id reference-0249 \
  --query-start 2.5 --out .local/stage4/verified-example
```

## Evidence

- [Frozen cohort](stage-4-cohort.json), [query manifest](stage-4-query-manifest.csv) and [planned reference manifest](stage-4-reference-manifest.csv).
- [Acquisition totals](stage-4-acquisition.json), [per-file source and license ledger](stage-4-acquisition.csv) and [verified index manifest](stage-4-index-manifest.csv).
- [Audit summary and input digests](stage-4-summary.json), [decision and coverage rows](stage-4-audit-queries.csv), [raw batch decisions](stage-4-batch-queries.csv), [ranked candidates](stage-4-candidates.csv) and [independent waveform review](stage-4-reviews.csv).
- [Replayed example](stage-4-example.json) with source references, timestamps and CLI output. Source WAVs, the SQLite index and generated excerpts live in the ignored local directories.
