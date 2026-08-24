#!/usr/bin/env python3
"""Run the preregistered distribution, predictor, and generality-gate analyses."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    mean_absolute_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor


ROOT = Path(__file__).resolve().parent.parent
FEATURES = ROOT / "results/generality/features-v1.jsonl"
FEATURE_MANIFEST = ROOT / "results/generality/feature-manifest-v1.json"
OUTPUT = ROOT / "results/generality"
DISTANCE_ORDINAL = {"near": 1, "medium": 2, "far": 3}


def finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def spearman(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    if len(actual) < 2 or np.all(actual == actual[0]) or np.all(predicted == predicted[0]):
        return None
    return finite(spearmanr(actual, predicted).statistic)


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "spearman": spearman(actual, predicted),
    }


def classification_metrics(actual: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    two_classes = len(set(int(value) for value in actual)) == 2
    return {
        "roc_auc": float(roc_auc_score(actual, probability)) if two_classes else None,
        "average_precision": float(average_precision_score(actual, probability)) if two_classes else None,
        "brier": float(brier_score_loss(actual, probability)),
        "positive_count": int(actual.sum()),
        "count": len(actual),
    }


def threshold_metrics(actual: np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = probability >= threshold
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(actual, predicted, zero_division=0)),
        "recall": float(recall_score(actual, predicted, zero_division=0)),
        "predicted_positive_count": int(predicted.sum()),
        "positive_count": int(actual.sum()),
        "count": len(actual),
    }


def feature_columns(rows: list[dict[str, Any]]) -> list[str]:
    exact = {
        "source_bytes",
        "target_bytes",
        "stock_patch_bytes",
        "stock_patch_fraction_of_target",
        "stock_instruction_bytes",
        "stock_data_bytes",
        "stock_address_bytes",
        "r_i",
        "logical_instruction_count",
        "instructions_per_output_mib",
        "adjacent_pair_occurrences",
        "source_copy_count",
        "source_copy_fraction_of_copy",
    }
    prefixes = (
        "type_",
        "copy_mode_",
        "size_bin_",
        "instruction_size_",
        "single_",
        "pair_",
    )
    columns = [
        key
        for key, value in rows[0].items()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (key in exact or key.startswith(prefixes))
        and not key.startswith("oracle_")
        and not key.startswith("solver_")
    ]
    return sorted(columns)


def matrix(rows: list[dict[str, Any]], columns: list[str]) -> np.ndarray:
    return np.asarray([[float(row[column]) for column in columns] for row in rows])


def regression_candidates() -> list[tuple[str, list[str] | None, Callable[[], Any]]]:
    candidates: list[tuple[str, list[str] | None, Callable[[], Any]]] = [
        ("instruction_fraction_linear", ["r_i"], lambda: LinearRegression())
    ]
    for alpha in (0.01, 0.1, 1.0, 10.0, 100.0):
        candidates.append((f"ridge_alpha_{alpha:g}", None, lambda alpha=alpha: Ridge(alpha=alpha)))
    candidates.append(
        (
            "tree_depth_3",
            None,
            lambda: DecisionTreeRegressor(max_depth=3, min_samples_leaf=2, random_state=0),
        )
    )
    return candidates


def classification_candidates() -> list[tuple[str, list[str] | None, Callable[[], Any]]]:
    candidates: list[tuple[str, list[str] | None, Callable[[], Any]]] = [
        (
            "instruction_fraction_logistic",
            ["r_i"],
            lambda: LogisticRegression(C=1.0, max_iter=10000, random_state=0),
        )
    ]
    for c_value in (0.01, 0.1, 1.0, 10.0, 100.0):
        candidates.append(
            (
                f"ridge_logistic_C_{c_value:g}",
                None,
                lambda c_value=c_value: LogisticRegression(
                    C=c_value, max_iter=10000, random_state=0
                ),
            )
        )
    candidates.append(
        (
            "tree_depth_3",
            None,
            lambda: DecisionTreeClassifier(max_depth=3, min_samples_leaf=2, random_state=0),
        )
    )
    return candidates


def pipeline(estimator: Any) -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", estimator),
        ]
    )


def class_probability(model: Pipeline, values: np.ndarray) -> np.ndarray:
    probabilities = model.predict_proba(values)
    classes = list(model.named_steps["model"].classes_)
    if 1 not in classes:
        return np.zeros(len(values), dtype=float)
    return probabilities[:, classes.index(1)]


def grouped_oof(
    rows: list[dict[str, Any]],
    columns: list[str],
    candidates: list[tuple[str, list[str] | None, Callable[[], Any]]],
    *,
    classification: bool,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    groups = np.asarray([row["project"] for row in rows])
    target = np.asarray(
        [bool(row["oracle_saves_1pct"]) for row in rows]
        if classification
        else [float(row["oracle_savings_fraction"]) for row in rows],
        dtype=int if classification else float,
    )
    splitter = LeaveOneGroupOut()
    reports: list[dict[str, Any]] = []
    predictions: dict[str, np.ndarray] = {}
    for order, (name, selected_columns, factory) in enumerate(candidates):
        used_columns = columns if selected_columns is None else selected_columns
        values = matrix(rows, used_columns)
        predicted = np.zeros(len(rows), dtype=float)
        valid = np.zeros(len(rows), dtype=bool)
        fold_failures: list[str] = []
        for training, held_out in splitter.split(values, target, groups):
            if classification and len(np.unique(target[training])) < 2:
                fold_failures.append(str(groups[held_out][0]))
                continue
            model = pipeline(factory())
            model.fit(values[training], target[training])
            predicted[held_out] = (
                class_probability(model, values[held_out])
                if classification
                else model.predict(values[held_out])
            )
            valid[held_out] = True
        if not valid.all():
            metrics: dict[str, Any] = {
                "roc_auc": None,
                "average_precision": None,
                "brier": None,
            } if classification else {"mae": None, "spearman": None}
        else:
            metrics = (
                classification_metrics(target, predicted)
                if classification
                else regression_metrics(target, predicted)
            )
        report = {
            "name": name,
            "order": order,
            "feature_count": len(used_columns),
            "features": used_columns,
            "fold_failures": fold_failures,
            **metrics,
        }
        reports.append(report)
        predictions[name] = predicted
    return reports, predictions


def choose_regressor(reports: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [report for report in reports if report["mae"] is not None]
    if not eligible:
        return reports[0]
    return min(
        eligible,
        key=lambda report: (
            report["mae"],
            -(report["spearman"] if report["spearman"] is not None else -math.inf),
            report["order"],
        ),
    )


def choose_classifier(reports: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [report for report in reports if report["roc_auc"] is not None]
    if not eligible:
        return reports[0]
    return max(
        eligible,
        key=lambda report: (
            report["roc_auc"],
            report["average_precision"],
            -report["order"],
        ),
    )


def candidate_by_name(candidates: list[tuple[str, Any, Any]], name: str) -> tuple[str, Any, Any]:
    return next(candidate for candidate in candidates if candidate[0] == name)


def fit_predict(
    training_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    all_columns: list[str],
    candidate: tuple[str, list[str] | None, Callable[[], Any]],
    *,
    classification: bool,
) -> tuple[np.ndarray, Pipeline]:
    _, selected_columns, factory = candidate
    columns = all_columns if selected_columns is None else selected_columns
    training_values = matrix(training_rows, columns)
    prediction_values = matrix(prediction_rows, columns)
    target = np.asarray(
        [bool(row["oracle_saves_1pct"]) for row in training_rows]
        if classification
        else [float(row["oracle_savings_fraction"]) for row in training_rows],
        dtype=int if classification else float,
    )
    model = pipeline(factory())
    model.fit(training_values, target)
    predicted = (
        class_probability(model, prediction_values)
        if classification
        else model.predict(prediction_values)
    )
    return predicted, model


def tune_threshold(actual: np.ndarray, probability: np.ndarray) -> dict[str, Any] | None:
    if len(set(int(value) for value in actual)) < 2:
        return None
    candidates = sorted(set(float(value) for value in probability))
    candidates.extend([0.0, float(np.nextafter(max(candidates), math.inf))])
    evaluations = [threshold_metrics(actual, probability, value) for value in set(candidates)]
    eligible = [value for value in evaluations if value["precision"] >= 0.70]
    if not eligible:
        return None
    return max(eligible, key=lambda value: (value["recall"], value["precision"], value["threshold"]))


def summarize_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([row["oracle_savings_fraction"] for row in rows], dtype=float)
    projects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        projects[row["project"]].append(row)
        categories[row["category"]].append(row)

    def group_summary(group_rows: list[dict[str, Any]]) -> dict[str, Any]:
        group_values = np.asarray([row["oracle_savings_fraction"] for row in group_rows])
        return {
            "count": len(group_rows),
            "mean": float(group_values.mean()),
            "median": float(np.median(group_values)),
            "min": float(group_values.min()),
            "max": float(group_values.max()),
            "saves_0_3pct_count": int(sum(value >= 0.003 for value in group_values)),
            "saves_1pct_count": int(sum(value >= 0.01 for value in group_values)),
            "saves_2pct_count": int(sum(value >= 0.02 for value in group_values)),
        }

    return {
        "count": len(rows),
        "mean": float(values.mean()),
        "minimum": float(values.min()),
        "q25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "q75": float(np.quantile(values, 0.75)),
        "maximum": float(values.max()),
        "thresholds": {
            str(threshold): {
                "count": int(sum(values >= threshold)),
                "fraction": float(np.mean(values >= threshold)),
            }
            for threshold in (0.003, 0.01, 0.02)
        },
        "project_balanced_mean": float(np.mean([
            np.mean([row["oracle_savings_fraction"] for row in group])
            for group in projects.values()
        ])),
        "category_balanced_mean": float(np.mean([
            np.mean([row["oracle_savings_fraction"] for row in group])
            for group in categories.values()
        ])),
        "by_project": {name: group_summary(group) for name, group in sorted(projects.items())},
        "by_category": {name: group_summary(group) for name, group in sorted(categories.items())},
    }


def change_distance(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["project"], row["category"])].append(row)
    result: list[dict[str, Any]] = []
    for (project, category), group in sorted(groups.items()):
        distances = np.asarray([DISTANCE_ORDINAL[row["distance"]] for row in group])
        savings = np.asarray([row["oracle_savings_fraction"] for row in group])
        result.append(
            {
                "project": project,
                "category": category,
                "count": len(group),
                "spearman": spearman(distances, savings),
                "pairs": [
                    {
                        "pair_id": row["pair_id"],
                        "distance": row["distance"],
                        "savings_fraction": row["oracle_savings_fraction"],
                    }
                    for row in sorted(group, key=lambda row: DISTANCE_ORDINAL[row["distance"]])
                ],
            }
        )
    return result


def write_markdown(result: dict[str, Any]) -> None:
    distribution = result["distribution"]
    gate = result["generality_gate"]
    predictor = result["predictive_analysis"]
    lines = [
        "# Exact VCDIFF restricted-table generality study",
        "",
        "## Distribution",
        "",
        f"All {distribution['count']} frozen usable pairs completed. Median exact saving: "
        f"{100*distribution['median']:.3f}%; mean: {100*distribution['mean']:.3f}%; "
        f"interquartile range: {100*distribution['q25']:.3f}% to {100*distribution['q75']:.3f}%.",
        "",
        "| Threshold | Pairs | Fraction |",
        "|---:|---:|---:|",
    ]
    for threshold in (0.003, 0.01, 0.02):
        value = distribution["thresholds"][str(threshold)]
        lines.append(f"| {100*threshold:.1f}% | {value['count']} | {100*value['fraction']:.1f}% |")
    lines.extend(
        [
            "",
            "## Categories",
            "",
            "| Category | Pairs | Mean | Median | >=1% |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, value in distribution["by_category"].items():
        lines.append(
            f"| {name} | {value['count']} | {100*value['mean']:.3f}% | "
            f"{100*value['median']:.3f}% | {value['saves_1pct_count']} |"
        )
    selected = predictor["selected_classifier"]
    validation = predictor["validation_classifier"]
    lines.extend(
        [
            "",
            "## Predictor and gate",
            "",
            f"Selected classifier: `{selected['name']}`; grouped training ROC AUC: "
            f"{selected['roc_auc'] if selected['roc_auc'] is not None else 'undefined'}.",
            "",
            f"Validation precision/recall: {validation.get('precision', 0):.3f}/"
            f"{validation.get('recall', 0):.3f}.",
            "",
            f"Generality gate: **{'PASS' if gate['passes'] else 'FAIL'}**.",
            "",
        ]
    )
    if gate["passes"]:
        lines.append("The preregistered conditional table-bank experiment is authorized.")
    else:
        lines.append("Per preregistration, no table bank or deployment prototype is built.")
    lines.extend(
        [
            "",
            "Every saving is an exact zero-gap optimum only within the frozen one-window, "
            "fixed-trace, q=0..93 canonical-prefix table family. It is not an optimum over "
            "all VCDIFF parses or all legal code tables.",
            "",
            "The corpus uses the frozen optimizer only as a sparse-model generator. "
            "Integer optimality is independently proved by the locked OR-Tools CP-SAT "
            "amendment after the originally preregistered HiGHS path was invalidated.",
            "",
        ]
    )
    (OUTPUT / "report-v1.md").write_text("\n".join(lines))


def main() -> None:
    manifest = json.loads(FEATURE_MANIFEST.read_text())
    if manifest.get("oracle_validity") is False:
        raise ValueError("oracle validity failed; confirmatory analysis is forbidden")
    if not manifest["complete"] or not manifest.get("confirmatory_use", False):
        raise ValueError("feature manifest is partial")
    if manifest.get("certificate_format") != "vcdiff-custom-table-certificate-v3-cpsat":
        raise ValueError("analysis requires amended CP-SAT certificates")
    rows = [json.loads(line) for line in FEATURES.read_text().splitlines() if line.strip()]
    if len(rows) != 48:
        raise ValueError(f"expected 48 feature rows, got {len(rows)}")
    columns = feature_columns(rows)
    training = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "validation"]
    test = [row for row in rows if row["split"] == "test"]

    regressors = regression_candidates()
    classifiers = classification_candidates()
    regression_reports, regression_oof = grouped_oof(
        training, columns, regressors, classification=False
    )
    classification_reports, classification_oof = grouped_oof(
        training, columns, classifiers, classification=True
    )
    selected_regression = choose_regressor(regression_reports)
    selected_classification = choose_classifier(classification_reports)
    regression_candidate = candidate_by_name(regressors, selected_regression["name"])
    classification_candidate = candidate_by_name(classifiers, selected_classification["name"])

    validation_regression, regression_model = fit_predict(
        training, validation, columns, regression_candidate, classification=False
    )
    validation_probability, classification_model = fit_predict(
        training, validation, columns, classification_candidate, classification=True
    )
    validation_savings = np.asarray([row["oracle_savings_fraction"] for row in validation])
    validation_label = np.asarray([row["oracle_saves_1pct"] for row in validation], dtype=int)
    threshold = tune_threshold(validation_label, validation_probability)
    validation_threshold_metrics = (
        threshold
        if threshold is not None
        else {
            "threshold": None,
            "precision": 0.0,
            "recall": 0.0,
            "predicted_positive_count": 0,
            "positive_count": int(validation_label.sum()),
            "count": len(validation),
        }
    )

    # Models and threshold are now fixed. The held-out test projects are predicted once.
    test_regression, _ = fit_predict(
        training, test, columns, regression_candidate, classification=False
    )
    test_probability, _ = fit_predict(
        training, test, columns, classification_candidate, classification=True
    )
    test_savings = np.asarray([row["oracle_savings_fraction"] for row in test])
    test_label = np.asarray([row["oracle_saves_1pct"] for row in test], dtype=int)
    test_threshold_metrics = (
        threshold_metrics(test_label, test_probability, float(threshold["threshold"]))
        if threshold is not None
        else {
            "threshold": None,
            "precision": 0.0,
            "recall": 0.0,
            "predicted_positive_count": 0,
            "positive_count": int(test_label.sum()),
            "count": len(test),
        }
    )

    project_hits = sorted(
        {
            row["project"] for row in rows if row["oracle_savings_fraction"] >= 0.01
        }
    )
    non_source_hits = [
        row["pair_id"]
        for row in rows
        if row["category"] in {"compiled", "structured"}
        and row["oracle_savings_fraction"] >= 0.01
    ]
    auc = selected_classification["roc_auc"]
    components = {
        "project_repetition": {
            "passes": len(project_hits) >= 3,
            "count": len(project_hits),
            "projects": project_hits,
            "required": 3,
        },
        "non_source_repetition": {
            "passes": len(non_source_hits) >= 2,
            "count": len(non_source_hits),
            "pair_ids": non_source_hits,
            "required": 2,
        },
        "grouped_classifier": {
            "passes": auc is not None and auc >= 0.75,
            "roc_auc": auc,
            "required": 0.75,
        },
        "validation_selector": {
            "passes": (
                threshold is not None
                and validation_threshold_metrics["precision"] >= 0.70
                and validation_threshold_metrics["recall"] >= 0.40
            ),
            **validation_threshold_metrics,
            "required_precision": 0.70,
            "required_recall": 0.40,
        },
    }
    gate = {
        "passes": all(value["passes"] for value in components.values()),
        "all_required": True,
        "components": components,
        "failure_action": "Do not build a deployment prototype; retain the oracle benchmark as the research artifact.",
    }

    predictions: list[dict[str, Any]] = []
    train_regression_prediction = regression_oof[selected_regression["name"]]
    train_class_probability = classification_oof[selected_classification["name"]]
    prediction_arrays = {
        "train": (training, train_regression_prediction, train_class_probability),
        "validation": (validation, validation_regression, validation_probability),
        "test": (test, test_regression, test_probability),
    }
    chosen_threshold = None if threshold is None else float(threshold["threshold"])
    for split, (split_rows, regression_prediction, class_probability_values) in prediction_arrays.items():
        for row, reg_value, probability in zip(
            split_rows, regression_prediction, class_probability_values, strict=True
        ):
            predictions.append(
                {
                    "pair_id": row["pair_id"],
                    "project": row["project"],
                    "split": split,
                    "actual_savings_fraction": row["oracle_savings_fraction"],
                    "actual_favorable": row["oracle_saves_1pct"],
                    "predicted_savings_fraction": float(reg_value),
                    "favorable_probability": float(probability),
                    "selected_favorable": False if chosen_threshold is None else probability >= chosen_threshold,
                }
            )
    with (OUTPUT / "predictions-v1.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)

    result = {
        "format": "vcdiff-generality-analysis-v1",
        "evidence_label": (
            "preregistered frozen corpus with a disclosed post-failure "
            "solver-validity amendment"
        ),
        "validity_amendment_sha256": manifest["validity_amendment_sha256"],
        "distribution": summarize_distribution(rows),
        "change_distance": change_distance(rows),
        "predictor_columns": columns,
        "predictive_analysis": {
            "regression_candidates": regression_reports,
            "classification_candidates": classification_reports,
            "selected_regressor": selected_regression,
            "selected_classifier": selected_classification,
            "validation_regression": regression_metrics(validation_savings, validation_regression),
            "validation_classifier_probability": classification_metrics(validation_label, validation_probability),
            "validation_classifier": validation_threshold_metrics,
            "test_regression": regression_metrics(test_savings, test_regression),
            "test_classifier_probability": classification_metrics(test_label, test_probability),
            "test_classifier": test_threshold_metrics,
        },
        "generality_gate": gate,
    }
    analysis_path = OUTPUT / "analysis-v1.json"
    gate_path = OUTPUT / "gate-decision-v1.json"
    analysis_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    gate_path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n")
    write_markdown(result)
    print(
        f"analysis complete: median={100*result['distribution']['median']:.3f}% "
        f"gate={'PASS' if gate['passes'] else 'FAIL'}"
    )


if __name__ == "__main__":
    main()
