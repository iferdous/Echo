"""Regenerate the committed evidence report, README block, charts and ZIP."""

from pathlib import Path

from echo.reporting import publish

if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    print(
        f"Published evidence {publish(repo, check=False, scratch_root=repo / '.local')}"
    )
