# Echo implementation stages

Start with [Stage 0](00-environment-and-scaffold.md). See the [Stages 0 and 1 verification](../results/stages-0-1.md), [Stage 2 matcher results](../results/stage-2.md), [Stage 3 held-out benchmark](../results/stage-3.md), [Stage 4 cross-dataset audit](../results/stage-4.md), and [Stage 5 paired model experiment](../results/stage-5.md). Echo's metadata preflight is documented in the [evaluation protocol](../evaluation-protocol.md#metadata-preflight).

| Stage | Work | Evidence required to close the stage |
| --- | --- | --- |
| [0. Environment and scaffold](00-environment-and-scaffold.md) | Python package, development environment, local fixtures, and CI | Fresh install and a generated-fixture test pass |
| [1. Audio foundations and datasets](01-audio-foundations-and-datasets.md) | Audio loading, source IDs, and benchmark manifests | Decode tests and a pinned dataset inventory |
| [2. Python fingerprint matcher](02-python-fingerprint-matcher.md) | Landmarks, offset voting, and SQLite index | A two-second crop returns the original and offset through the CLI |
| [3. Matcher evaluation](03-matcher-evaluation.md) | Calibration, frozen tests, and baselines | Per-query retrieval and false-acceptance results with denominators |
| [4. Cross-dataset audit](04-cross-dataset-audit.md) | ESC-50 against a recorded FSD50K cohort | Acoustic decisions, sample review, and reconciled coverage counts |
| [5. Paired ML experiment](05-paired-ml-experiment.md) | Compare identical test sets under two controlled training conditions | Split checks, paired predictions, and a signed score difference |
| [6. Profiling and optional Rust](06-profiling-and-optional-rust.md) | Measure bottlenecks and test an acceleration candidate if warranted | Timing breakdown and a recorded retain-or-port decision |
| [7. Demo and delivery](07-demo-and-delivery.md) | Walkthrough, reproducible CLI examples, and optional UI | An aligned clip, a rejected distractor, and a chart tied to a real run |
| [8. Benchmark and evidence bundle](08-benchmark-and-evidence-bundle.md) | Reproducible benchmark profiles, reports, and manifests | Regenerated figures and checked machine-readable artifacts |
| [9. Hardening and release](09-hardening-and-release.md) | Fresh-clone verification, release packaging, and résumé evidence | Clean release checks and traceable project claims |

Use the [build plan](../build-plan.md) for shared architecture and command contracts. Use the [evaluation protocol](../evaluation-protocol.md) for source grouping, metric definitions, and experiment rules.

At each stage, record the commit, commands and checks run, paths to outputs, and remaining questions. Keep development trials distinct from frozen runs. Stage 6 can close with a profiling report and the Python implementation.
