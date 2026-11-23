# Echo build plan

## The product

An ML practitioner should be able to point Echo at two folders or manifests, identify recordings that cross the training/test boundary, and inspect the evidence behind each candidate. The shortest demo is a cropped, re-encoded clip going in and the original recording plus its timestamp coming out. The portfolio release adds a cross-dataset report and a controlled experiment showing what happened to one classifier's test score.

This plan consolidates Muse's handoff into an implementation path. The existing public work includes landmark-based fingerprinting, the ESC-50 and FSD50K datasets, and prior overlap counts. Echo's deliverables are a usable split audit, a measured comparison of matching methods under realistic edits, and a paired training experiment. [Audfprint](https://github.com/dpwe/audfprint) · [LAION overlap analysis](https://github.com/LAION-AI/audio-dataset/blob/main/laion-audio-630k/ICASSP.md#potential-data-leakage) · [probeBench's related exclusions](https://github.com/birdnet-team/probeBench#tasks)

## Scope and finish line

**First working version.** Index a small ESC-50 corpus, query a two-second crop, return the original and an offset, and reject a similar sound from a recording outside the index. Save every query and its measured result. Build this on the Apple Silicon Mac using Python.

**Portfolio release.** Run the fingerprint benchmark across a declared corpus and a frozen test manifest. Audit a reproducible ESC-50/FSD50K cohort with examples a reader can verify. Complete the controlled training experiment and generate tables from run artifacts. Ship a recorded demo and a copyable CLI walkthrough. Work through the full evidence path even if real-world overlap recovery or the ML effect is small.

**Extensions.** A PyTorch cross-dataset experiment depends on usable naturally overlapping clips and same-origin controls. A Rust implementation depends on profiling. A hosted upload interface depends on a use case beyond the CLI and recorded demo. These extensions can be evaluated independently after the main results are available.

## Stack

| Component | Default | Purpose |
| --- | --- | --- |
| Project and tools | Python 3.12 candidate, uv, Ruff, pytest | Verify native ARM64 wheels before locking an exact Python minor and dependencies. Put PyTorch in an optional dependency group. |
| Decode | SoundFile, NumPy, SciPy | Decode WAV/FLAC, normalize channels and sample rate, compute spectrograms, and select peaks. |
| Codec tests | FFmpeg | Produce and decode explicit MP3 variants. Record the encoder, arguments, and version. |
| Matcher | Python landmark hashing and offset voting | Implement the baseline from the published approach. Use in-memory postings during the spike. |
| Persistent index | SQLite through Python's standard library | Store track IDs and hash postings with a format/configuration version. Keep the CLI usable across processes. |
| Model | PyTorch, small CNN from random initialization | Train on fixed log-mel features as a controlled measurement of the impact of known overlap. |
| Outputs | CSV, JSON, Markdown, static plots | Save evidence first and generate a short report and figures from it. |
| CI | GitHub Actions, Ubuntu first | Exercise contracts, generated fixtures and a small reproducible smoke benchmark. Add Windows or macOS coverage when support is verified. |
| Optional acceleration | Rust, PyO3 and maturin if an in-process port helps | Port only a measured hot path and preserve Python results. Compare on the same hardware and corpus. |

## How it fits together

~~~text
Training manifest and test manifest
          |
          +-- Source-ID join and exact file hash as baselines
          |
          +-- Decode -> mono and resample -> spectrogram -> peak-pair hashes
                           train side -> write fingerprint index
                            test side -> search and align candidate matches
          |
          +-- Pair evidence -> match report -> adjudicated recording groups
                                             -> frozen experiment inputs
                                             -> paired model runs -> report
~~~

A file is one asset. A recording can have several assets, including excerpts. Dataset membership, class, upload metadata, and split are properties of the manifest. Acoustic similarity does not change a manifest entry. Downstream code only groups recordings from declared source IDs or reviewed evidence. See the [evaluation protocol](evaluation-protocol.md) for how these groups enter the experiment.

### Proposed project layout

~~~text
src/echo/
  __main__.py          CLI entry point
  audio.py             decode, validation, and resampling
  fingerprint.py       spectrogram peaks and stable landmark hashes
  index.py             in-memory postings first, then SQLite persistence
  matcher.py           offset voting, ranking, and accept/reject decisions
  datasets.py          manifests, provenance, and source-ID checks
  experiment.py        paired model execution and prediction outputs
  report.py            tables and plots from recorded results
tests/                 deterministic fixtures and behavior checks
bench/                 versioned configurations and benchmark definitions
docs/                  build plan, protocol, and release evidence
~~~

Add files when their responsibilities exist. Keep downloaded datasets and generated working files in ignored local paths. Use a separate local output path for quick runs so exploratory metrics cannot overwrite frozen results.

### CLI and data contracts

These are planned interfaces. Each command should have a human-readable summary and write structured evidence where specified.

~~~text
echo index TRAIN.csv --out train.sqlite
echo match QUERY.wav --index train.sqlite --json
echo audit TEST.csv --index train.sqlite --out audit/
echo bench --spec bench/matcher-test.json --out run/
echo experiment --spec bench/paired-esc50.json --out run/
echo report run/
~~~

- A track manifest includes a stable asset ID, dataset/version, relative path, role, optional source service and source ID, label, and attribution reference. Record file checksum and decode status after scanning. Keep missing metadata explicit. Resolve paths relative to the manifest or a specified dataset root.
- An index stores the version, full fingerprint configuration or its canonical hash, dataset manifest digest, stable track IDs, durations, and postings of hash to track ID and anchor frame. Write a fresh database off to the side and replace the target only after successful completion. A query with a mismatched fingerprint configuration fails clearly.
- A match includes query ID, candidate ID, query-relative and reference-relative matched coordinates where available, signed alignment offset, support count, coverage, raw score, ranking, and acceptance decision. Define offset as reference time minus query time. Use a stable tie-break by track ID. Raw scores are heuristic scores.
- Distinguish a decoded query with no accepted hit, insufficient audio evidence, and a decode or input error. Batch audits must preserve a row for errors and rejected queries. Pair/report JSON and CSV carry a schema version and a shared run ID.
- The metadata comparison can annotate reported candidates after the audio decision. The acoustic path gets audio and opaque track IDs during evaluation, so filenames and Freesound IDs cannot determine the ranking.

## Implementation stages

The [stage index](stages/README.md) contains the ten numbered implementation plans. Each stage specifies its tasks, tests, evidence, and completion criteria. Start with [Stage 0](stages/00-environment-and-scaffold.md).

The first working lookup is the Stage 0–2 deliverable. Stages 3–5 build the matcher benchmark, cross-dataset audit, and model comparison. Stage 6 profiles the workflow and makes the Rust decision. Stages 7–9 build the demo, evidence bundle, and release.

### Operational behaviors to test

- Decoding handles silence, duration below the minimum, corrupt or unreadable files, downmixing and resampling. Batch processing accounts for each input.
- Index creation handles duplicate stable IDs, malformed manifests, configuration changes, an interrupted build, and reopen from a separate process.
- Ranking handles repeated hashes, short or quiet clips, negative offsets, single-candidate ties and empty indexes. Offset tests state tolerance in seconds and tie it to frame/bin resolution.
- Audit tests check training/test direction, same-class negatives, deterministic ranking, missing provenance, and reporting of accepted candidates separately from reviewed matches.
- Experiment checks verify split disjointness against actual source groups, fixed evaluation IDs and bytes, equal class counts, fixed training update budgets, and exact swap membership. The tiny CPU job tests plumbing and metrics. Frozen local runs produce project claims.
- Verify formatter, lint, tests, and a generated-fixture smoke run in CI. Put benchmark timing on a named machine with the hardware and measurement method recorded. Use OS-level peak RSS or a clearly labeled alternative, as Python allocation tracing alone misses native buffers.

## Publishing the work

Record a short demo of an excerpt resolving to its original timestamp, one similar clip being rejected, and a generated chart of the model comparison. A synthetic fixture can provide the public audio example while the CLI and report link to original dataset sources for the recorded study. Use the results to draft résumé bullets only after the relevant run can be inspected.

The release evidence should include commit, lockfile digest, dataset revisions, manifest digests, configuration and metric definitions, machine/OS, timing boundaries, query-level results, split audits, prediction files or an appropriate shareable summary, and instructions for reproducing each published table. See the [evaluation protocol](evaluation-protocol.md#results-and-release-evidence).

## Decisions that refine the original handoff

- Source groups are audited explicitly. The metadata preflight found four ESC-50 source IDs spanning folds. The controlled model run introduces known shared audio and uses same-class replacements to hold the training budget constant.
- Source IDs, acoustic overlap and review verdicts have independent fields. Different labels or different takes can share a source. The released report keeps those distinctions visible.
- Start FSD50K with metadata and budget for split archives. Selective extraction can reduce the files kept on disk. Archive access and bytes transferred need separate verification.
- The application and model experiment can ship with descriptive findings. Timing targets, accuracy targets and the direction of the model effect remain hypotheses until measured. A static demo and reproducible report carry the first release.

## First implementation session

Start with the package, a generated fixture and a small ESC-50 lookup. End the session with one successful crop alignment, one absent-source rejection, and a saved query-level run. Then expand the index and hard negatives using the same command. The ML experiment, Rust, web API and deployment can wait until that loop is working.
