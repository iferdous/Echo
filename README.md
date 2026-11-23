# Echo

Echo is a planned audio dataset audit tool. Feed it a clip and a collection of recordings. It will look for the same sound recording, identify where the clip lines up in the original, and report matches that cross a model's training and test sets. A separate experiment will measure how those matches affect a classifier's score.

A five-second excerpt can come from the same recording as a longer file with a different name and encoding. Echo will use acoustic fingerprints to find the shared audio and return a timestamp and matching evidence. The two datasets for the first study are ESC-50 and FSD50K. LAION has already documented overlap in their source IDs. Echo will use those IDs to check its work and test what it can recover from the audio itself. [ESC-50](https://github.com/karolpiczak/ESC-50) · [FSD50K](https://zenodo.org/records/4060432) · [LAION overlap analysis](https://github.com/LAION-AI/audio-dataset/blob/main/laion-audio-630k/ICASSP.md#potential-data-leakage)

## Build documents

- [Build plan](docs/build-plan.md) covers scope, architecture, milestones, commands, tests, and the first implementation session.
- [Evaluation protocol](docs/evaluation-protocol.md) covers the dataset audit, how to verify audio matches, and the controlled model experiment.

## Planning baseline

A metadata-only join reproduced 630 ESC-50 rows with IDs shared by FSD50K. It also found four ESC-50 source IDs that span more than one fold in the inspected metadata. These observations define the starting point for the acoustic audit and the experiment's source-group checks. The matcher and model experiment are planned work. [Audit inputs, counts, and reproduction](docs/evaluation-protocol.md#metadata-preflight)
