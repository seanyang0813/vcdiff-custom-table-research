#!/usr/bin/env python3
"""Run one frozen study under the locked exact-SCIP amendment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyscipopt
import scipy

import vcdiff_opt.optimizer as optimizer
from benchmark.scip_exact_adapter import ScipExactAdapter, ScipExactCall
from vcdiff_opt.study import run_study


ROOT = Path(__file__).resolve().parent.parent
AMENDMENT = ROOT / "benchmark/scip-validity-amendment-v2.json"
AMENDMENT_HASH = ROOT / "benchmark/scip-validity-amendment-v2.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_protocol() -> dict[str, Any]:
    if AMENDMENT_HASH.read_text().split()[0] != sha256(AMENDMENT):
        raise ValueError("exact-SCIP amendment hash drift")
    value = json.loads(AMENDMENT.read_text())
    for key in ("optimizer", "artifact_lock", "analysis_spec", "prior_amendment"):
        item = value["unchanged_scope"][key]
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"locked input drift: {item['path']}")
    adapter = value["proof_backend"]["adapter"]
    if sha256(ROOT / adapter["path"]) != adapter["sha256"]:
        raise ValueError("exact-SCIP adapter drift")
    runner = value["proof_backend"]["study_runner"]
    if sha256(ROOT / runner["path"]) != runner["sha256"]:
        raise ValueError("exact-SCIP study runner drift")
    environment = value["proof_backend"]["environment_lock"]
    if sha256(ROOT / environment["path"]) != environment["sha256"]:
        raise ValueError("exact-SCIP environment lock drift")
    return value


def stable_call(call: ScipExactCall) -> dict[str, Any]:
    return dict(call.__dict__)


def normalize_runtime(value: dict[str, Any]) -> None:
    value["proof_backend"] = "SCIP numerically exact binary model"


def render_report(certificate: dict[str, Any]) -> str:
    baseline = int(certificate["baseline"]["size"])
    optimum = certificate["global_optimum"]
    saving = baseline - int(optimum["file_bytes"])
    percent = 100.0 * saving / baseline
    return "\n".join(
        [
            "# VCDIFF restricted-table result with exact-SCIP proof",
            "",
            "## Result",
            "",
            f"Stock patch: {baseline:,} bytes. Exact amended-oracle patch: "
            f"{int(optimum['file_bytes']):,} bytes. Saving: {saving:,} bytes "
            f"({percent:.4f}%). Physical slots q={optimum['physical_slots']}.",
            "",
            "## Proof protocol",
            "",
            "The frozen optimizer generated the sparse model. Every intended [0,1] "
            "variable was explicitly binary and SCIP numerically exact mode returned "
            "OPTIMAL with equal integral primal and dual bounds. Integer-redundant "
            "occurrence-to-selection activation rows tighten only the fractional "
            "relaxation. The independently integral DP and emitted patch attain the "
            "bound, and two decoders reconstruct the target.",
            "",
            "## Evidence boundary",
            "",
            "This is exact only for the frozen logical trace and restricted canonical "
            "q=0..93 table family. It is a disclosed post-failure protocol amendment.",
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
    settings = amendment["proof_backend"]["settings"]
    adapter = ScipExactAdapter(
        scipy_no_presolve_hint=True,
        promote_all_binary=True,
        strengthen_activation_links=True,
        time_limit_seconds=float(settings["limits/time_seconds_per_model"]),
        memory_limit_mb=float(settings["limits/memory_mb"]),
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
        or not call.exact_mode
        for call in adapter.calls
    ):
        raise AssertionError("an exact-SCIP call violated the amendment")
    certificate = json.loads(certificate_path.read_text())
    certificate["format"] = "vcdiff-custom-table-certificate-v4-scip-exact"
    certificate["validity_amendment"] = {
        "path": str(AMENDMENT.relative_to(ROOT)),
        "sha256": sha256(AMENDMENT),
        "evidence_label": amendment["evidence_label"],
    }
    certificate["restriction"]["integer_proof_domain"] = (
        "all intended parse, pattern, q, and varint-state variables binary"
    )
    certificate["tools"]["optimizer"] = {
        "role": "frozen sparse-model generator only",
        **amendment["unchanged_scope"]["optimizer"],
    }
    certificate["tools"]["independent_integer_proof"] = {
        "api": "PySCIPOpt / SCIP numerically exact mode",
        "pyscipopt_version": pyscipopt.__version__,
        "scip_version": adapter.calls[0].scip_version,
        "numpy_version": np.__version__,
        "scipy_version_for_candidate_hint": scipy.__version__,
        "settings": settings,
        "status_required": "optimal",
        "calls": [stable_call(call) for call in adapter.calls],
    }
    certificate["tools"]["candidate_hint"] = {
        "api": "scipy.optimize.milp / HiGHS with presolve disabled",
        "role": "feasible construction only; supplies no proof bound",
        "acceptance": "integral, captured-matrix feasible, SCIP-optimal objective",
    }
    for evaluation in certificate["custom_evaluations"]:
        normalize_runtime(evaluation["solver"])
    normalize_runtime(certificate["global_optimum"]["solver"])
    certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    (arguments.output.resolve() / "report.md").write_text(render_report(certificate))
    print(certificate_path)


if __name__ == "__main__":
    main()
