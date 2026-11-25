# Echo preview 1

Echo audits audio corpora for shared recordings before an ML team relies on a test score. It finds matching excerpts by sound and provides the reference, signed offset, and ranked evidence for review. The release includes the Python CLI, the optional Rust alignment source, the recorded evidence, and the reproducible walkthrough.

## Real-world case

Echo audited 267 proposed ESC-50 test clips against 290 official FSD50K eval references used as an example training index. File checksums alone flagged zero. Independent waveform review confirmed 140 overlaps. Applying the case policy quarantined 145 clips including related source-group members, held 27 for follow-up, and retained 95. A fresh recheck of those 95 returned zero accepted matches and zero input errors. The retained subset spans 44 of the original 50 classes. [Case study and replay](real-world-case.md)

## Measured results

| Workload | Result |
| --- | --- |
| Frozen held-out matcher | Rank 1 found 350/360 positives and rank 5 found 351/360. The frozen policy accepted 333/360 positives and 0/360 absent-source trials. |
| Cross-dataset waveform checks | Echo found 137/140 confirmed clips at a supported offset. The other three comprise two offset disagreements and one abstention. |
| Controlled ESC-50 classifier | Mean accuracy was 47.4% with independent training crops and 57.0% with deliberately exposed crops, a +9.60-point difference on the same 400 clips across five paired seeds. |
| Cross-dataset warm query time | Median 429.6 ms in tuned Python and 188.8 ms with Rust voting on an Apple M3 using a reused SQLite connection. |

The held-out trials reused recordings across transformations. The model bootstrap interval of +7.06 to +12.35 points resamples test sources conditional on the fitted models, and the gain varied across seeds. The case’s revised test manifest is a different cohort from the fixed classifier experiment. [Benchmark tables and machine-readable results](results/stage-8.md)

## Install and verify

Clone this preview tag and run `uv sync --locked --group demo` with the pinned Python 3.12 runtime. Run `uv run --no-sync echo-audit bench --profile fixture --out .local/preview-fixture` for a small generated benchmark. Verify the download hashes with the attached `SHA256SUMS`. The core Python wheel uses package version `0.1.0.dev0`. Its preview tag identifies the source and release assets. [Reproduction guide](reproduce-evidence.md) · [Demo and captions](demo/README.md)

## Preview limits

Echo can miss overlapping excerpts in noisy, short or repetitive inputs, and it can return an unsupported offset. The report applies to the indexed recordings and frozen policy. The model result applies to the documented experiment. The local measurements come from the named Apple M3 system, and CI uses hosted runners. Dedicated-host performance measurements and independent replication beyond this project’s pinned dataset experiment remain open. The Python CLI is verified on macOS arm64 and CI’s Ubuntu and Windows images. The optional Rust extension was exercised on macOS arm64 and Ubuntu x64. [Release verification](results/stage-9.md) · [Dataset terms](data-sources.md)
