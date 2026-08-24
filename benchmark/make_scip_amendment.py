#!/usr/bin/env python3
"""Freeze the exact-SCIP protocol amendment before new corpus outcomes."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "benchmark/scip-validity-amendment-v2.json"
HASH_OUTPUT = ROOT / "benchmark/scip-validity-amendment-v2.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked(path: str) -> dict[str, str]:
    value = ROOT / path
    if not value.is_file():
        raise FileNotFoundError(value)
    return {"path": path, "sha256": sha256(value)}


def main() -> None:
    trigger = ROOT / "results/generality/scip-exact-recovery-diagnostic-v1.json"
    diagnostic = json.loads(trigger.read_text())
    fixed = diagnostic["fixed_q1_recovery"]
    global_result = diagnostic["global_recovery"]
    if not (
        fixed["instruction_primal"]
        == fixed["instruction_dual"]
        == fixed["independent_dp"]
        == 8254
    ):
        raise AssertionError("exact-SCIP trigger result drift")
    if not (
        global_result["patch_primal"]
        == global_result["patch_dual"]
        == global_result["optimal_patch_bytes"]
        == 2_227_631
    ):
        raise AssertionError("exact-SCIP global trigger result drift")
    if global_result["historical_decoder"]["returncode"] != 0:
        raise AssertionError("historical decoder did not accept trigger patch")

    environment = ROOT / "benchmark_work/scip-conda"
    libraries = {
        name: sha256(environment / "lib" / name)
        for name in ("libscip.so.10.0.2", "libgmp.so.10.5.0", "libmpfr.so.6.2.2")
    }
    amendment = {
        "format": "vcdiff-exact-scip-validity-amendment-v2",
        "registered_date": str(date.today()),
        "status": "locked before any previously unsolved corpus outcome was run with exact SCIP",
        "reason": (
            "The locked CP-SAT amendment is exact but exceeded practical host memory "
            "on larger frozen traces. Exact SCIP preserves exact proof semantics with "
            "a lower-memory formulation."
        ),
        "evidence_label": (
            "preregistered frozen corpus with disclosed post-failure exact-SCIP "
            "solver amendment"
        ),
        "unchanged_scope": {
            "pair_membership": "unchanged 48 frozen usable pairs / 67 artifacts",
            "outcome_selection": "none",
            "analysis_and_decision_gates": "unchanged",
            "optimizer": locked("src/vcdiff_opt/optimizer.py"),
            "artifact_lock": locked("benchmark/artifact-lock-v1.json"),
            "analysis_spec": locked("benchmark/analysis-spec-v1.json"),
            "prior_amendment": locked("benchmark/validity-amendment-v1.json"),
        },
        "proof_backend": {
            "adapter": locked("benchmark/scip_exact_adapter.py"),
            "study_runner": locked("benchmark/run_scip_study.py"),
            "corpus_runner": locked("benchmark/run_scip_corpus.py"),
            "model": (
                "same frozen sparse model, with every intended [0,1] parse, pattern, "
                "slot, and varint-state variable explicitly binary"
            ),
            "solver": "SCIP 10.0.2 through PySCIPOpt 6.2.1",
            "exact_mode": True,
            "environment_lock": locked("benchmark/scip-environment-explicit-v1.txt"),
            "python_sha256": sha256(environment / "bin/python"),
            "library_sha256": libraries,
            "settings": {
                "parallel/maxnthreads": 1,
                "lp/threads": 1,
                "randomization/randomseedshift": 0,
                "randomization/permutationseed": 0,
                "randomization/lpseed": 0,
                "randomization/permuteconss": False,
                "randomization/permutevars": False,
                "limits/time_seconds_per_model": 7200,
                "limits/memory_mb": 6000,
            },
            "acceptance": (
                "SCIP exact mode status optimal, equal integral primal and dual, "
                "independent DP attainment, emitted-byte equality, and successful "
                "strict-Python plus unchanged-historical-xdelta decode"
            ),
            "failure_accounting": (
                "Every timeout, memory limit, process failure, or unsolved status is "
                "retained in the corpus state and never used as an exact oracle label."
            ),
            "candidate_hint": (
                "SciPy/HiGHS with presolve disabled supplies only a validated feasible "
                "construction and no proof bound."
            ),
        },
        "activation_strengthening": {
            "added_rows": "x_occurrence <= y_pattern",
            "proof": (
                "The frozen row is sum_i x_i <= M*y with 0<=x_i<=1 and binary y. "
                "For y=0, nonnegativity forces every x_i=0. For y=1, every added "
                "row is the existing x_i<=1 bound. Thus the integer feasible set is "
                "unchanged; only fractional relaxations are tightened."
            ),
            "executable_test": "tests/test_core.py::test_activation_links_preserve_binary_selection_feasible_set",
        },
        "pre_freeze_trigger": locked(
            "results/generality/scip-exact-recovery-diagnostic-v1.json"
        ),
        "required_revalidation_before_inference": [
            "compressed-zstd-tar-gz-v1.5.4-to-v1.5.5",
            "source-linux-v6.12-to-v6.13",
            "source-linux-v6.12-to-v6.14",
            "source-linux-v6.12-to-v6.15",
            "source-git-v2.48.0-to-v2.48.1",
            "source-git-v2.48.0-to-v2.49.0",
        ],
        "host_record": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "evidence_boundary": "operational record, not a portability guarantee",
        },
    }
    OUTPUT.write_text(json.dumps(amendment, indent=2, sort_keys=True) + "\n")
    HASH_OUTPUT.write_text(
        f"{sha256(OUTPUT)}  {OUTPUT.relative_to(ROOT)}\n"
    )
    print(OUTPUT)
    print(HASH_OUTPUT)


if __name__ == "__main__":
    main()
