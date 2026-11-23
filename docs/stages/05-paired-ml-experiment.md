# Stage 5 — Paired ML experiment

**Outcome.** Measure the difference in test performance when a classifier has already heard parts of selected test recordings during training.

## Build

1. Freeze ESC-50 fold 1 for evaluation and fold 2 for validation. Use folds 3–5 as the training and donor pool. Apply the recording-group precedence in the protocol, including the verified metadata exceptions. Save the ordered split manifests and digests. [Main study protocol](../evaluation-protocol.md#main-study-with-known-exposure)
2. Create exposure and comparison slots. Use one known crop per selected test source. Give the comparison arm a crop of the same class from a different recording group. Use the same crop and encoding policy for both arms. Reserve donor recordings out of the shared training base and record all added slots, bytes and source groups.
3. Create a small PyTorch CNN with log-mel inputs and random initialization. Use a short CPU smoke run to verify data loading, seed handling, training and prediction collection. Tune the recipe on validation under the group-disjoint setup and freeze it before scoring the test set.
4. Train paired runs with predeclared seeds, matching initialization, model architecture, training sample counts, optimizer update budget and checkpoint rule. Use at least three paired seeds for the full run. Record runtime, device/backend and package versions.
5. Report exposed minus comparison accuracy in percentage points on the identical test set. Include macro F1, per-seed results, counts and results for directly exposed and unexposed test items, and per-class counts. A paired test-source bootstrap is an optional view of sampling uncertainty. Report it independently of variation across training seeds.
6. Consider a separate FSD50K-train follow-up only if enough audibly aligned pairs and same-origin class controls are available. Publish it as its own experiment with its own denominators. [Cross-dataset follow-up](../evaluation-protocol.md#optional-real-cross-dataset-follow-up)

## Check and capture

- Assert equal test IDs, labels, file digests and ordering, and equal class counts and update budgets between arms.
- Verify that every intentionally shared source is listed and that the comparison arm passes the train/validation/test separation checks.
- Save configuration, predeclared seeds, split validation output, training logs, per-item predictions and the signed deltas. Keep test-score claims tied to the exact experiment and observed result.

**Done when** both arms can be reproduced from the same configuration and the report explains how exposure affected this test, including a small, mixed or zero effect.

[Stage index](README.md) · [Next stage](06-profiling-and-optional-rust.md)
