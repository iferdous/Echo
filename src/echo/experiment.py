"""Calibrate and run the paired ESC-50 experiment without tuning on test scores."""

import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, stdev
from time import perf_counter

import numpy as np
import scipy
import soundfile
import torch

from echo import experiment_model as model
from echo.artifacts import new_output_directory, sha256_file, write_csv, write_json
from echo.evaluation import run_info
from echo.experiment_data import ARMS, ExperimentDesign, read_experiment_design
from echo.experiment_metrics import group_bootstrap, masks, paired_metrics

CHECKPOINT_RULE = "final_epoch"
CALIBRATION_RULE = "highest_final_validation_accuracy_then_lower_learning_rate"
PREDICTION_COLUMNS = (
    "run_id",
    "seed",
    "row",
    "asset_id",
    "wav_sha256",
    "recording_group",
    "label",
    "directly_exposed",
    "comparison_prediction",
    "exposed_prediction",
    "comparison_correct",
    "exposed_correct",
)
LOG_COLUMNS = (
    "seed",
    "arm",
    "epoch",
    "optimizer_updates",
    "mean_training_loss",
    "validation_rows",
    "validation_correct",
    "validation_accuracy",
)
CLASS_COLUMNS = (
    "seed",
    "label",
    "test_rows",
    "directly_exposed_rows",
    "unexposed_rows",
    "comparison_correct",
    "exposed_correct",
    "delta_accuracy_pp",
    "comparison_wrong_exposed_right",
    "comparison_right_exposed_wrong",
)


def use_cpu(threads: int) -> None:
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)


def environment() -> dict:
    return {
        **run_info(),
        "device": "cpu",
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "soundfile": soundfile.__version__,
        "libsndfile": soundfile.__libsndfile_version__,
    }


def label_indices(design: ExperimentDesign) -> dict[str, int]:
    return {
        label: index
        for index, label in enumerate(
            sorted({a.label for a in design.splits.assets["validation"]})
        )
    }


def training_inputs(design, esc_root, design_root, classes, arms):
    assets = design.splits.assets
    validation = model.features_for(assets["validation"], esc_root, classes)
    base = model.features_for(assets["train_base"], esc_root, classes)
    training = {
        arm: model.combine(
            base, model.features_for(design.crops[arm], design_root, classes)
        )
        for arm in arms
    }
    return validation, training


def frozen_identity(design_root: Path) -> dict:
    return {
        "design_sha256": sha256_file(design_root / "design.json"),
        "experiment_model_sha256": sha256_file(Path(model.__file__)),
        "experiment_runner_sha256": sha256_file(Path(__file__)),
        "dependency_lock_sha256": sha256_file(
            Path(__file__).resolve().parents[2] / "uv.lock"
        ),
        "checkpoint_rule": CHECKPOINT_RULE,
    }


def run_smoke(inventory: Path, esc_root: Path, design_root: Path, out: Path) -> dict:
    design = read_experiment_design(design_root, inventory)
    use_cpu(design.spec.cpu_threads)
    labels = sorted({crop.label for crop in design.crops["comparison"]})[:3]
    classes = {label: index for index, label in enumerate(labels)}

    def sample(items, limit):
        return [
            item
            for label in labels
            for item in [candidate for candidate in items if candidate.label == label][
                :limit
            ]
        ]

    base = model.features_for(
        sample(design.splits.assets["train_base"], 4), esc_root, classes
    )
    additions = model.features_for(
        sample(design.crops["comparison"], 1), design_root, classes
    )
    validation = model.features_for(
        sample(design.splits.assets["validation"], 2), esc_root, classes
    )
    train = model.combine(base, additions)
    seed = design.spec.calibration_seed
    orders = model.seed_orders(seed, len(train), 1)
    kwargs = {
        "seed": seed,
        "num_classes": len(classes),
        "learning_rate": design.spec.learning_rates[0],
        "batch_size": 4,
        "orders": orders,
    }
    first = model.fit_model(train, validation, **kwargs)
    replay = model.fit_model(train, validation, **kwargs)
    equal = (
        first.initial_sha256 == replay.initial_sha256
        and model.model_sha256(first.model) == model.model_sha256(replay.model)
        and torch.equal(
            model.predict(first.model, validation, 4),
            model.predict(replay.model, validation, 4),
        )
    )
    if not equal or first.updates != math.ceil(len(train) / 4):
        raise ValueError("CPU smoke replay diverged")
    result = {
        "schema_version": 1,
        "validation_only": True,
        "deterministic_replay": equal,
        "training_rows": len(train),
        "classes": classes,
        "logs": first.epochs,
        "environment": environment(),
    }
    with new_output_directory(out):
        write_json(out / "smoke.json", result)
    return result


