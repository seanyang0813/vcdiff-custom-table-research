#!/usr/bin/env python3
"""Independently replay every stored fixed-q rational-dual lower bound."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from pathlib import Path

import vcdiff_opt.optimizer as optimizer
from benchmark.integer_dual_adapter import RationalDualBoundReplayAdapter
from vcdiff_opt.model import WindowTrace


def verify_one(trace_path: str, bound_root: str, q: int) -> dict[str, object]:
    trace = json.loads(Path(trace_path).read_text())
    windows = tuple(WindowTrace.from_dict(value) for value in trace["windows"])
    directory = Path(bound_root) / f"{q:03d}"
    bound_document = json.loads((directory / "lower-bound.json").read_text())
    replay = RationalDualBoundReplayAdapter(directory / "proof")
    original = optimizer.milp
    optimizer.milp = replay
    try:
        try:
            optimizer.solve_selection(windows, q)
        except RuntimeError:
            pass
        else:
            raise AssertionError("bound-only replay unexpectedly returned a witness")
    finally:
        optimizer.milp = original
    if len(replay.calls) != 1:
        raise AssertionError("bound-only replay did not consume exactly one proof")
    call = replay.calls[0]
    recorded = bound_document["bound_calls"][0]
    if not (
        call.exact_dual_numerator == int(recorded["exact_dual_numerator"])
        and call.exact_dual_denominator
        == int(recorded["exact_dual_denominator"])
        and call.integer_lattice_lower_bound
        == int(bound_document["instruction_bytes_integer_lower_bound"])
        and call.model_fingerprint == recorded["model_fingerprint"]
    ):
        raise ValueError(f"replayed bound mismatch at q={q}")
    return {
        "status": "replayed_exact",
        "physical_slots": q,
        "exact_dual_numerator": call.exact_dual_numerator,
        "exact_dual_denominator": call.exact_dual_denominator,
        "instruction_bytes_integer_lower_bound": call.integer_lattice_lower_bound,
        "full_patch_bytes_integer_lower_bound": int(
            bound_document["full_patch_bytes_integer_lower_bound"]
        ),
        "model_fingerprint": call.model_fingerprint,
        "proof_vectors_sha256": call.proof_vectors_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--bound-root", type=Path, required=True)
    parser.add_argument("--first-q", type=int, default=1)
    parser.add_argument("--last-q", type=int, default=92)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if not 1 <= arguments.first_q <= arguments.last_q <= 93:
        raise ValueError("q range must lie in 1..93")
    if not 1 <= arguments.workers <= 4:
        raise ValueError("workers must lie in 1..4")
    started = time.monotonic()
    rows: dict[int, dict[str, object]] = {}
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=arguments.workers
    ) as executor:
        futures = {
            executor.submit(
                verify_one,
                str(arguments.trace),
                str(arguments.bound_root),
                q,
            ): q
            for q in range(arguments.first_q, arguments.last_q + 1)
        }
        for future in concurrent.futures.as_completed(futures):
            q = futures[future]
            rows[q] = future.result()
            print(f"q={q}: replayed_exact", flush=True)
    document = {
        "format": "vcdiff-fixed-q-rational-dual-replay-ledger-v1",
        "trace": str(arguments.trace),
        "bound_root": str(arguments.bound_root),
        "q_range": [arguments.first_q, arguments.last_q],
        "expected_count": arguments.last_q - arguments.first_q + 1,
        "replayed_exact_count": len(rows),
        "elapsed_seconds": time.monotonic() - started,
        "rows": [rows[q] for q in sorted(rows)],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(arguments.output)


if __name__ == "__main__":
    main()
