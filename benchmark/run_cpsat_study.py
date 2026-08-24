#!/usr/bin/env python3
"""Run one frozen study with the independent CP-SAT proof amendment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import ortools
import scipy

import vcdiff_opt.optimizer as optimizer
from benchmark.cpsat_adapter import BinaryCpSatAdapter, CpSatCall
from vcdiff_opt.study import run_study


ROOT = Path(__file__).resolve().parent.parent
AMENDMENT = ROOT / "benchmark/validity-amendment-v1.json"
AMENDMENT_HASH = ROOT / "benchmark/validity-amendment-v1.sha256"
ADAPTER = ROOT / "benchmark/cpsat_adapter.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_protocol() -> dict[str, Any]:
    expected = AMENDMENT_HASH.read_text().split()[0]
    actual = sha256(AMENDMENT)
    if expected != actual:
        raise ValueError("validity amendment hash drift")
    amendment = json.loads(AMENDMENT.read_text())
    replacement = amendment["replacement_oracle"]
    if sha256(ADAPTER) != replacement["adapter_sha256"]:
        raise ValueError("CP-SAT adapter drift")
    optimizer_path = ROOT / amendment["unchanged_scope"]["optimizer_path"]
    if sha256(optimizer_path) != amendment["unchanged_scope"]["optimizer_sha256"]:
        raise ValueError("frozen optimizer drift")
    return amendment


def stable_call(call: CpSatCall) -> dict[str, Any]:
    return {
        "variables": call.variables,
        "original_integer_variables": call.original_integer_variables,
        "promoted_binary_variables": call.promoted_binary_variables,
        "constraints": call.constraints,
        "nonzeros": call.nonzeros,
        "objective": call.objective,
        "best_bound": call.best_bound,
        "ortools_version": call.ortools_version,
        "returned_solution_source": call.returned_solution_source,
        "hint_objective": call.hint_objective,
    }


def normalize_solver_runtime(value: dict[str, Any]) -> None:
    # Branch counts depend on the parallel CP-SAT portfolio and are operational,
    # not part of the proof. Keep the certificate deterministic.
    value["solver_nodes"] = None
    value["proof_backend"] = "OR-Tools CP-SAT exact Boolean model"


def render_report(certificate: dict[str, Any]) -> str:
    baseline = certificate["baseline"]["size"]
    optimum = certificate["global_optimum"]
    saving = baseline - optimum["file_bytes"]
    percent = 100.0 * saving / baseline
    calls = certificate["tools"]["independent_integer_proof"]["calls"]
    return "\n".join(
        [
            "# VCDIFF restricted-table result with independent CP-SAT proof",
            "",
            "## Result",
            "",
            f"Stock patch: {baseline:,} bytes. Exact amended-oracle patch: "
            f"{optimum['file_bytes']:,} bytes. Saving: {saving:,} bytes "
            f"({percent:.4f}%). Physical slots q={optimum['physical_slots']}.",
            "",
            "## Proof protocol",
            "",
            "The frozen optimizer generated the sparse model but was not trusted to "
            "prove its bound. Every [0,1] combinatorial variable was translated to a "
            "Boolean variable in OR-Tools CP-SAT. CP-SAT returned OPTIMAL with equal "
            "integer objective and best bound. The deterministic no-presolve HiGHS "
            "candidate was accepted only after it satisfied the captured matrix and "
            "matched that independently proved objective.",
            "",
            f"CP-SAT solved {len(calls)} nontrivial model(s). The global patch primal "
            f"and dual are both {optimum['solver']['patch_bytes']:,} bytes, with "
            f"reported gap {optimum['solver']['solver_gap']}.",
            "",
            "The selected table's independent integral DP attains the instruction "
            "bound, the emitted patch attains the full-patch bound, and both the strict "
            "Python decoder and unchanged historical xdelta decoder reconstruct the "
            "target.",
            "",
            "## Evidence boundary",
            "",
            "This is exact only for the frozen logical trace, one target window, fixed "
            "address caches, observed implicit-size single/pair patterns, and canonical "
            "q=0..93 prefix-replacement family. It is a disclosed post-failure solver "
            "amendment, not the originally preregistered HiGHS execution.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-xdelta", type=Path, required=True)
    parser.add_argument("--custom-table-decoder", type=Path, required=True)
    parser.add_argument("--max-slots", type=int, default=1)
    parser.add_argument("--global-max-slots", type=int, default=93)
    arguments = parser.parse_args()
    amendment = verify_protocol()
    adapter = BinaryCpSatAdapter(
        workers=int(
            amendment["replacement_oracle"]["proof_solver_workers"]
        ),
        scipy_no_presolve_hint=True,
    )
    original = optimizer.milp
    optimizer.milp = adapter
    try:
        certificate_path = run_study(
            arguments.source,
            arguments.target,
            arguments.output,
            trace_xdelta=arguments.trace_xdelta,
            custom_table_decoder=arguments.custom_table_decoder,
            max_slots=arguments.max_slots,
            global_max_slots=arguments.global_max_slots,
        )
    finally:
        optimizer.milp = original
    if any(
        call.returned_solution_source != "validated_scipy_no_presolve_hint"
        or call.objective != call.best_bound
        for call in adapter.calls
    ):
        raise AssertionError("a CP-SAT proof call violated the validity amendment")
    certificate = json.loads(certificate_path.read_text())
    certificate["format"] = "vcdiff-custom-table-certificate-v3-cpsat"
    certificate["validity_amendment"] = {
        "path": str(AMENDMENT),
        "sha256": sha256(AMENDMENT),
        "evidence_label": amendment["evidence_label"],
    }
    certificate["restriction"]["integer_proof_domain"] = (
        "all intended parse, pattern, q, and varint-state variables Boolean"
    )
    certificate["tools"]["optimizer"] = {
        "role": "frozen sparse-model generator only",
        "path": amendment["unchanged_scope"]["optimizer_path"],
        "sha256": amendment["unchanged_scope"]["optimizer_sha256"],
    }
    certificate["tools"]["independent_integer_proof"] = {
        "api": "OR-Tools CP-SAT",
        "ortools_version": ortools.__version__,
        "numpy_version": np.__version__,
        "scipy_version_for_candidate_hint": scipy.__version__,
        "workers": adapter.workers,
        "status_required": "OPTIMAL",
        "calls": [stable_call(call) for call in adapter.calls],
    }
    certificate["tools"]["candidate_hint"] = {
        "api": "scipy.optimize.milp / bundled HiGHS 1.2.0",
        "presolve": False,
        "role": "deterministic feasible construction only; supplies no proof bound",
        "acceptance": "integral, captured-matrix feasible, CP-SAT-optimal objective",
    }
    for evaluation in certificate["custom_evaluations"]:
        normalize_solver_runtime(evaluation["solver"])
    normalize_solver_runtime(certificate["global_optimum"]["solver"])
    certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    (arguments.output.resolve() / "report.md").write_text(render_report(certificate))
    print(certificate_path)


if __name__ == "__main__":
    main()
