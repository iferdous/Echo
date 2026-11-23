# Stage 0 — Environment and scaffold

**Outcome.** A clean checkout installs the Python package, runs a generated fixture through a smoke test, and exercises the same path in CI.

## Build

1. Use the existing Echo repository and its `main` branch. Record the baseline commit and current system architecture. Check the Apple Silicon development environment with `uname -m`, `python3 --version`, and `uv --version`.
2. Try native Python 3.12 with NumPy, SciPy, and SoundFile. Verify imports and a WAV round trip before committing to the Python version. Add `pyproject.toml`, the lockfile, and a `src/echo` package. Set up Ruff and pytest as development dependencies. Add PyTorch when Stage 5 starts.
3. Add a minimal CLI entry point with `--help` and `--version`. Add the setup and smoke commands to the README. Ignore downloaded audio, temporary files, local indexes, and run directories. Keep named fixture specs and shareable evidence trackable.
4. Write a small deterministic WAV fixture generator for a changing tone with transients and an unrelated distractor. Generate files under a test temporary directory. Save the fixture seed and expected sample positions in the test.
5. Configure Ubuntu CI to install the lockfile, check formatting and lint, and run fixture tests. Keep the smoke job small and independent of external audio. Record FFmpeg as an optional tool for codec cases in Stage 3.

## Check and capture

- Run the locked install, CLI help, lint, and tests from a fresh environment.
- Verify that libraries loaded under native ARM64 on the development Mac. Record the Python version and any platform-specific setup.
- Verify the CI workflow from its run log. Keep the actual platform support visible in the README.

**Done when** a fresh checkout can install, generate and read the fixture, and pass the documented checks. Record the setup commands and CI run.

[Implementation results](../results/stages-0-1.md) · [Stage index](README.md) · [Next stage](01-audio-foundations-and-datasets.md)