def calibrate(inventory: Path, esc_root: Path, design_root: Path, out: Path) -> dict:
    started = datetime.now(UTC)
    design = read_experiment_design(design_root, inventory)
    spec = design.spec
    use_cpu(spec.cpu_threads)
    classes = label_indices(design)
    validation, training = training_inputs(
        design, esc_root, design_root, classes, ("comparison",)
    )
    train = training["comparison"]
    orders = model.seed_orders(spec.calibration_seed, len(train), spec.epochs)
    trials = []
    with new_output_directory(out):
        for rate in spec.learning_rates:
            fit = model.fit_model(
                train,
                validation,
                seed=spec.calibration_seed,
                num_classes=len(classes),
                learning_rate=rate,
                batch_size=spec.batch_size,
                orders=orders,
            )
            row = {
                "learning_rate": rate,
                "initial_model_sha256": fit.initial_sha256,
                "optimizer_updates": fit.updates,
                "runtime_seconds": fit.runtime_seconds,
                "epochs": fit.epochs,
            }
            trials.append(row)
            print(
                f"Validation learning rate {rate:g} scored {fit.epochs[-1]['validation_accuracy']:.2%}",
                file=sys.stderr,
                flush=True,
            )
        if len({row["initial_model_sha256"] for row in trials}) != 1:
            raise ValueError(
                "calibration trials must start from identical model states"
            )
        best = min(
            trials,
            key=lambda row: (
                -row["epochs"][-1]["validation_accuracy"],
                row["learning_rate"],
            ),
        )
        recipe = {
            "schema_version": 1,
            **frozen_identity(design_root),
            "calibration_rule": CALIBRATION_RULE,
            "selection_split": "group_disjoint_validation",
            "learning_rate": best["learning_rate"],
            "calibration_seed": spec.calibration_seed,
            "training_rows": len(train),
            "validation_rows": len(validation),
            "epochs": spec.epochs,
            "batch_size": spec.batch_size,
            "optimizer_updates": math.ceil(len(train) / spec.batch_size) * spec.epochs,
            "training_order_sha256": hashlib.sha256(orders.tobytes()).hexdigest(),
            "started_utc": started.isoformat(),
            "completed_utc": datetime.now(UTC).isoformat(),
            "trials": trials,
            "environment": environment(),
        }
        write_json(out / "calibration.json", recipe)
    return recipe


def read_recipe(path: Path, design_root: Path, design: ExperimentDesign) -> dict:
    recipe = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        **frozen_identity(design_root),
        "schema_version": 1,
        "calibration_rule": CALIBRATION_RULE,
        "selection_split": "group_disjoint_validation",
        "calibration_seed": design.spec.calibration_seed,
        "training_rows": design.metadata["validation"]["training_rows_per_arm"],
        "validation_rows": len(design.splits.assets["validation"]),
        "epochs": design.spec.epochs,
        "batch_size": design.spec.batch_size,
    }
    if any(recipe.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "calibration differs from the frozen design, training code or lockfile"
        )
    trials = recipe["trials"]
    best = min(
        trials,
        key=lambda row: (
            -row["epochs"][-1]["validation_accuracy"],
            row["learning_rate"],
        ),
    )
    if [row["learning_rate"] for row in trials] != design.spec.learning_rates or recipe[
        "learning_rate"
    ] != best["learning_rate"]:
        raise ValueError(
            "calibration learning rate differs from the validation selection rule"
        )
    return recipe


