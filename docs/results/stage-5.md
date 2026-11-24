# Stage 5 controlled audio-exposure experiment

On the same 400 ESC-50 test clips, mean classifier accuracy was **47.4% with independent training crops** and **57.0% with crops from selected test recordings**. The measured difference was **+9.60 percentage points** across five paired seeds. On the 164 directly exposed clips, the difference was **+19.27 points**.

## What was held fixed

| Input | Rows | Original recording groups |
| --- | ---: | ---: |
| Test, ESC-50 fold 1 | 400 | 311 |
| Validation, ESC-50 fold 2 | 400 | 302 |
| Common training base, folds 3–5 | 932 | 747 |
| Same-class crop slots per arm | 164 | 164 |
| Training examples in each arm | 1,096 | 911 |

Source groups join Freesound IDs and exact WAV hashes transitively. The frozen inventory contained no exact WAV hash collisions across files. Test took precedence over validation, and validation took precedence over training. Two training-pool rows shared sources with validation and were excluded. The donor pool came from the remaining training folds. Reserving the 164 donor groups also removed 102 related rows from the common base. The comparison arm had zero source overlap with validation or test. The exposed arm had exactly the 164 declared test source overlaps and zero validation overlap.

Specimen selection used seed 500207. A test source was eligible if it had a single row in fold 1. The cap was four slots per class, leaving at least one unexposed example per class. Selection yielded 164 exposure rows across 47 classes and 236 unexposed rows. The other three classes, door wood creaks, helicopter, and pig, still contributed to evaluation. Each exposed clip had a same-class comparison donor from an independent recording group, and donors were used once.

Each slot uses a native, three-second PCM excerpt. A preflight found ten all-zero centered crops, including seven exposure crops. Before scoring any test data, the final design changed both arms to use the three-second window with the highest sum of squared PCM samples. Ties favor the window nearest the center and then the earliest start. The source pairs stayed fixed. Validation was rerun on the final crops. Echo checked the 328 generated WAVs against their exact native PCM intervals, confirmed each contained signal, and stored offsets and SHA-256 values. [Experiment design and split checks](stage-5-design/design.json) · [Crop ledger](stage-5-design/crops.csv) · [Exclusions](stage-5-design/exclusions.csv)

The classifier is a three-layer PyTorch CNN initialized from scratch. Echo downmixes and resamples audio to 16 kHz, then uses 48 fixed log-mel bands with a 32 ms window and 20 ms hop. Short clips are centered in five seconds of input, with silence padding. Scaling is fixed, and the training recipe adds no augmentation. A small comparison-only CPU smoke run replayed its learned weights and validation predictions exactly.

The calibration run compared AdamW learning rates 0.001 and 0.003 on the group-disjoint validation set. The choice used final-epoch validation accuracy, with the lower rate breaking ties. The two rates scored 48.00% and 56.75% on the 400 validation clips, so the frozen rate was 0.003. The frozen protocol used 14 epochs, batch size 64, and 252 optimizer updates for every arm. Both arms of each seed pair shared the starting weights, shuffled row order, class labels at each row, validation set, and final-epoch checkpoint rule. Both scored the same file digests in the same test order. [Frozen validation evidence](stage-5-calibration.json)

## Results

Accuracy and macro F1 below are means over five seed pairs. The 95% interval resamples original test source groups with replacement while holding the trained models fixed. Macro F1 uses the classes present in each slice.

| Test slice | Rows | Comparison accuracy | Exposed accuracy | Difference (percentage points) | Source bootstrap 95% interval (points) | Comparison macro F1 | Exposed macro F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All test clips | 400 | 47.40% | 57.00% | +9.60 | +7.06 to +12.35 | 0.452 | 0.552 |
| Directly exposed | 164 | 50.12% | 69.39% | +19.27 | +15.24 to +23.41 | 0.475 | 0.677 |
| Unexposed | 236 | 45.51% | 48.39% | +2.88 | -0.09 to +5.91 | 0.428 | 0.460 |

