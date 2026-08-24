#!/usr/bin/env python3
"""Validate exact SCIP on the frozen HiGHS counterexample.

This is a diagnostic run.  It deliberately predates and cannot itself amend
the locked confirmatory protocol.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pyscipopt
import scipy

import vcdiff_opt.optimizer as optimizer
from benchmark.scip_exact_adapter import ScipExactAdapter
from vcdiff_opt.codec import build_custom_table, encode_file, encode_file_header
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.default_table import DEFAULT_TABLE, table_to_bytes
from vcdiff_opt.model import ADD, Atom, Pattern, WindowTrace, observed_patterns
from vcdiff_opt.study import _verify_with_decoder


ROOT = Path(__file__).resolve().parent.parent
PAIR_ID = "compressed-zstd-tar-gz-v1.5.4-to-v1.5.5"
TRACE = ROOT / "benchmark_artifacts" / PAIR_ID / "trace.json"
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
COUNTEREXAMPLE = (
    ROOT / "results/generality/optimizer-counterexamples" / f"{PAIR_ID}-q1.json"
)
OUTPUT = ROOT / "results/generality/scip-exact-recovery-diagnostic-v1.json"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def with_adapter(function: Any) -> tuple[Any, ScipExactAdapter]:
    adapter = ScipExactAdapter(
        scipy_no_presolve_hint=True,
        promote_all_binary=True,
        strengthen_activation_links=True,
    )
    original = optimizer.milp
    optimizer.milp = adapter
    try:
        result = function()
    finally:
        optimizer.milp = original
    return result, adapter


def main() -> None:
    lock = json.loads(LOCK.read_text())
    pair = next(value for value in lock["pairs"] if value["id"] == PAIR_ID)
    trace = json.loads(TRACE.read_text())
    windows = tuple(WindowTrace.from_dict(value) for value in trace["windows"])
    source = (ROOT / pair["source"]["artifact"]).read_bytes()
    target = (ROOT / pair["target"]["artifact"]).read_bytes()
    default = encode_file(windows, source, target)
    if default.encoded != Path(trace["baseline_patch"]["path"]).read_bytes():
        raise AssertionError("default reparse differs from frozen stock patch")
    candidates = observed_patterns(windows)

    fixed, fixed_adapter = with_adapter(
        lambda: optimizer.solve_selection(windows, 1, candidates=candidates)
    )
    fixed_table = build_custom_table(fixed.selected, 1)
    fixed_encoding = encode_file(
        windows, source, target, table=fixed_table, physical_slots=1
    )
    fixed_dp = sum(value.instruction_length for value in fixed_encoding.windows)
    if fixed_dp != fixed.instruction_bytes:
        raise AssertionError("exact-SCIP q=1 bound is not attained by the DP")

    probe = Pattern((Atom(ADD, 255),))
    header_lengths = [len(encode_file_header()[0])] + [
        len(encode_file_header(build_custom_table((probe,), q), q)[0])
        for q in range(1, 94)
    ]
    global_result, global_adapter = with_adapter(
        lambda: optimizer.solve_global_selection(
            windows[0],
            93,
            file_header_lengths=header_lengths,
            data_bytes=sum(value.data_length for value in default.windows),
            address_bytes=sum(value.address_length for value in default.windows),
            candidates=candidates,
        )
    )
    table = (
        DEFAULT_TABLE
        if global_result.physical_slots == 0
        else build_custom_table(
            global_result.selected, global_result.physical_slots
        )
    )
    encoding = encode_file(
        windows,
        source,
        target,
        table=table,
        physical_slots=global_result.physical_slots,
    )
    if len(encoding.encoded) != global_result.patch_bytes:
        raise AssertionError("exact-SCIP global bound differs from emitted patch")
    if decode_file(encoding.encoded, source, expected_target_size=len(target)) != target:
        raise AssertionError("strict decoder rejected exact-SCIP patch")
    with tempfile.TemporaryDirectory(prefix="vcdiff-scip-recovery-") as directory:
        patch = Path(directory) / "patch.vcdiff"
        patch.write_bytes(encoding.encoded)
        historical = _verify_with_decoder(
            DECODER, ROOT / pair["source"]["artifact"], patch, target
        )

    previous = json.loads(COUNTEREXAMPLE.read_text())
    result = {
        "format": "vcdiff-scip-exact-recovery-diagnostic-v1",
        "status": "validated on frozen counterexample only",
        "pair_id": PAIR_ID,
        "artifact_lock_sha256": sha256(LOCK),
        "frozen_optimizer_sha256": sha256(ROOT / lock["optimizer"]["optimizer_path"]),
        "adapter_path": "benchmark/scip_exact_adapter.py",
        "adapter_sha256": sha256(ROOT / "benchmark/scip_exact_adapter.py"),
        "environment": {
            "pyscipopt": pyscipopt.__version__,
            "scip": fixed_adapter.calls[0].scip_version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "exact_mode": True,
            "all_model_variables_binary": True,
            "activation_links": "occurrence <= selected",
        },
        "old_invalid_result": {
            "reported_primal": previous["milp_instruction_primal"],
            "reported_dual": previous["milp_instruction_dual"],
            "feasible_dp": previous["independent_dp_instruction_bytes"],
        },
        "fixed_q1_recovery": {
            "instruction_primal": fixed.instruction_bytes,
            "instruction_dual": fixed.solver_dual_bound,
            "independent_dp": fixed_dp,
            "table_sha256": sha256_bytes(table_to_bytes(fixed_table)),
            "solver_call": fixed_adapter.calls[0].__dict__,
        },
        "global_recovery": {
            "stock_patch_bytes": len(default.encoded),
            "optimal_patch_bytes": len(encoding.encoded),
            "saving_bytes": len(default.encoded) - len(encoding.encoded),
            "physical_slots": global_result.physical_slots,
            "patch_primal": global_result.patch_bytes,
            "patch_dual": global_result.patch_dual_bound,
            "patch_sha256": sha256_bytes(encoding.encoded),
            "solver_call": global_adapter.calls[0].__dict__,
            "historical_decoder": historical,
        },
        "activation_strengthening_argument": (
            "For each pattern, the frozen row is sum(x_i) <= M*y with "
            "0<=x_i<=1 and binary y. If y=0, nonnegativity forces all x_i=0; "
            "if y=1, each added x_i<=y is the existing upper bound. Therefore "
            "the added inequalities preserve the integer feasible set."
        ),
        "evidence_boundary": (
            "This validates exact SCIP on the trigger pair only and does not amend "
            "or complete the frozen corpus."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(OUTPUT)
    print(
        f"q1={fixed.instruction_bytes}; global={len(default.encoded)} -> "
        f"{len(encoding.encoded)} q={global_result.physical_slots}"
    )


if __name__ == "__main__":
    main()