def class_rows(seed, labels, actual, baseline, exposed, direct):
    for number, label in enumerate(labels):
        selected = actual == number
        row = paired_metrics(actual[selected], baseline[selected], exposed[selected])
        yield {
            "seed": seed,
            "label": label,
            "test_rows": int(selected.sum()),
            "directly_exposed_rows": int((selected & direct).sum()),
            "unexposed_rows": int((selected & ~direct).sum()),
            "comparison_correct": row["comparison"]["correct"],
            "exposed_correct": row["exposed"]["correct"],
            "delta_accuracy_pp": row["delta_accuracy_pp"],
            "comparison_wrong_exposed_right": row["comparison_wrong_exposed_right"],
            "comparison_right_exposed_wrong": row["comparison_right_exposed_wrong"],
        }


def summaries(seed_rows, test, source_groups, deltas, slices):
    output = {}
    for name, selected in slices.items():
        rows = [row["metrics"][name] for row in seed_rows]
        accuracy = [row["delta_accuracy_pp"] for row in rows]
        macro = [row["delta_macro_f1_pp"] for row in rows]
        groups = [
            source_groups[a.asset_id]
            for a, keep in zip(test, selected, strict=True)
            if keep
        ]
        output[name] = {
            "test_rows": int(selected.sum()),
            "test_source_groups": len(set(groups)),
            "comparison_mean_accuracy": mean(
                row["comparison"]["accuracy"] for row in rows
            ),
            "exposed_mean_accuracy": mean(row["exposed"]["accuracy"] for row in rows),
            "comparison_mean_macro_f1": mean(
                row["comparison"]["macro_f1"] for row in rows
            ),
            "exposed_mean_macro_f1": mean(row["exposed"]["macro_f1"] for row in rows),
            "mean_delta_accuracy_pp": mean(accuracy),
            "sample_sd_delta_accuracy_pp": stdev(accuracy),
            "min_delta_accuracy_pp": min(accuracy),
            "max_delta_accuracy_pp": max(accuracy),
            "mean_delta_macro_f1_pp": mean(macro),
            "sample_sd_delta_macro_f1_pp": stdev(macro),
            "paired_test_source_bootstrap": group_bootstrap(
                deltas[:, selected], groups
            ),
        }
    return output


