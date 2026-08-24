#!/usr/bin/env python3
"""Turn a stored rational-dual vector into a replayed fixed-q bound record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import vcdiff_opt.optimizer as optimizer
from benchmark.integer_dual_adapter import (
    RationalDualBoundReplayAdapter,
    bound_calls_as_dicts,
)
from benchmark_android.finalize_integer_dual_pair import fixed_q_patch_lower_bound
from vcdiff_opt.codec import encode_file
from vcdiff_opt.model import WindowTrace


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--physical-slots", type=int, required=True)
    parser.add_argument("--proof-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    trace = json.loads(arguments.trace.read_text())
    windows = tuple(WindowTrace.from_dict(value) for value in trace["windows"])
    if len(windows) != 1:
        raise ValueError("full-patch lower bound requires one window")
    replay = RationalDualBoundReplayAdapter(arguments.proof_directory)
    original = optimizer.milp
    optimizer.milp = replay
    try:
        try:
            optimizer.solve_selection(windows, arguments.physical_slots)
        except RuntimeError:
            pass
        else:
            raise AssertionError("bound-only replay unexpectedly returned a witness")
    finally:
        optimizer.milp = original
    if len(replay.calls) != 1:
        raise AssertionError("stored proof did not replay exactly once")
    source_path = Path(trace["source"]["path"])
    target_path = Path(trace["target"]["path"])
    source = source_path.read_bytes()
    target = target_path.read_bytes()
    default_encoding = encode_file(windows, source, target)
    data_bytes = sum(value.data_length for value in default_encoding.windows)
    address_bytes = sum(value.address_length for value in default_encoding.windows)
    call = replay.calls[0]
    patch_lower, header_bytes = fixed_q_patch_lower_bound(
        windows[0],
        arguments.physical_slots,
        call.integer_lattice_lower_bound,
        data_bytes,
        address_bytes,
    )
    value = {
        "format": "vcdiff-android-fixed-q-rational-dual-bound-v1",
        "status": "exact_lower_bound_only",
        "evidence_boundary": (
            "Exact lower bound for this fixed q, not an attained fixed-q "
            "optimum or preregistered pair label."
        ),
        "trace": {"path": str(arguments.trace), "sha256": sha256(arguments.trace)},
        "source": {"path": str(source_path), "sha256": hashlib.sha256(source).hexdigest()},
        "target": {"path": str(target_path), "sha256": hashlib.sha256(target).hexdigest()},
        "physical_slots": arguments.physical_slots,
        "instruction_bytes_integer_lower_bound": call.integer_lattice_lower_bound,
        "full_patch_bytes_integer_lower_bound": patch_lower,
        "file_header_bytes": header_bytes,
        "data_bytes": data_bytes,
        "address_bytes": address_bytes,
        "bound_calls": bound_calls_as_dicts(replay.calls),
        "construction": "fresh replay of previously stored numerator vectors",
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(arguments.output)


if __name__ == "__main__":
    main()
