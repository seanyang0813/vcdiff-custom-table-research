#!/usr/bin/env python3
"""Validate the independent CP-SAT recovery on the frozen counterexample."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import ortools
import scipy

import vcdiff_opt.optimizer as optimizer
from benchmark.cpsat_adapter import BinaryCpSatAdapter
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
    ROOT
    / "results/generality/optimizer-counterexamples"
    / f"{PAIR_ID}-q1.json"
)
OUTPUT = ROOT / "results/generality/cpsat-recovery-diagnostic-v1.json"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def selected_hash(selected: tuple[Pattern, ...]) -> str:
    encoded = json.dumps(
        [pattern.to_dict() for pattern in selected],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256_bytes(encoded)


def with_adapter(function: Any) -> tuple[Any, BinaryCpSatAdapter]:
    adapter = BinaryCpSatAdapter(
        workers=8,
        scipy_no_presolve_hint=True,
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
    pair = next(pair for pair in lock["pairs"] if pair["id"] == PAIR_ID)
    trace = json.loads(TRACE.read_text())
    windows = tuple(WindowTrace.from_dict(value) for value in trace["windows"])
    source = (ROOT / pair["source"]["artifact"]).read_bytes()
    target = (ROOT / pair["target"]["artifact"]).read_bytes()
    default = encode_file(windows, source, target)
    baseline = Path(trace["baseline_patch"]["path"]).read_bytes()
    if default.encoded != baseline:
        raise AssertionError("default reparse is not the frozen stock patch")
    candidates = observed_patterns(windows)

    fixed, fixed_adapter = with_adapter(
        lambda: optimizer.solve_selection(windows, 1, candidates=candidates)
    )
    fixed_table = build_custom_table(fixed.selected, 1)
    fixed_encoding = encode_file(
        windows, source, target, table=fixed_table, physical_slots=1
    )
    fixed_dp = sum(window.instruction_length for window in fixed_encoding.windows)
    if fixed_dp != fixed.instruction_bytes:
        raise AssertionError("CP-SAT fixed-q result is not attained by the DP")

    probe = Pattern((Atom(ADD, 255),))
    header_lengths = [len(encode_file_header()[0])]
    for q in range(1, 94):
        header_lengths.append(
            len(encode_file_header(build_custom_table((probe,), q), q)[0])
        )

    def solve_global() -> tuple[Any, BinaryCpSatAdapter, bytes, bytes | None]:
        result, adapter = with_adapter(
            lambda: optimizer.solve_global_selection(
                windows[0],
                93,
                file_header_lengths=header_lengths,
                data_bytes=sum(window.data_length for window in default.windows),
                address_bytes=sum(window.address_length for window in default.windows),
                candidates=candidates,
            )
        )
        table = (
            DEFAULT_TABLE
            if result.physical_slots == 0
            else build_custom_table(result.selected, result.physical_slots)
        )
        encoding = encode_file(
            windows,
            source,
            target,
            table=table,
            physical_slots=result.physical_slots,
        )
        if len(encoding.encoded) != result.patch_bytes:
            raise AssertionError("CP-SAT global bound does not equal emitted patch")
        if sum(window.instruction_length for window in encoding.windows) != result.instruction_bytes:
            raise AssertionError("CP-SAT global instruction bound is not attained")
        if decode_file(encoding.encoded, source, expected_target_size=len(target)) != target:
            raise AssertionError("strict Python decoder rejected CP-SAT optimum")
        table_bytes = None if result.physical_slots == 0 else table_to_bytes(table)
        return result, adapter, encoding.encoded, table_bytes

    first, first_adapter, first_patch, first_table = solve_global()
    second, second_adapter, second_patch, second_table = solve_global()
    if (
        first.to_dict() != second.to_dict()
        or first_patch != second_patch
        or first_table != second_table
    ):
        raise AssertionError("CP-SAT recovery is not deterministic across repetitions")
    with tempfile.TemporaryDirectory(prefix="vcdiff-cpsat-recovery-") as directory:
        patch_path = Path(directory) / "patch.vcdiff"
        patch_path.write_bytes(first_patch)
        historical = _verify_with_decoder(DECODER, ROOT / pair["source"]["artifact"], patch_path, target)

    previous = json.loads(COUNTEREXAMPLE.read_text())
    result = {
        "format": "vcdiff-cpsat-recovery-diagnostic-v1",
        "status": "validated on frozen counterexample",
        "pair_id": PAIR_ID,
        "artifact_lock_sha256": sha256(LOCK),
        "frozen_optimizer_sha256": sha256(ROOT / lock["optimizer"]["optimizer_path"]),
        "counterexample_sha256": sha256(COUNTEREXAMPLE),
        "environment": {
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "ortools": ortools.__version__,
            "cp_sat_workers": 8,
            "candidate_hint": "SciPy HiGHS 1.2.0 with presolve disabled; hint supplies no bound",
        },
        "old_invalid_result": {
            "reported_primal": previous["milp_instruction_primal"],
            "reported_dual": previous["milp_instruction_dual"],
            "reported_gap": previous["milp_reported_gap"],
            "feasible_dp": previous["independent_dp_instruction_bytes"],
        },
        "fixed_q1_recovery": {
            "instruction_primal": fixed.instruction_bytes,
            "instruction_dual": fixed.solver_dual_bound,
            "independent_dp": fixed_dp,
            "selected_patterns": [value.to_dict() for value in fixed.selected],
            "selected_table_sha256": sha256_bytes(table_to_bytes(fixed_table)),
            "solver_call": fixed_adapter.calls[0].__dict__,
        },
        "global_recovery": {
            "repetitions": 2,
            "identical": True,
            "physical_slots": first.physical_slots,
            "selected_pattern_count": len(first.selected),
            "selected_patterns_sha256": selected_hash(first.selected),
            "table_sha256": None if first_table is None else sha256_bytes(first_table),
            "stock_patch_bytes": len(default.encoded),
            "optimal_patch_bytes": len(first_patch),
            "saving_bytes": len(default.encoded) - len(first_patch),
            "optimal_patch_sha256": sha256_bytes(first_patch),
            "instruction_bytes": first.instruction_bytes,
            "patch_primal": first.patch_bytes,
            "patch_dual": first.patch_dual_bound,
            "solver_gap": first.solver_gap,
            "solver_calls": [
                first_adapter.calls[0].__dict__,
                second_adapter.calls[0].__dict__,
            ],
            "historical_decoder": historical,
        },
        "evidence_boundary": (
            "This validates the replacement solver protocol on the trigger pair only. "
            "It does not itself validate the remaining frozen corpus."
        ),
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(OUTPUT)
    print(
        f"q1={fixed.instruction_bytes}; global={len(default.encoded)} -> "
        f"{len(first_patch)} q={first.physical_slots}"
    )


if __name__ == "__main__":
    main()
