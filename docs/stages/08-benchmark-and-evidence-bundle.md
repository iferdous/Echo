# Stage 8 — Benchmark and evidence bundle

**Outcome.** Every reported number can be traced to a named run with documented inputs and regenerated tables.

The completed [report](../results/stage-8.md), [checksummed ZIP](../results/echo-evidence.zip), and [reproduction guide](../reproduce-evidence.md) cover the fixture, full replay, and published-result checks.

## Build

1. Define a generated-fixture CI profile and a full local profile. Keep the CI profile deterministic and small. Validate the benchmark output structure and run identifiers before producing tables.
2. Save the commit, locked dependencies, data revisions, manifest digests, configurations, seeds, review scope, runtime versions, hardware, and run times. Produce structured per-query results, audited pair evidence, split assertions, aggregate metrics and available prediction summaries.
3. Build report generation from saved outputs. Show denominators for retrieval, false acceptance and audit coverage. Include grouped uncertainty or seed variability where applicable. Use one canonical run per headline number and label timing conditions. [Evidence and reporting](../evaluation-protocol.md#results-and-release-evidence)
4. Add a report check that detects drift between generated files and the README's measured tables. Generate plots from the same aggregate data and attach enough run metadata to find the underlying experiment.
5. Package approved text artifacts and checksums. Include a reproduction guide that states the dataset needed for each profile, where to get it, and what the reader can expect to vary across machines.

## Check and capture

- Rebuild a report from a saved run without running training again. Confirm that human-readable values match the machine-readable results.
- Run the fixture profile in a fresh checkout. Check that the full profile rejects missing data or incomplete artifacts with actionable errors.
- Keep partial runs, weaker slices and observed negative results visible with the correct scopes.

**Done when** a reviewer can reproduce the fixture benchmark and regenerate every published table from the corresponding evidence bundle.

[Stage index](README.md) · [Next stage](09-hardening-and-release.md)
