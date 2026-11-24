# Stage 6 — Profiling and optional Rust

**Outcome.** Identify where Echo spends time and memory across representative queries. Add an experimental Rust backend when a measurable lookup bottleneck justifies the work.

The [Stage 6 report](../results/stage-6.md) includes the measured timings, the optional Rust backend decision, and full Stage 4 result parity.

## Build

1. Profile decode and resampling, spectrogram/peak extraction, database retrieval, and voting separately. Measure end-to-end query latency and build time as well. Use the same manifests and stable query order across implementations.
2. Record warm and cold conditions, repetitions, corpus and index size, median and p95 latency, build throughput, and process peak RSS. Name the machine and capture the memory measurement method.
3. Pick the candidate from the measurements. If Python lookup or voting dominates a user-facing cost, try one native component fed with the same fingerprints. Compare it against the tuned Python path. If another component dominates, record what the profile showed and close the stage with that evidence.
4. For an in-process native experiment, use Rust with PyO3 and maturin. Keep the same offsets, tie-breaking rules and Python output contract. Include conversion and boundary overhead in end-to-end timings. Keep a Python fallback and record whether the native option helps the actual workload.

## Check and capture

- Compare complete ranked results, offsets, acceptance decisions and error handling across the Python and native variants if the port is explored.
- Compare on the same machine, with the same corpus, index contents, queries and timed boundaries. Report absolute times and measured memory.
- Save the profile, timed samples, environment and written decision. Benchmark evidence can support retaining Python.

**Done when** Echo has a measured bottleneck analysis and a decision about whether to port, keep, or retire the native component.

[Stage index](README.md) · [Next stage](07-demo-and-delivery.md)
