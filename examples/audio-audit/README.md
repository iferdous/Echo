# Audit real audio with Echo

[Open the interactive example](https://iferdous.github.io/Echo/) · [Engineer guide for your own datasets](../../docs/demo/ENGINEER-GUIDE.md) · [Full cross-dataset case](../../docs/real-world-case.md)

A team plans to test its classifier on clips from ESC-50. Its training audio includes Freesound recordings, so it wants to catch excerpts the model may already have heard. The example uses three official FSD50K evaluation WAVs as a small stand-in for that training catalog. The browser plays the original clips, displays the votes from Echo’s recorded audit, and lets you change how much evidence the review rule requires.

## Start with the dog bark

1. Select **Dog bark from ESC-50** and play each clip. The catalog player can jump to Echo’s **+0.616 s** offset. The 267-query study independently checked the waveform at **+0.613125 s**. [Full recording evidence](../../docs/results/stage-4.md#replayed-example)
2. Switch to the **2-second dog crop** or **64 kbps MP3 crop**. Both match at **+2.208 s**. Echo’s score drops from **676** votes for the crop to **578** for the MP3. Exact file bytes differ in both cases.
3. Try **Dog crop with heavy noise** and **Different dog recording**. The frozen policy declines both. For the different dog, set minimum support to zero and watch the wrong candidate be accepted. A review threshold matters when unrelated recordings share a few spectral peaks. Reset the policy to restore the recorded decision.

The browser applies the two controls to saved ranked candidates. The Python replay below rebuilds the SQLite index and fingerprints the audio. Use fresh output paths.

```bash
uv sync --locked
uv run --no-sync python scripts/run_audio_lab.py --check --out .local/audio-example
uv run --no-sync echo-audit match examples/audio-audit/audio/dog-mp3.mp3 \
  --index .local/audio-example/index.sqlite \
  --policy docs/results/stage-3-policy.json --json
```

Open `examples/audio-audit/index.html` directly from a clone to use the example offline. The audio files ship with the example. The full-corpus audit has its own upstream acquisition workflow.

## Follow one vote through the math

Echo downmixes and resamples to 16 kHz. It slides a 512-sample Hann window every 128 samples. The window spans **32 ms**, and the frames advance by **8 ms**. For each frame it takes the magnitude of the real FFT. Bin (k) represents (k × 16{,}000 / 512) Hz. Echo keeps local spectral peaks and pairs each anchor with nearby later peaks.

The dog query and reference both contain one fingerprint made from anchor bin **63**, target bin **5**, and delay bin **5**. Delay bins represent two frames each. The integer key allocates ten bits to each field.

```text
hash = (63 << 20) | (5 << 10) | 5 = 66065413
offset = (reference frame 226 − query frame 149) × 8 ms = +0.616 s
```

A few chance matches can share that fingerprint. What matters is whether many fingerprints agree on the same time shift. The highlighted bin has **959** votes at exactly 77 frames. Counting distinct query fingerprints within one frame on either side gives **1,396 aligned votes**. Each fingerprint contributes at most once to that window. Echo requires enough unique anchors, coverage, support, and a lead over the runner-up. The larger index reports a slightly different vote count because Echo skips hash keys above the index-wide postings limit. [Fingerprint implementation](../../src/echo/fingerprint.py) · [Voting and policy](../../src/echo/matcher.py) · [Landmark audio search paper](https://labrosa.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf)

## What the measured run says

The mini audit has six queries against three references. **Four of five** known overlaps were accepted at their expected reference, **zero** shared files were found by exact SHA-256 comparison, and the one absent-source query was declined. Several queries are transformations of the same dog recording. The larger audit and held-out benchmark provide the broader evidence.

| Voting engine | Warm median per query | Warm p95 per query |
| --- | ---: | ---: |
| Python | 24.0 ms | 164.3 ms |
| Rust | 23.4 ms | 168.0 ms |

The mini run used an Apple M3, a reused SQLite connection, and 54 measured queries per engine after warmup. These timings include decoding, fingerprints, lookup, voting, and the policy decision. They show similar end-to-end times at this scale. On the larger 290-reference profile, the warm median was 429.6 ms in tuned Python and 188.8 ms with Rust. [Mini timing summaries](performance.json) · [Raw timing rows](timings.csv) · [Larger profiling run and its boundaries](../../docs/results/stage-6.md)

In a release audit, use the time offset to review the suspected overlap. Quarantine confirmed source groups, keep uncertain candidates for review, and re-run on the revised split. The larger example walks through that decision and how removing clips changed test-set coverage. [Release case](../../docs/real-world-case.md)

## Sources and redistribution

| Example audio | Source and license |
| --- | --- |
| `catalog-dog.wav` | *DogBARKING.wav* by ahill86, FSD50K eval. [Freesound 207124](https://freesound.org/s/207124/) · [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `catalog-rain.wav` | *Louisiana Rain 1.wav* by uberhuberman, FSD50K eval. [Freesound 21189](https://freesound.org/s/21189/) · [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `catalog-other-dog.wav` | *MABEL 1.aif* by Bobby Beck, FSD50K eval. [Freesound 32318](https://freesound.org/s/32318/) · [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `other-dog.wav` | *Dog Barking* by nick121087, FSD50K eval. [Freesound 274471](https://freesound.org/s/274471/) · [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `esc-dog.wav`, `dog-trim.wav`, `dog-mp3.mp3`, `dog-noisy.wav` | Karol J. Piczak’s ESC-10 dog excerpt from ahill86’s Freesound 207124. The pack includes the original excerpt and edited copies with trimming, MP3 encoding, and seeded −5 dB SNR noise as described in the manifest. [Pinned ESC-50 project and attribution](https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/LICENSE) · [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| `esc-rain.wav` | Karol J. Piczak’s ESC-10 rain excerpt from uberhuberman’s Freesound 21189. [Pinned ESC-50 project and attribution](https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/LICENSE) · [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |

The manifest records SHA-256, uploader, and transformations for every file. The preparation script verifies the original bytes against Echo’s acquisition ledgers and the FSD50K clip metadata. [Audio manifest](dataset.json) · [Pack preparation script](../../scripts/prepare_audio_lab.py) · [Official FSD50K release](https://zenodo.org/records/4060432)
