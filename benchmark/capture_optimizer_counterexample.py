#!/usr/bin/env python3
"""Capture a replayable MILP-versus-DP disagreement without changing the optimizer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import vcdiff_opt.optimizer as optimizer
from vcdiff_opt.codec import build_custom_table, encode_file
from vcdiff_opt.default_table import DEFAULT_TABLE, PAIR_BANK_START, table_to_bytes
from vcdiff_opt.model import Pattern, WindowTrace, observed_patterns
from vcdiff_opt.parser import best_entry


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
OUTPUT = ROOT / "results/generality/optimizer-counterexamples"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstruct_edges(
    windows: tuple[WindowTrace, ...], physical_slots: int, candidates: tuple[Pattern, ...]
) -> tuple[list[optimizer.ModelEdge], tuple[Pattern, ...]]:
    observed = set(candidates)
    removed = set(range(PAIR_BANK_START, PAIR_BANK_START + physical_slots))
    base_table = tuple(
        entry for opcode, entry in enumerate(DEFAULT_TABLE) if opcode not in removed
    )
    edges: list[optimizer.ModelEdge] = []
    for window_number, window in enumerate(windows):
        for start, instruction in enumerate(window.instructions):
            single = Pattern((instruction.atom,)) if instruction.size <= 255 else None
            base_single = best_entry(base_table, (instruction.atom,))
            assert base_single is not None
            edges.append(
                optimizer.ModelEdge(window_number, start, 1, base_single[0], None)
            )
            if single is not None and single in observed and base_single[0] > 1:
                edges.append(optimizer.ModelEdge(window_number, start, 1, 1, single))
            if start + 1 >= len(window.instructions):
                continue
            second = window.instructions[start + 1]
            pair = (
                Pattern((instruction.atom, second.atom))
                if instruction.size <= 255 and second.size <= 255
                else None
            )
            base_pair = best_entry(base_table, (instruction.atom, second.atom))
            if base_pair is not None:
                edges.append(
                    optimizer.ModelEdge(window_number, start, 2, base_pair[0], None)
                )
            if (
                pair is not None
                and pair in observed
                and (base_pair is None or base_pair[0] > 1)
            ):
                edges.append(optimizer.ModelEdge(window_number, start, 2, 1, pair))
    candidate_tuple = tuple(
        sorted({edge.pattern for edge in edges if edge.pattern is not None})
    )
    return edges, candidate_tuple


def parse_feasible_vector(
    edges: list[optimizer.ModelEdge],
    candidate_tuple: tuple[Pattern, ...],
    selected: tuple[Pattern, ...],
    encoding: object,
    physical_slots: int,
) -> np.ndarray:
    vector = np.zeros(len(edges) + len(candidate_tuple), dtype=float)
    selected_set = set(selected)
    for window_number, encoded_window in enumerate(encoding.windows):
        for token in encoded_window.parse.tokens:
            is_custom = PAIR_BANK_START <= token.opcode < PAIR_BANK_START + physical_slots
            expected_pattern = selected_set if is_custom else {None}
            matches = [
                index
                for index, edge in enumerate(edges)
                if edge.window == window_number
                and edge.start == token.start
                and edge.width == token.width
                and edge.byte_cost == token.byte_cost
                and edge.pattern in expected_pattern
            ]
            if len(matches) != 1:
                raise AssertionError(f"cannot map parse token uniquely: {token}")
            vector[matches[0]] = 1.0
    candidate_index = {pattern: index for index, pattern in enumerate(candidate_tuple)}
    for pattern in selected:
        vector[len(edges) + candidate_index[pattern]] = 1.0
    return vector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--physical-slots", type=int, default=1)
    arguments = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    pair = next(
        (value for value in lock["pairs"] if value["id"] == arguments.pair_id),
        None,
    )
    if pair is None:
        raise ValueError(f"unknown frozen pair: {arguments.pair_id}")
    directory = ROOT / "benchmark_artifacts" / arguments.pair_id
    trace_path = directory / "trace.json"
    trace = json.loads(trace_path.read_text())
    windows = tuple(WindowTrace.from_dict(value) for value in trace["windows"])
    candidates = observed_patterns(windows)
    captured: dict[str, object] = {}
    original_milp = optimizer.milp

    def capture_milp(*call_args: object, **call_kwargs: object) -> object:
        captured["args"] = call_args
        captured["kwargs"] = call_kwargs
        result = original_milp(*call_args, **call_kwargs)
        captured["result"] = result
        return result

    optimizer.milp = capture_milp
    try:
        solver = optimizer.solve_selection(
            windows, arguments.physical_slots, candidates=candidates
        )
    finally:
        optimizer.milp = original_milp
    table = build_custom_table(solver.selected, arguments.physical_slots)
    source = (ROOT / pair["source"]["artifact"]).read_bytes()
    target = (ROOT / pair["target"]["artifact"]).read_bytes()
    encoding = encode_file(
        windows,
        source,
        target,
        table=table,
        physical_slots=arguments.physical_slots,
    )
    dp_instruction_bytes = sum(
        window.instruction_length for window in encoding.windows
    )
    if dp_instruction_bytes == solver.instruction_bytes:
        raise ValueError("the requested run is not a counterexample")
    edges, candidate_tuple = reconstruct_edges(
        windows, arguments.physical_slots, candidates
    )
    feasible = parse_feasible_vector(
        edges,
        candidate_tuple,
        solver.selected,
        encoding,
        arguments.physical_slots,
    )
    milp_kwargs = dict(captured["kwargs"])
    objective = np.asarray(milp_kwargs["c"], dtype=float)
    constraint = milp_kwargs["constraints"]
    activity = constraint.A @ feasible
    lower_violation = np.maximum(constraint.lb - activity, 0.0)
    upper_violation = np.maximum(activity - constraint.ub, 0.0)
    max_violation = float(max(lower_violation.max(), upper_violation.max()))
    feasible_objective = int(round(float(objective @ feasible)))
    if max_violation != 0.0 or feasible_objective != dp_instruction_bytes:
        raise AssertionError("reconstructed DP vector is not feasible in the captured MILP")

    no_presolve_kwargs = dict(milp_kwargs)
    no_presolve_kwargs["options"] = {"mip_rel_gap": 0.0, "presolve": False}
    no_presolve = original_milp(**no_presolve_kwargs)
    edge_count = len(edges)
    no_presolve_selected = tuple(
        candidate_tuple[index]
        for index, value in enumerate(no_presolve.x[edge_count:])
        if value > 0.5
    )
    no_presolve_table = build_custom_table(
        no_presolve_selected, arguments.physical_slots
    )
    no_presolve_encoding = encode_file(
        windows,
        source,
        target,
        table=no_presolve_table,
        physical_slots=arguments.physical_slots,
    )
    no_presolve_dp_bytes = sum(
        window.instruction_length for window in no_presolve_encoding.windows
    )
    if int(round(no_presolve.fun)) != no_presolve_dp_bytes:
        raise AssertionError("no-presolve solution does not replay in the independent DP")
    result = {
        "format": "vcdiff-fixed-q-optimizer-counterexample-v1",
        "pair_id": pair["id"],
        "category": pair["category"],
        "project": pair["project"],
        "artifact_lock_sha256": sha256(LOCK),
        "optimizer_path": lock["optimizer"]["optimizer_path"],
        "optimizer_sha256": sha256(ROOT / lock["optimizer"]["optimizer_path"]),
        "trace_path": str(trace_path.relative_to(ROOT)),
        "trace_sha256": sha256(trace_path),
        "source_sha256": pair["source"]["sha256"],
        "target_sha256": pair["target"]["sha256"],
        "logical_instruction_count": sum(
            len(window.instructions) for window in windows
        ),
        "observed_candidate_count": len(candidates),
        "physical_slots": arguments.physical_slots,
        "selected_patterns": [value.to_dict() for value in solver.selected],
        "selected_table_sha256": hashlib.sha256(table_to_bytes(table)).hexdigest(),
        "milp_instruction_primal": solver.instruction_bytes,
        "milp_instruction_dual": solver.solver_dual_bound,
        "milp_reported_gap": solver.solver_gap,
        "independent_dp_instruction_bytes": dp_instruction_bytes,
        "dp_beats_claimed_lower_bound_by_bytes": solver.instruction_bytes
        - dp_instruction_bytes,
        "captured_milp_feasible_vector": {
            "objective_instruction_bytes": feasible_objective,
            "maximum_constraint_violation": max_violation,
            "nonzero_variables": int(np.count_nonzero(feasible)),
        },
        "same_model_without_highs_presolve": {
            "instruction_primal": int(round(no_presolve.fun)),
            "instruction_dual": int(round(no_presolve.mip_dual_bound)),
            "reported_gap": float(no_presolve.mip_gap),
            "selected_patterns": [value.to_dict() for value in no_presolve_selected],
            "independent_dp_instruction_bytes": no_presolve_dp_bytes,
        },
        "emitted_patch_bytes": len(encoding.encoded),
        "status": "optimizer exactness invariant violated; pair has no accepted exact certificate",
        "replay_command": (
            "PYTHONPATH=src python3 benchmark/capture_optimizer_counterexample.py "
            f"--pair-id {pair['id']} --physical-slots {arguments.physical_slots}"
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / f"{pair['id']}-q{arguments.physical_slots}.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(destination)
    print(
        f"MILP={solver.instruction_bytes} DP={dp_instruction_bytes} "
        f"difference={solver.instruction_bytes - dp_instruction_bytes}"
    )


if __name__ == "__main__":
    main()
