# Stage 9 — Hardening and release

**Outcome.** Echo ships a reproducible preview with the matcher and paired model evidence, a concise demo, and claims scoped to what was measured.

The preview includes a real-data split review with a published re-audit, dataset validation, and an audit of the previous stages. [Release verification](../results/stage-9.md) · [Real-world case](../real-world-case.md) · [Preview notes](../preview-release.md)

## Build

1. Test malformed audio, invalid manifests, decode failure, silence, very short audio, repeated hashes, ties, missing data, and interrupted index writes. Confirm predictable statuses and no partial index replacing a previously valid file.
2. Verify supported platforms and actual dependency installation. Run all checked-in tests, formatting, lint, and the fixture benchmark in CI. Run an end-to-end local workflow from a clean checkout with the declared dependency lock.
3. Check the data terms and attribution for release materials. Include code, generated fixtures, reproducible manifests as appropriate, and evidence. Record data and model limitations in the release notes.
4. Assemble the README walkthrough, demo, generated tables, reproducibility instructions and release artifacts. Once checks are green at the intended commit, prepare the preview tag and release notes from that evidence.
5. Write résumé bullets and interview notes tied to the final measured run. Be ready to explain how alignment works, how source IDs can disagree with shared audio, what makes the comparison fair, how to interpret the score difference, and what the profile showed.

## Check and capture

- Confirm commit and artifact hashes, verify every README result against its run, and re-run the demo steps from the documented setup.
- Check release links, installation commands, and model experiment conclusions. Record any scoped weaknesses or remaining platform gaps.
- Save the final CI and evidence links and use them to substantiate any portfolio claims.

**Done when** the preview and evidence are ready for a reader to rerun, with matcher, model and optional native results traceable to their workloads.

[Stage index](README.md)
