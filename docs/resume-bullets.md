# Echo résumé and interview notes

- Built Echo, a Python audio-fingerprint auditor with an optional Rust alignment engine, SQLite index, and offline review. Finds shared recording excerpts across datasets and reports time offsets and match evidence.
- Audited 267 real ESC-50 clips against 290 FSD50K references and identified 137 of 140 confirmed overlaps at the supported offset. In a separate five-pair ESC-50 classifier experiment, deliberate exposure to test recordings raised mean accuracy from 47.4% to 57.0% on the same 400 clips. [Cross-dataset run](results/stage-4.md) · [Paired model run](results/stage-5.md)

The audit workload and ranked candidates come from source commit [8ca24f3](https://github.com/iferdous/Echo/commit/8ca24f325d2f7cc08d95f95c37b59ee70b3a4942), audit ID `21351d5272b0c7d71b07a74bc127e9edcbaa89da2dc8808fea8aed0b9a3f5988`. The held-out acceptance study is separate. [Audit summary](results/stage-4-summary.json) · [Waveform review rows](results/stage-4-reviews.csv)

The model run comes from source commit [a790713](https://github.com/iferdous/Echo/commit/a790713635036b72429e35c6492f63d55ac18fc1), run ID `2c117167672477d6faa6c8591f527ff84d17e223529a458135c6e4a348ba889b`. The five signed differences range from +0.50 to +21.25 percentage points. The test-source bootstrap interval for their mean is +7.06 to +12.35 points, conditional on these five fitted pairs. [Run summary and seeds](results/stage-5-summary.json) · [Per-clip predictions](results/stage-5-predictions.csv)

## Interview prompts

- **How does Echo find an excerpt?** It pairs peaks in a spectrogram and stores their hashes with the reference positions. Shared hashes that agree on one reference-minus-query offset vote for the same alignment. Support, coverage, and the lead over the runner-up determine acceptance. Sparse repetitive sounds can vote for several offsets.
- **Why check provenance too?** Several clips can share a Freesound ID and contain different parts of a longer source. Changed bytes can still contain the same bark. The release case shows both a matcher abstention confirmed by waveform review and an accepted alarm pair held for review.
- **What makes the model comparison fair?** Both arms use the same 400 ordered eval clips, model design, seed list, per-class training counts, training budget and evaluation code. Same-class replacements expose the model to 164 declared test groups in one arm. New split composition and new exposure rates would warrant a new experiment.
- **What did Rust change?** It accelerates offset vote accumulation and ranking. The decoder and SQLite lookup still contribute to latency. The cross-dataset warm median was 188.8 ms versus 429.6 ms for tuned Python on the defined Apple M3 workload. Both engines agreed on 1,335 ranked rows in the full replay. [Measured boundaries](results/stage-6.md) · [Full replay receipts](results/stage-8-replay.json)
- **When would you hold a dataset release?** Keep checksum and decode errors visible. Hold unresolved overlaps, quarantine confirmed source groups and re-audit released candidates. Confirm class coverage before comparing model scores. [Real release-review case](real-world-case.md)
