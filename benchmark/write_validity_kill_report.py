#!/usr/bin/env python3
"""Write the preregistered stop result after an oracle-validity failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = ROOT / "benchmark"
RESULTS = ROOT / "results/generality"
COUNTEREXAMPLE = (
    RESULTS
    / "optimizer-counterexamples/compressed-zstd-tar-gz-v1.5.4-to-v1.5.5-q1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    preregistration = json.loads((BENCHMARK / "preregistration-v1.json").read_text())
    artifact_lock_path = BENCHMARK / "artifact-lock-v1.json"
    artifact_lock = json.loads(artifact_lock_path.read_text())
    analysis_spec_path = BENCHMARK / "analysis-spec-v1.json"
    counterexample = json.loads(COUNTEREXAMPLE.read_text())
    certificates = sorted(
        path.parent.name
        for path in (ROOT / "benchmark_artifacts").glob("*/certificate.json")
    )
    if counterexample["captured_milp_feasible_vector"]["maximum_constraint_violation"] != 0:
        raise ValueError("counterexample no longer has a feasible captured-model vector")
    if not (
        counterexample["independent_dp_instruction_bytes"]
        < counterexample["milp_instruction_dual"]
    ):
        raise ValueError("counterexample no longer refutes the claimed lower bound")
    optimizer = ROOT / artifact_lock["optimizer"]["optimizer_path"]
    if sha256(optimizer) != artifact_lock["optimizer"]["optimizer_sha256"]:
        raise ValueError("frozen optimizer was modified")

    decision = {
        "format": "vcdiff-generality-validity-stop-v1",
        "status": "STOP",
        "reason": "frozen optimizer produced a false zero-gap optimum under HiGHS presolve",
        "preregistered_pair_count": preregistration["sampling"]["pair_count"],
        "frozen_usable_pair_count": artifact_lock["effective_pair_count"],
        "certificate_count_before_abort": len(certificates),
        "certificate_pair_ids": certificates,
        "certificates_accepted_for_confirmatory_exact_distribution": 0,
        "distribution_computed": False,
        "predictor_models_fitted": False,
        "preregistered_generality_gate_evaluated": False,
        "table_bank_built": False,
        "deployment_prototype_built": False,
        "counterexample": {
            "path": str(COUNTEREXAMPLE.relative_to(ROOT)),
            "sha256": sha256(COUNTEREXAMPLE),
            "pair_id": counterexample["pair_id"],
            "physical_slots": counterexample["physical_slots"],
            "reported_primal": counterexample["milp_instruction_primal"],
            "reported_dual": counterexample["milp_instruction_dual"],
            "reported_gap": counterexample["milp_reported_gap"],
            "feasible_dp_objective": counterexample["independent_dp_instruction_bytes"],
            "captured_matrix_maximum_violation": counterexample[
                "captured_milp_feasible_vector"
            ]["maximum_constraint_violation"],
            "no_presolve_primal": counterexample[
                "same_model_without_highs_presolve"
            ]["instruction_primal"],
            "no_presolve_dp": counterexample[
                "same_model_without_highs_presolve"
            ]["independent_dp_instruction_bytes"],
        },
        "locks": {
            "preregistration_sha256": sha256(BENCHMARK / "preregistration-v1.json"),
            "artifact_lock_sha256": sha256(artifact_lock_path),
            "analysis_spec_sha256": sha256(analysis_spec_path),
            "optimizer_sha256": sha256(optimizer),
            "execution_deviations_sha256": sha256(
                BENCHMARK / "execution-deviations.jsonl"
            ),
        },
        "next_authority_required": (
            "A new goal must authorize changing the optimizer execution path, such as "
            "disabling HiGHS presolve and revalidating all exactness tests, before the "
            "48-pair oracle sweep can restart."
        ),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    validity_path = RESULTS / "validity-decision-v1.json"
    validity_path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
    gate = {
        "format": "vcdiff-generality-gate-decision-v1",
        "passes": False,
        "status": "NOT EVALUATED",
        "reason": "oracle validity prerequisite failed before confirmatory metrics",
        "preregistered_components": {
            "project_repetition": "not evaluated",
            "non_source_repetition": "not evaluated",
            "grouped_classifier": "not evaluated",
            "validation_selector": "not evaluated",
        },
        "table_bank_authorized": False,
        "deployment_prototype_authorized": False,
        "validity_decision": str(validity_path.relative_to(ROOT)),
    }
    gate_path = RESULTS / "gate-decision-v1.json"
    gate_path.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n"
    )
    report = f"""# VCDIFF generality study: validity stop

## Outcome

The preregistered exact-gain study stopped before distribution or predictor
analysis. The frozen optimizer reported a q=1 MILP primal and dual of **8,261
instruction bytes with zero gap** on
`compressed-zstd-tar-gz-v1.5.4-to-v1.5.5`, while its selected table replayed in
the independent dynamic program at **8,258 bytes**.

This is not a rounding discrepancy. A vector reconstructed from that DP parse
has objective 8,258 and satisfies the captured MILP constraint matrix with
maximum violation **0**. Re-solving the identical matrix with HiGHS presolve
disabled proves **8,254**, and the independent DP also obtains 8,254.

Therefore the zero-gap result produced with presolve enabled is a false
optimality certificate. The optimizer file remains byte-identical to its frozen
SHA-256 `{decision['locks']['optimizer_sha256']}`.

## Consequences

- The full 48-pair exact gain distribution was **not** computed.
- The {len(certificates)} certificates emitted before the abort are retained as
  diagnostic artifacts, but none is promoted into the confirmatory exact
  distribution because they share the invalidated solver execution path.
- Predictor fitting and change-distance inference were **not** run.
- The preregistered generality gate is **not evaluated**, hence it does not pass.
- No reusable table bank or deployment prototype was built.

The acquisition result remains usable: 48 frozen pairs across source trees,
compiled code, structured data, and compressed controls are locked in
`benchmark/artifact-lock-v1.json`. Three preregistered SQLite source-tree pairs
were excluded before tracing because the common source artifact exceeded the
64 MiB limit.

## Replay

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \\
  python3 benchmark/capture_optimizer_counterexample.py \\
  --pair-id compressed-zstd-tar-gz-v1.5.4-to-v1.5.5 --physical-slots 1
```

The replay ledger is
`results/generality/optimizer-counterexamples/compressed-zstd-tar-gz-v1.5.4-to-v1.5.5-q1.json`.

Restarting the oracle sweep requires permission to change the optimizer
execution path and then revalidate exactness. That is outside the explicit
instruction not to modify the optimizer in this study.
"""
    report_path = RESULTS / "kill-report-v1.md"
    report_path.write_text(report)
    (RESULTS / "validity-v1.sha256").write_text(
        f"{sha256(COUNTEREXAMPLE)}  {COUNTEREXAMPLE.relative_to(ROOT)}\n"
        f"{sha256(validity_path)}  {validity_path.relative_to(ROOT)}\n"
        f"{sha256(gate_path)}  {gate_path.relative_to(ROOT)}\n"
        f"{sha256(report_path)}  {report_path.relative_to(ROOT)}\n"
    )
    print(validity_path)


if __name__ == "__main__":
    main()