| Seed | Comparison correct (of 400) | Exposed correct (of 400) | All clips (points) | Directly exposed (points) | Unexposed (points) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 501013 | 223 | 259 | +9.00 | +23.17 | -0.85 |
| 501023 | 214 | 249 | +8.75 | +20.73 | +0.42 |
| 501031 | 213 | 247 | +8.50 | +17.68 | +2.12 |
| 501043 | 125 | 210 | +21.25 | +28.05 | +16.53 |
| 501047 | 173 | 175 | +0.50 | +6.71 | -3.81 |

All five seeds improved on the full test and on the directly exposed slice. Full-test gains ranged from **+0.50 to +21.25 points**, with a sample standard deviation of **7.43 points** across training seeds. Across all 2,000 paired predictions, 332 changed from wrong to right and 140 went the other way. The unexposed slice had mixed results across seeds, and its group-bootstrap interval included zero. The bootstrap intervals describe test-recording variation conditional on these trained models. The seed table shows how much the effect varied across training runs.

The result applies to this CNN, the fixed ESC-50 fold, a 41% direct exposure rate, and the three-second crop policy. The split checks use recorded source IDs and exact file digests. A natural cross-dataset follow-up would require a separate FSD50K train cohort with reviewed alignments and independent same-class FSD50K controls.

## Run verification

The scored run used clean commit [`a790713`](https://github.com/iferdous/Echo-/commit/a790713635036b72429e35c6492f63d55ac18fc1) on Apple Silicon with Python 3.12.16, PyTorch 2.12.1, and four CPU threads. The full run took 142.4 seconds, including 7.6 seconds to verify inputs and compute features. The ten checkpoints and generated WAVs stay in the local experiment directories. Features are computed in memory.

An independent check reconciled all 2,000 saved paired predictions, class counts, update logs, and reported accuracy and macro F1. Retraining seed 501013 reproduced both model states and all 400 predictions per arm exactly. All 53 repository tests passed locally, and a fresh Stage 4 CLI replay reproduced its entire saved JSON result. [Verification record](stage-5-verification.json)

## Reproduce

Start from the [Stage 1 dataset setup](stages-0-1.md#reproduction). Use fresh output directories. These commands consume the pinned ESC-50 inventory and keep crops and checkpoints local.

```bash
uv sync --locked --group experiment
mkdir -p .local/stage5

uv run --group experiment echo-audit experiment prepare \
  --inventory .local/stage1/inventory/assets.csv --esc-root .local/esc50 \
  --out .local/stage5/design

uv run --group experiment echo-audit experiment smoke \
  --inventory .local/stage1/inventory/assets.csv --esc-root .local/esc50 \
  --design .local/stage5/design --out .local/stage5/smoke

uv run --group experiment echo-audit experiment calibrate \
  --inventory .local/stage1/inventory/assets.csv --esc-root .local/esc50 \
  --design .local/stage5/design --out .local/stage5/calibration

uv run --group experiment echo-audit experiment run \
  --inventory .local/stage1/inventory/assets.csv --esc-root .local/esc50 \
  --design .local/stage5/design --calibration .local/stage5/calibration/calibration.json \
  --out .local/stage5/run
```

Use the published `docs/results/stage-5-calibration.json` with the matching design to replay the published run identity. A new calibration records a new run identity.

Environment details, the dependency lock digest, and input and output hashes are in the run summary. Repeated CPU training was verified on the recorded environment. Results may differ across PyTorch builds and platforms. [PyTorch reproducibility notes](https://docs.pytorch.org/docs/stable/notes/randomness.html)

## Evidence

- [Frozen experiment specification](../../bench/stage5-spec.json), [test manifest](stage-5-design/test.csv), [validation manifest](stage-5-design/validation.csv), [common training manifest](stage-5-design/train_base.csv), and [donor manifest](stage-5-design/donors.csv).
- [CPU smoke replay](stage-5-smoke.json) and [frozen validation recipe](stage-5-calibration.json).
- [Full run and paired metrics](stage-5-summary.json), [ordered predictions from both arms](stage-5-predictions.csv), [per-seed class counts](stage-5-per-class.csv), and [epoch training logs](stage-5-training.csv).
