#!/usr/bin/env python3
"""Generate the exact analysis specification before confirmatory tracing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "benchmark/analysis-spec-v1.json"
HASH = ROOT / "benchmark/analysis-spec-v1.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    artifact_lock = ROOT / "benchmark/artifact-lock-v1.json"
    preregistration = ROOT / "benchmark/preregistration-v1.json"
    optimizer = ROOT / "src/vcdiff_opt/optimizer.py"
    if (ROOT / "benchmark_artifacts").exists() and any(
        (ROOT / "benchmark_artifacts").iterdir()
    ):
        raise ValueError("analysis specification must be frozen before tracing")
    document = {
        "format": "vcdiff-generality-analysis-spec-v1",
        "frozen_date": "2026-08-23",
        "outcome_state": "frozen before any confirmatory VCDIFF trace",
        "locks": {
            "artifact_lock_sha256": sha256(artifact_lock),
            "preregistration_sha256": sha256(preregistration),
            "optimizer_sha256": sha256(optimizer),
        },
        "oracle_run": {
            "diagnostic_max_slots": 1,
            "global_max_slots": 93,
            "one_target_window": True,
            "required_solver_gap": 0.0,
            "decoder": "unchanged historical xdelta3 custom-table decoder",
        },
        "feature_definitions": {
            "stock_only_rule": (
                "Predictor columns are computed from artifact sizes and the stock "
                "xdelta3 fixed logical trace. Oracle/table fields are labels only."
            ),
            "instruction_signature": "TYPE:SIZE:MODE, with MODE=0 for ADD and RUN",
            "pair_signature": "ordered adjacent instruction signatures within one window",
            "instruction_size_bins": [
                "1", "2", "3", "4", "5-8", "9-16", "17-32", "33-64",
                "65-127", "128-255", "256+"
            ],
            "quantiles": [0.0, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0],
            "top_k": [1, 4, 8, 16, 32, 64, 93],
            "top_k_ties": "descending frequency, then lexicographic signature",
            "top_pair_coverage": (
                "For the k most frequent pair signatures, dynamic programming chooses "
                "a maximum-cardinality nonoverlapping set of their occurrences; divide "
                "the number of covered logical instructions by instruction count."
            ),
            "entropy": "base-2 Shannon entropy of empirical signature frequencies",
            "normalized_entropy": "entropy/log2(number of positive-frequency signatures), or zero for <=1 signature",
            "herfindahl": "sum of squared empirical signature probabilities",
            "top_k_mass": "mass of the k most frequent signatures",
            "r_i": "stock instruction-section bytes / stock patch bytes",
            "instruction_density": "logical instruction count / target output MiB",
            "oracle_saving_fraction": "(stock patch bytes - exact oracle patch bytes) / stock patch bytes",
            "table_transmission_cost": "oracle file-header bytes - default file-header bytes",
        },
        "distribution_analysis": {
            "thresholds": [0.003, 0.01, 0.02],
            "pair_summary": "median, quartiles, mean, min, max, and threshold fractions",
            "balanced_means": (
                "project-balanced mean averages project means equally; category-balanced "
                "mean averages category means equally"
            ),
            "change_distance": (
                "within each project/category baseline group, report near/medium/far "
                "values and Spearman correlation of ordinal distance 1/2/3 with savings"
            ),
        },
        "predictive_protocol": {
            "favorable_label": "oracle saving fraction >= 0.01",
            "training_groups": ["curl", "git", "linux", "redis", "tzdb", "zstd"],
            "validation_groups": ["llvm", "unicode"],
            "test_groups": ["open-vcdiff", "sqlite", "xdelta"],
            "standardization": "fit median imputation and standardization inside each training fold",
            "training_cv": "LeaveOneGroupOut by project on training projects",
            "regressors": {
                "instruction_fraction_linear": "ordinary least squares on r_i only",
                "ridge": {"alphas": [0.01, 0.1, 1.0, 10.0, 100.0]},
                "tree": {"max_depth": 3, "min_samples_leaf": 2, "random_state": 0},
            },
            "classifiers": {
                "instruction_fraction_logistic": {"C": 1.0, "max_iter": 10000},
                "ridge_logistic": {"C_values": [0.01, 0.1, 1.0, 10.0, 100.0], "max_iter": 10000},
                "tree": {"max_depth": 3, "min_samples_leaf": 2, "random_state": 0},
            },
            "model_selection": (
                "Regression minimizes grouped-CV MAE, tie-broken by higher Spearman then "
                "fixed listed order. Classification maximizes grouped out-of-fold ROC AUC, "
                "tie-broken by average precision then fixed listed order."
            ),
            "validation_threshold": (
                "Among unique predicted probabilities plus endpoints, choose the threshold "
                "with precision >=0.70 that maximizes recall, then precision, then threshold."
            ),
            "test_rule": "After model and threshold are fixed on train/validation, evaluate test projects once.",
        },
        "generality_gate": {
            "all_required": {
                "project_repetition": "at least 3 confirmatory projects have >=1 pair saving >=1%",
                "non_source_repetition": "at least 2 compiled or structured pairs save >=1%",
                "grouped_classifier": "selected training grouped out-of-fold ROC AUC >=0.75",
                "validation_selector": "validation precision >=0.70 and recall >=0.40",
            },
            "undefined_metric_rule": "an undefined required metric fails its gate component",
        },
        "conditional_table_bank": {
            "run_only_if_all_generality_gate_components_pass": True,
            "candidate_tables": "unique nondefault exact-oracle tables from training pairs only",
            "bank_sizes": [1, 2, 4, 8],
            "construction": (
                "deterministic forward greedy selection maximizing aggregate training bytes "
                "saved versus stock under best-of-bank plus stock fallback; table SHA-256 "
                "breaks ties"
            ),
            "validation_choice": (
                "choose the smallest bank reaching aggregate validation oracle capture >=0.70; "
                "if none does, choose maximum validation capture, then smaller bank"
            ),
            "test_metric": "aggregate test bank savings / aggregate positive test oracle savings",
            "monotonic_fallback": "for every pair emit the smallest of stock and every bank-table encoding",
            "deployment_prototype": "only after the table-bank test is complete and the generality gate passed",
        },
    }
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    digest = sha256(OUTPUT)
    HASH.write_text(f"{digest}  benchmark/{OUTPUT.name}\n")
    print(f"analysis specification sha256={digest}")


if __name__ == "__main__":
    main()
