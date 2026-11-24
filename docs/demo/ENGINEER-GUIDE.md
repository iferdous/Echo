# Audit audio before trusting a benchmark

Echo finds recordings that share a segment of sound and gives reviewers the file IDs, time ranges, and fingerprint support. Use the evidence to make a split or provenance decision.

## When to run it

| Job | Index | Query | What to do with a candidate |
| --- | --- | --- | --- |
| Check an evaluation split before reporting a model score | Every recording eligible for training | The proposed validation or test split | Listen at the reported intervals, group related files by source, and keep each confirmed recording group on one side of the split. Rerun the audit against the frozen result. |
| Merge two licensed audio collections | Your existing audio catalog | The incoming collection | Check whether renamed, excerpted, or transcoded files duplicate a recording already in the catalog. Keep the provenance and license records for both files. |
| Investigate inconsistent metadata | A reference collection with known source IDs | Clips with missing or conflicting IDs | Inspect the acoustic evidence and original source links. Record acoustic overlap and metadata agreement as separate review findings. |

## Run it on your own audio

Install the locked environment once. The commands expect a reference folder called `train-audio` and a separate query folder called `test-audio`. Use fresh output paths for later runs so the earlier evidence remains available.

```bash
uv sync --locked
run=.local/split-audit-v1
mkdir -p "$run"

uv run echo-audit data manifest train-audio \
  --dataset train --role reference --revision v1 --out "$run/train.csv"
uv run echo-audit data manifest test-audio \
  --dataset test --role query --revision v1 --out "$run/test.csv"

uv run echo-audit index "$run/train.csv" --root train-audio --out "$run/train.sqlite"
uv run echo-audit audit "$run/test.csv" --root test-audio --index "$run/train.sqlite" \
  --policy docs/results/stage-3-policy.json --out "$run/results"

uv run echo-audit review "$run/results" --out "$run/results/review.html"
```

Open `review.html` locally. Filter by decision, search filenames, and expand a row to see ranked candidates and their intervals. The file opens offline and carries the audit run ID and policy digest. The report includes asset IDs and diagnostic text, so review those fields before sharing it. WAVs, fingerprints, and the index stay in the directories you supply.

The manifest scanner hashes regular audio files with supported suffixes and sorts their relative paths. Directory symlinks are skipped and audio file symlinks are rejected. Decoding happens at index or query time. For named datasets with provenance, use Echo’s full manifest schema to preserve source IDs, splits, and attribution. Keep both manifests and `audit.json`, `queries.csv`, and `candidates.csv` as the evidence for the exact run. [Manifest schema](../../src/echo/datasets.py)

## Review exceptions

| What you see | What to check |
| --- | --- |
| **Accepted** across training and test | Listen to both reported intervals. If they share the same recording, move or quarantine the whole source group and rebuild the split. An offset of `+0.752 s` places query time zero about 0.752 seconds into the reference. |
| **No accepted match** but a ranked candidate looks plausible | Compare its support and offset with other candidates. Check that you indexed the relevant source version and enough of the recording. With conflicting evidence, review the raw waveform and provenance. |
| **Insufficient evidence** | Listen to the input for silence, a short transient, or missing content. Try a longer excerpt from the original that includes the event. |
| **Input error** | Inspect the error in `queries.csv` or `review.html`. Recover the missing or damaged file, or deliberately create a new manifest after a version change. A checksum mismatch means the audit used different bytes than planned. |
| **Review rejects the batch files** | Return to the original output directory. Keep `audit.json`, `queries.csv`, and `candidates.csv` together. Use a separate copy for manual edits or joins. |
| **The index is too slow for repeated runs** | Start with a representative subset, reuse the same verified SQLite index, and measure your workload. An optional Rust voting engine can reduce query time on the measured workloads. [Stage 6 benchmark and installation](../results/stage-6.md) |

The Stage 4 ticking-clock pair shows why provenance remains useful even when Echo abstains. Echo ranked the right reference at an incorrect offset and returned `no_match`. Independent waveform review found four overlapping half-second windows at 0 seconds. Record this kind of case for manual review even if it falls below the matcher’s acceptance rule. [Recorded failure and source](../results/stage-4.md#results)

For CI, treat a nonzero audit exit as a processing failure and preserve the output directory for diagnosis. The batch can still write query and candidate files when individual queries fail. An audit can exit successfully and report accepted overlaps. Read those decisions separately and apply your team’s review policy before releasing the split. Keep it tied to a versioned reference manifest, match policy, and test set. A clean report describes what Echo found in the indexed corpus under that policy.

[Run the generated-audio walkthrough](README.md) · [Stage 5 controlled experiment](../results/stage-5.md)