def run_experiment(
    inventory: Path, esc_root: Path, design_root: Path, calibration: Path, out: Path
) -> dict:
    started = datetime.now(UTC)
    timer = perf_counter()
    design = read_experiment_design(design_root, inventory)
    recipe = read_recipe(calibration, design_root, design)
    spec = design.spec
    use_cpu(spec.cpu_threads)
    classes = label_indices(design)
    labels = list(classes)
    source_groups = design.splits.groups
    test = design.splits.assets["test"]
    directly_exposed = {pair.test.asset_id for pair in design.splits.pairs}
    direct = np.array([asset.asset_id in directly_exposed for asset in test])
    slices = masks(direct)
    identity = {
        **frozen_identity(design_root),
        "calibration_sha256": sha256_file(calibration),
        "seeds": spec.paired_seeds,
        "test_manifest_sha256": design.metadata["files"]["test.csv"],
    }
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    with new_output_directory(out):
        validation, training = training_inputs(
            design, esc_root, design_root, classes, ARMS
        )
        size = len(training["comparison"])
        test_inputs = model.features_for(test, esc_root, classes)
        actual = test_inputs.labels.numpy()
        feature_seconds = perf_counter() - timer
        planned_updates = math.ceil(size / spec.batch_size) * spec.epochs
        if size != recipe["training_rows"] or not torch.equal(
            training["comparison"].labels, training["exposed"].labels
        ):
            raise ValueError(
                "training sets must have identical ordered class labels and counts"
            )
        if planned_updates != recipe["optimizer_updates"]:
            raise ValueError("optimizer update budget differs from calibration")
        logs = []
        predictions = []
        by_class = []
        seed_rows = []
        deltas = []
        (out / "models").mkdir()
        for seed in spec.paired_seeds:
            orders = model.seed_orders(seed, size, spec.epochs)
            fits = {
                arm: model.fit_model(
                    training[arm],
                    validation,
                    seed=seed,
                    num_classes=len(classes),
                    learning_rate=recipe["learning_rate"],
                    batch_size=spec.batch_size,
                    orders=orders,
                )
                for arm in ARMS
            }
            if len({fit.initial_sha256 for fit in fits.values()}) != 1 or any(
                fit.updates != planned_updates for fit in fits.values()
            ):
                raise ValueError(
                    f"seed {seed}: paired model initialization or updates diverged"
                )
            predicted = {}
            pair = {
                "seed": seed,
                "training_order_sha256": hashlib.sha256(orders.tobytes()).hexdigest(),
                "initial_model_sha256": fits["comparison"].initial_sha256,
                "arms": {},
            }
            for arm, fit in fits.items():
                predicted[arm] = model.predict(
                    fit.model, test_inputs, spec.batch_size
                ).numpy()
                logs.extend({"seed": seed, "arm": arm, **row} for row in fit.epochs)
                checkpoint = out / "models" / f"{seed}-{arm}.pt"
                torch.save(fit.model.state_dict(), checkpoint)
                pair["arms"][arm] = {
                    "runtime_seconds": fit.runtime_seconds,
                    "optimizer_updates": fit.updates,
                    "test_manifest_sha256": identity["test_manifest_sha256"],
                    "checkpoint": str(checkpoint.relative_to(out)),
                    "checkpoint_sha256": sha256_file(checkpoint),
                    "final_model_state_sha256": model.model_sha256(fit.model),
                    "final_validation_accuracy": fit.epochs[-1]["validation_accuracy"],
                }
            comparison, exposed = (predicted[arm] for arm in ARMS)
            deltas.append((exposed == actual).astype(np.int8) - (comparison == actual))
            pair["metrics"] = {
                name: paired_metrics(
                    actual[selected], comparison[selected], exposed[selected]
                )
                for name, selected in slices.items()
            }
            seed_rows.append(pair)
            by_class.extend(
                class_rows(seed, labels, actual, comparison, exposed, direct)
            )
            for i, asset in enumerate(test):
                predictions.append(
                    {
                        "run_id": run_id,
                        "seed": seed,
                        "row": i,
                        "asset_id": asset.asset_id,
                        "wav_sha256": asset.sha256,
                        "recording_group": source_groups[asset.asset_id],
                        "label": asset.label,
                        "directly_exposed": bool(direct[i]),
                        "comparison_prediction": labels[comparison[i]],
                        "exposed_prediction": labels[exposed[i]],
                        "comparison_correct": bool(comparison[i] == actual[i]),
                        "exposed_correct": bool(exposed[i] == actual[i]),
                    }
                )
            print(f"Seed {seed} finished both arms", file=sys.stderr, flush=True)
        write_csv(out / "training.csv", LOG_COLUMNS, logs)
        write_csv(out / "predictions.csv", PREDICTION_COLUMNS, predictions)
        write_csv(out / "per_class.csv", CLASS_COLUMNS, by_class)
        report = {
            "schema_version": 1,
            **identity,
            "run_id": run_id,
            "started_utc": started.isoformat(),
            "completed_utc": datetime.now(UTC).isoformat(),
            "wall_seconds": perf_counter() - timer,
            "input_and_feature_seconds": feature_seconds,
            "learning_rate": recipe["learning_rate"],
            "batch_size": spec.batch_size,
            "epochs": spec.epochs,
            "optimizer_updates_per_arm": planned_updates,
            "train_examples_per_arm": size,
            "label_order": labels,
            "dataset_revision": design.metadata["dataset_revision"],
            "split_validation": design.metadata["validation"],
            "per_seed": seed_rows,
            "slices": summaries(
                seed_rows, test, source_groups, np.array(deltas), slices
            ),
            "files": {
                file.name: sha256_file(file) for file in sorted(out.glob("*.csv"))
            },
            "environment": environment(),
        }
        write_json(out / "summary.json", report)
    return report
