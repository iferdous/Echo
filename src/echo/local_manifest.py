"""Turn an ordinary directory of audio files into a checksummed manifest."""

from pathlib import Path

from echo.artifacts import new_output_file, sha256_file
from echo.datasets import Asset, write_manifest

AUDIO_SUFFIXES = frozenset(
    (".aif", ".aiff", ".flac", ".mp3", ".oga", ".ogg", ".opus", ".wav")
)


def raise_walk_error(error: OSError) -> None:
    raise error


def manifest_directory(
    root: Path, out: Path, *, dataset: str, revision: str, role: str
) -> int:
    if not dataset.strip() or not revision.strip():
        raise ValueError("dataset and revision must contain a name")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"expected an audio directory: {root}")
    with new_output_file(out) as temporary:
        audio = []
        for folder, _, names in root.walk(on_error=raise_walk_error):
            for name in names:
                path = folder / name
                if path.suffix.lower() in AUDIO_SUFFIXES:
                    if path.is_symlink() or not path.is_file():
                        raise ValueError(
                            f"expected a regular, non-symlink audio file: {path}"
                        )
                    audio.append(path.relative_to(root).as_posix())
        if not audio:
            raise ValueError(f"no supported audio files found in {root}")
        assets = (
            Asset(
                asset_id=f"{dataset}:{relative}",
                dataset=dataset,
                revision=revision,
                path=relative,
                role=role,
                sha256=sha256_file(root / relative),
            )
            for relative in sorted(audio)
        )
        write_manifest(temporary, assets)
    return len(audio)
