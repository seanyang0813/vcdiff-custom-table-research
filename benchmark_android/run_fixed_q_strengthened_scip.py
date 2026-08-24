#!/usr/bin/env python3
"""Run and independently attain one strengthened exact-SCIP fixed-q model."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import vcdiff_opt.optimizer as optimizer
from benchmark.strengthened_scip_adapter import StrengthenedScipAdapter
from vcdiff_opt.codec import build_custom_table, encode_file
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.model import WindowTrace


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--physical-slots", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-limit-seconds", type=float, default=1800.0)
    parser.add_argument("--memory-limit-mb", type=float, default=6000.0)
    parser.add_argument("--display", action="store_true")
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    trace_document = json.loads(arguments.trace.read_text())
    windows = tuple(
        WindowTrace.from_dict(value) for value in trace_document["windows"]
    )
    source = Path(trace_document["source"]["path"]).read_bytes()
    target = Path(trace_document["target"]["path"]).read_bytes()
    adapter = StrengthenedScipAdapter(
        time_limit_seconds=arguments.time_limit_seconds,
        memory_limit_mb=arguments.memory_limit_mb,
        display=arguments.display,
    )
    original = optimizer.milp
    started = time.monotonic()
    optimizer.milp = adapter
    result = None
    error: RuntimeError | None = None
    try:
        try:
            result = optimizer.solve_selection(windows, arguments.physical_slots)
        except RuntimeError as caught:
            error = caught
    finally:
        optimizer.milp = original
    elapsed = time.monotonic() - started
    document = {
        "format": "vcdiff-android-fixed-q-strengthened-scip-v1",
        "status": "nonexact_solver_stop" if result is None else "exact_fixed_q",
        "evidence_boundary": (
            "Exact only for this fixed q if exact SCIP returns OPTIMAL and the "
            "independent integral parser attains its equal primal/dual objective. "
            "This is not a global q=0..93 pair label."
        ),
        "trace": {"path": str(arguments.trace), "sha256": sha256(arguments.trace)},
        "physical_slots": arguments.physical_slots,
        "elapsed_seconds": elapsed,
        "model_fingerprints": adapter.model_fingerprints,
        "solver_calls": [call.__dict__ for call in adapter.calls],
        "nonresult_reason": None if error is None else str(error),
    }
    if result is not None:
        table = build_custom_table(result.selected, arguments.physical_slots)
        encoding = encode_file(
            windows,
            source,
            target,
            table=table,
            physical_slots=arguments.physical_slots,
        )
        instruction_bytes = sum(
            window.instruction_length for window in encoding.windows
        )
        if instruction_bytes != result.instruction_bytes:
            raise AssertionError("integral DP does not attain exact SCIP objective")
        if decode_file(encoding.encoded, source) != target:
            raise AssertionError("Python decoder rejected exact SCIP fixed-q patch")
        patch = arguments.output / "restricted-optimal.vcdiff"
        patch.write_bytes(encoding.encoded)
        document.update(
            {
                "selection": result.to_dict(),
                "attained_patch": {
                    "path": str(patch),
                    "bytes": len(encoding.encoded),
                    "sha256": sha256(patch),
                    "instruction_bytes": instruction_bytes,
                    "python_decoder_round_trip": True,
                },
            }
        )
    output = arguments.output / "result.json"
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(output)


if __name__ == "__main__":
    main()
