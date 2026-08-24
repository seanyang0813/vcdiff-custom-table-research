#!/usr/bin/env python3
"""Freeze the post-failure independent-solver amendment before corpus restart."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = ROOT / "benchmark"
RESULTS = ROOT / "results/generality"
OUTPUT = BENCHMARK / "validity-amendment-v1.json"
HASH = BENCHMARK / "validity-amendment-v1.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    cpsat_outputs = ROOT / "benchmark_artifacts_cpsat"
    if cpsat_outputs.exists() and any(cpsat_outputs.iterdir()):
        raise ValueError("validity amendment must precede non-trigger CP-SAT outputs")
    artifact_lock = BENCHMARK / "artifact-lock-v1.json"
    analysis_spec = BENCHMARK / "analysis-spec-v1.json"
    optimizer = ROOT / "src/vcdiff_opt/optimizer.py"
    adapter = BENCHMARK / "cpsat_adapter.py"
    requirements = BENCHMARK / "cpsat-requirements.txt"
    counterexample = (
        RESULTS
        / "optimizer-counterexamples"
        / "compressed-zstd-tar-gz-v1.5.4-to-v1.5.5-q1.json"
    )
    recovery = RESULTS / "cpsat-recovery-diagnostic-v1.json"
    document = {
        "format": "vcdiff-oracle-validity-amendment-v1",
        "registered_date": "2026-08-23",
        "status": "locked before any non-trigger CP-SAT oracle run",
        "reason": (
            "The frozen SciPy/HiGHS 1.2 presolve path returned a false zero-gap "
            "optimum. An exact corpus requires an independent integer proof."
        ),
        "unchanged_scope": {
            "artifact_lock_sha256": sha256(artifact_lock),
            "analysis_spec_sha256": sha256(analysis_spec),
            "optimizer_path": "src/vcdiff_opt/optimizer.py",
            "optimizer_sha256": sha256(optimizer),
            "pair_membership": "unchanged 48 frozen usable pairs",
            "project_splits": "unchanged",
            "features_models_gates": "unchanged",
            "outcome_selection": "none; replacement protocol applies to every frozen pair",
        },
        "trigger_evidence": {
            "counterexample_path": str(counterexample.relative_to(ROOT)),
            "counterexample_sha256": sha256(counterexample),
            "recovery_diagnostic_path": str(recovery.relative_to(ROOT)),
            "recovery_diagnostic_sha256": sha256(recovery),
            "prior_partial_certificates": (
                "Ten old-HiGHS certificates existed before the stop. They remain "
                "diagnostic and are never reused by the replacement run."
            ),
        },
        "replacement_oracle": {
            "model_generator": (
                "the frozen optimizer builds the same fixed-q and global-q sparse 0/1 model"
            ),
            "adapter_path": "benchmark/cpsat_adapter.py",
            "adapter_sha256": sha256(adapter),
            "requirements_path": "benchmark/cpsat-requirements.txt",
            "requirements_sha256": sha256(requirements),
            "proof_solver": "OR-Tools CP-SAT 9.15.6755",
            "proof_solver_workers": 8,
            "integer_translation": (
                "All [0,1] parse, pattern, q, and varint-state variables are Boolean; "
                "all objective, matrix, and finite-bound coefficients must be exact integers."
            ),
            "proof_acceptance": (
                "CP-SAT status OPTIMAL and integer objective equals integer best bound."
            ),
            "deterministic_construction": (
                "SciPy/HiGHS 1.2 with presolve disabled supplies a hint only. Its rounded "
                "solution is returned only if it is integral, satisfies the original captured "
                "matrix with zero tolerance violation, and has the CP-SAT-proved objective."
            ),
            "hint_evidence_boundary": (
                "The HiGHS hint supplies no lower bound and cannot establish optimality."
            ),
            "attainment_checks": [
                "selected table independent integral DP equals proved instruction objective",
                "emitted full patch bytes equal proved global patch objective",
                "strict Python decoder reconstructs target",
                "unchanged pinned historical xdelta decoder reconstructs target",
            ],
            "failure_rule": (
                "Any non-OPTIMAL status, unequal bound, nonintegral/nonoptimal hint, DP "
                "mismatch, patch mismatch, or decoder failure stops the whole confirmatory run."
            ),
            "output_isolation": "all replacement certificates live under benchmark_artifacts_cpsat",
        },
        "evidence_label": (
            "preregistered frozen corpus with a disclosed post-failure solver-validity amendment"
        ),
        "sources": [
            "https://developers.google.com/optimization/cp/cp_solver",
            "https://github.com/scipy/scipy/issues/18907",
        ],
    }
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    digest = sha256(OUTPUT)
    HASH.write_text(f"{digest}  benchmark/{OUTPUT.name}\n")
    print(f"validity amendment sha256={digest}")


if __name__ == "__main__":
    main()
