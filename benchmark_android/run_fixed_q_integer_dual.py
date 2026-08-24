#!/usr/bin/env python3
"""Construct and independently replay one exact fixed-q Android result."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import vcdiff_opt.optimizer as optimizer
from benchmark.integer_dual_adapter import (
    IntegerDualAdapter,
    IntegerDualReplayAdapter,
    bound_calls_as_dicts,
    calls_as_dicts,
)
from vcdiff_opt.codec import build_custom_table, encode_file, encode_file_header
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.model import ADD, Atom, Pattern, WindowTrace
from vcdiff_opt.varint import varint_size


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--physical-slots", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--time-limit-seconds", type=float, default=1800.0)
    parser.add_argument("--bound-only", action="store_true")
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    proof_directory = arguments.output / "proof"
    trace_document = json.loads(arguments.trace.read_text())
    windows = tuple(
        WindowTrace.from_dict(value) for value in trace_document["windows"]
    )
    source_path = Path(trace_document["source"]["path"])
    target_path = Path(trace_document["target"]["path"])
    source = source_path.read_bytes()
    target = target_path.read_bytes()

    constructor = IntegerDualAdapter(
        proof_directory=proof_directory,
        time_limit_seconds=arguments.time_limit_seconds,
        bound_only=arguments.bound_only,
    )
    original = optimizer.milp
    started = time.monotonic()
    optimizer.milp = constructor
    solve_error: RuntimeError | None = None
    result = None
    try:
        try:
            result = optimizer.solve_selection(windows, arguments.physical_slots)
        except RuntimeError as error:
            solve_error = error
    finally:
        optimizer.milp = original
    construction_elapsed = time.monotonic() - started

    if result is None:
        if not constructor.bound_calls:
            assert solve_error is not None
            raise solve_error
        bound = constructor.bound_calls[-1]
        default_encoding = encode_file(windows, source, target)
        data_bytes = sum(window.data_length for window in default_encoding.windows)
        address_bytes = sum(
            window.address_length for window in default_encoding.windows
        )
        if len(windows) != 1:
            raise ValueError("full-patch lower bound requires exactly one window")
        window = windows[0]
        probe = Pattern((Atom(ADD, 255),))
        probe_table = build_custom_table((probe,), arguments.physical_slots)
        file_header_bytes = len(
            encode_file_header(probe_table, arguments.physical_slots)[0]
        )
        instruction_lower = bound.integer_lattice_lower_bound
        delta_constant = (
            varint_size(window.target_length)
            + 1
            + varint_size(data_bytes)
            + varint_size(address_bytes)
            + data_bytes
            + address_bytes
        )
        window_prefix = 1
        if window.source_used:
            window_prefix += varint_size(window.source_length)
            window_prefix += varint_size(window.source_position)
        instruction_varint = varint_size(instruction_lower)
        delta_bytes = delta_constant + instruction_varint + instruction_lower
        full_patch_lower = (
            file_header_bytes
            + window_prefix
            + delta_constant
            + instruction_lower
            + instruction_varint
            + varint_size(delta_bytes)
        )
        document = {
            "format": "vcdiff-android-fixed-q-rational-dual-bound-v1",
            "status": "exact_lower_bound_only",
            "evidence_boundary": (
                "Exact lower bound for this fixed q, not an attained fixed-q "
                "optimum or preregistered pair label."
            ),
            "trace": {
                "path": str(arguments.trace),
                "sha256": sha256(arguments.trace),
            },
            "source": {
                "path": str(source_path),
                "sha256": hashlib.sha256(source).hexdigest(),
            },
            "target": {
                "path": str(target_path),
                "sha256": hashlib.sha256(target).hexdigest(),
            },
            "physical_slots": arguments.physical_slots,
            "instruction_bytes_integer_lower_bound": instruction_lower,
            "full_patch_bytes_integer_lower_bound": full_patch_lower,
            "file_header_bytes": file_header_bytes,
            "data_bytes": data_bytes,
            "address_bytes": address_bytes,
            "construction_elapsed_seconds": construction_elapsed,
            "bound_calls": bound_calls_as_dicts(constructor.bound_calls),
            "witness_search_skipped": arguments.bound_only,
            "nonattainment_reason": None if solve_error is None else str(solve_error),
        }
        result_path = arguments.output / "lower-bound.json"
        result_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        print(result_path)
        return

    replay = IntegerDualReplayAdapter(proof_directory)
    optimizer.milp = replay
    try:
        replayed = optimizer.solve_selection(windows, arguments.physical_slots)
    finally:
        optimizer.milp = original
    if replayed != result:
        raise AssertionError("stored integer-dual replay changed the fixed-q result")

    table = build_custom_table(result.selected, arguments.physical_slots)
    encoding = encode_file(
        windows,
        source,
        target,
        table=table,
        physical_slots=arguments.physical_slots,
    )
    if decode_file(encoding.encoded, source) != target:
        raise AssertionError("independent decoder rejected the fixed-q witness")
    instruction_bytes = sum(
        window.instruction_length for window in encoding.windows
    )
    if instruction_bytes != result.instruction_bytes:
        raise AssertionError("integral parse does not attain the dual bound")

    document = {
        "format": "vcdiff-android-fixed-q-integer-dual-result-v1",
        "status": "exact_fixed_q_only",
        "evidence_boundary": (
            "Exact only for this fixed q in the frozen restricted table family; "
            "not yet a global q=0..93 oracle or preregistered corpus label."
        ),
        "trace": {
            "path": str(arguments.trace),
            "sha256": sha256(arguments.trace),
        },
        "source": {
            "path": str(source_path),
            "sha256": hashlib.sha256(source).hexdigest(),
        },
        "target": {
            "path": str(target_path),
            "sha256": hashlib.sha256(target).hexdigest(),
        },
        "physical_slots": arguments.physical_slots,
        "selection": result.to_dict(),
        "attained_patch": {
            "bytes": len(encoding.encoded),
            "sha256": hashlib.sha256(encoding.encoded).hexdigest(),
            "file_header_bytes": encoding.file_header_length,
            "nested_table_delta_bytes": encoding.table_delta_length,
            "data_bytes": sum(window.data_length for window in encoding.windows),
            "instruction_bytes": instruction_bytes,
            "address_bytes": sum(
                window.address_length for window in encoding.windows
            ),
            "independent_decoder_round_trip": True,
        },
        "construction_elapsed_seconds": construction_elapsed,
        "constructor_calls": calls_as_dicts(constructor.calls),
        "replay_calls": calls_as_dicts(replay.calls),
    }
    result_path = arguments.output / "result.json"
    result_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(result_path)


if __name__ == "__main__":
    main()
