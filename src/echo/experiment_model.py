"""Fixed log-mel frontend and deterministic CPU classifier training."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from scipy.fft import rfft
from torch import Tensor, nn

from echo.artifacts import sha256_file
from echo.audio import load_audio
from echo.datasets import Asset
from echo.experiment_data import Crop

SAMPLE_RATE = 16_000
INPUT_SAMPLES = 5 * SAMPLE_RATE
FFT_SIZE = 512
HOP_SIZE = 320
MEL_BANDS = 48
MIN_HZ = 40
MAX_HZ = 7600
DB_FLOOR = -80.0
WEIGHT_DECAY = 0.001
FEATURE_SHAPE = (1, MEL_BANDS, 1 + (INPUT_SAMPLES - FFT_SIZE) // HOP_SIZE)


def mel_filterbank() -> np.ndarray:
    def mel(hz):
        return 2595 * np.log10(1 + hz / 700)

    mel_breaks = np.linspace(mel(MIN_HZ), mel(MAX_HZ), MEL_BANDS + 2)
    breaks = 700 * (10 ** (mel_breaks / 2595) - 1)
    frequencies = np.fft.rfftfreq(FFT_SIZE, d=1 / SAMPLE_RATE)[:, None]
    rising = (frequencies - breaks[:-2]) / (breaks[1:-1] - breaks[:-2])
    falling = (breaks[2:] - frequencies) / (breaks[2:] - breaks[1:-1])
    return np.maximum(0, np.minimum(rising, falling)).astype(np.float32)


MEL_WEIGHTS = mel_filterbank()
WINDOW = np.hanning(FFT_SIZE).astype(np.float32)
WINDOW /= WINDOW.sum()


def log_mel_features(samples: np.ndarray) -> np.ndarray:
    padded = np.zeros(INPUT_SAMPLES, dtype=np.float32)
    length = min(len(samples), INPUT_SAMPLES)
    begin = (INPUT_SAMPLES - length) // 2
    padded[begin : begin + length] = samples[:length]
    frames = np.lib.stride_tricks.sliding_window_view(padded, FFT_SIZE)[::HOP_SIZE]
    power = np.abs(rfft(frames * WINDOW)) ** 2
    decibels = 10 * np.log10(np.maximum(power @ MEL_WEIGHTS, 10 ** (DB_FLOOR / 10)))
    return np.clip((decibels.T - DB_FLOOR) / -DB_FLOOR, 0, 1)[None, :, :]


@dataclass(frozen=True, slots=True)
class AudioSet:
    features: Tensor
    labels: Tensor

    def __len__(self) -> int:
        return len(self.labels)


def features_for(
    entries: list[Asset] | list[Crop], root: Path, classes: dict[str, int]
) -> AudioSet:
    values = np.empty((len(entries), *FEATURE_SHAPE), dtype=np.float32)
    for index, entry in enumerate(entries):
        path = entry.local_path(root) if isinstance(entry, Asset) else root / entry.path
        if sha256_file(path) != entry.sha256:
            raise ValueError(f"{entry.path}: audio differs from the frozen SHA-256")
        samples = load_audio(path, target_rate=SAMPLE_RATE).samples
        values[index] = log_mel_features(samples)
    return AudioSet(
        torch.from_numpy(values).contiguous(memory_format=torch.channels_last),
        torch.tensor([classes[item.label] for item in entries]),
    )


def combine(base: AudioSet, additions: AudioSet) -> AudioSet:
    return AudioSet(
        torch.cat((base.features, additions.features)).contiguous(
            memory_format=torch.channels_last
        ),
        torch.cat((base.labels, additions.labels)),
    )


class MelCNN(nn.Module):
    def __init__(self, classes: int):
        super().__init__()
        self.extract = nn.Sequential(
            nn.Conv2d(1, 12, kernel_size=5, stride=(2, 3), padding=2, bias=False),
            nn.BatchNorm2d(12),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(12, 24, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(24),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(24, 32, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(32),
            nn.ReLU(),
        )
        self.classifier = nn.Linear(32 * (MEL_BANDS // 8) * 2, classes)

    def forward(self, features: Tensor) -> Tensor:
        x = self.extract(features)
        return self.classifier(
            torch.cat((x.mean(dim=-1), x.amax(dim=-1)), dim=1).flatten(1)
        )


def init_model(seed: int, classes: int) -> MelCNN:
    torch.manual_seed(seed)
    return MelCNN(classes).to(memory_format=torch.channels_last)


def model_sha256(model: MelCNN) -> str:
    digest = hashlib.sha256()
    for name, tensor in model.state_dict().items():
        digest.update(name.encode())
        digest.update(tensor.detach().contiguous().cpu().numpy().tobytes())
    return digest.hexdigest()


def seed_orders(seed: int, rows: int, epochs: int) -> np.ndarray:
    rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    return np.asarray([rng.permutation(rows) for _ in range(epochs)], dtype="<i8")


@dataclass(frozen=True, slots=True)
class Fit:
    model: MelCNN
    initial_sha256: str
    updates: int
    epochs: list[dict]
    runtime_seconds: float


@torch.inference_mode()
def predict(model: MelCNN, dataset: AudioSet, batch_size: int) -> Tensor:
    model.eval()
    return torch.cat(
        [model(batch).argmax(dim=1) for batch in dataset.features.split(batch_size)]
    )


def fit_model(
    train: AudioSet,
    validation: AudioSet,
    *,
    seed: int,
    num_classes: int,
    learning_rate: float,
    batch_size: int,
    orders: np.ndarray,
) -> Fit:
    started = perf_counter()
    model = init_model(seed, num_classes)
    initial = model_sha256(model)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate, weight_decay=WEIGHT_DECAY
    )
    cross_entropy = nn.CrossEntropyLoss()
    updates = 0
    log = []
    for number, order in enumerate(torch.from_numpy(orders), start=1):
        model.train()
        train_loss = 0.0
        for batch in order.split(batch_size):
            values = train.features[batch].contiguous(memory_format=torch.channels_last)
            optimizer.zero_grad(set_to_none=True)
            loss = cross_entropy(model(values), train.labels[batch])
            if not torch.isfinite(loss):
                raise ValueError("training produced non-finite loss")
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(batch)
            updates += 1
        predictions = predict(model, validation, batch_size)
        validation_correct = int((predictions == validation.labels).sum())
        log.append(
            {
                "epoch": number,
                "optimizer_updates": updates,
                "mean_training_loss": train_loss / len(train),
                "validation_rows": len(validation),
                "validation_correct": validation_correct,
                "validation_accuracy": validation_correct / len(validation),
            }
        )
    return Fit(model, initial, updates, log, perf_counter() - started)
