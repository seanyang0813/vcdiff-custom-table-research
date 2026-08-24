#!/usr/bin/env python3
"""Record a trace-replayed pair skipped by the post-hoc host scaling gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
STATE = ROOT / "benchmark_android/work/oracle-state-v1.json"
GATE = ROOT / "results/android/rational-dual-scaling-gate-v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--trace-preparation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--update-state", action="store_true")
    arguments = parser.parse_args()

    corpus = json.loads(CORPUS.read_text())
    if arguments.pair_id not in {pair["pair_id"] for pair in corpus["pairs"]}:
        raise ValueError("pair is not in the frozen Android corpus")
    gate = json.loads(GATE.read_text())
    if gate.get("status") != "posthoc_operational_policy_active":
        raise ValueError("scaling gate is not active")
    cutoff = int(gate["trace_instruction_cutoff"])
    preparation = json.loads(arguments.trace_preparation.read_text())
    if not (
        preparation.get("pair_id") == arguments.pair_id
        and preparation.get("status") == "stock_trace_byte_replayed"
        and preparation.get("python_decoder_round_trip") is True
    ):
        raise ValueError("trace preparation is not an exact stock replay for this pair")
    logical_instructions = int(preparation["logical_instruction_count"])
    if logical_instructions < cutoff:
        raise ValueError(
            f"trace has {logical_instructions} instructions, below cutoff {cutoff}"
        )
    trace_path = Path(preparation["trace_path"])
    if not trace_path.is_absolute():
        trace_path = ROOT / trace_path
    if sha256(trace_path) != preparation["trace_sha256"]:
        raise ValueError("prepared trace hash drift")
    baseline_path = arguments.trace_preparation.parent / "baseline-xdelta3.vcdiff"
    if (
        baseline_path.stat().st_size != int(preparation["baseline_bytes"])
        or sha256(baseline_path) != preparation["baseline_sha256"]
    ):
        raise ValueError("prepared baseline patch drift")

    relative_gate = str(GATE.relative_to(ROOT))
    result = {
        "format": "vcdiff-android-posthoc-scaling-gate-skip-v1",
        "pair_id": arguments.pair_id,
        "status": "solver_skipped_by_posthoc_scaling_gate",
        "logical_instructions": logical_instructions,
        "baseline_bytes": int(preparation["baseline_bytes"]),
        "trace_sha256": preparation["trace_sha256"],
        "scaling_gate": relative_gate,
        "evidence_boundary": (
            "The stock trace was exactly byte-replayed, but no q=93 solver was "
            "started and no exact lower bound or optimum is claimed. This is a "
            f"post-hoc host resource skip under {relative_gate}."
        ),
    }
    write_json(arguments.output, result)

    if arguments.update_state:
        state = json.loads(STATE.read_text())
        state["pairs"][arguments.pair_id] = {
            "status": result["status"],
            "baseline_bytes": result["baseline_bytes"],
            "logical_instructions": logical_instructions,
            "diagnostic": str(arguments.output.resolve().relative_to(ROOT)),
        }
        write_json(STATE, state)
    print(arguments.output)


if __name__ == "__main__":
    main()
