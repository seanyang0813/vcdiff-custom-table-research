#!/usr/bin/env python3
"""Certify an Android pair whose restricted table family has no candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import vcdiff_opt.optimizer as optimizer_module
from vcdiff_opt.codec import build_custom_table, encode_file, encode_file_header
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.model import ADD, Atom, Pattern, WindowTrace
from vcdiff_opt.optimizer import solve_global_selection


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
PREREG = ROOT / "benchmark_android/preregistration-v1.json"
EXECUTION = ROOT / "benchmark_android/execution-lock-v1.json"
STATE = ROOT / "benchmark_android/work/oracle-state-v1.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def verify_external_decoder(
    decoder: Path, source: Path, patch: Path, target: bytes
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vcdiff-zero-candidate-") as directory:
        decoded = Path(directory) / "decoded.bin"
        command = [
            str(decoder.resolve()),
            "-d",
            "-f",
            "-s",
            str(source.resolve()),
            str(patch.resolve()),
            str(decoded),
        ]
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"external decoder failed with {completed.returncode}: "
                f"{completed.stderr}"
            )
        value = decoded.read_bytes()
        if value != target:
            raise ValueError("external decoder output differs from the target")
        return {
            "command": [*command[:-1], "<temporary-output>"],
            "returncode": completed.returncode,
            "decoded_bytes": len(value),
            "decoded_sha256": sha256_bytes(value),
            "stderr": completed.stderr.strip(),
        }


def update_state(pair_id: str, value: dict[str, Any]) -> None:
    state = json.loads(STATE.read_text())
    state["pairs"][pair_id] = value
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, STATE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--custom-table-decoder", type=Path, required=True)
    parser.add_argument("--update-state", action="store_true")
    arguments = parser.parse_args()

    corpus = json.loads(CORPUS.read_text())
    pair = next(
        value
        for value in corpus["pairs"]
        if value["pair_id"] == arguments.pair_id
    )
    trace_document = json.loads(arguments.trace.read_text())
    windows = tuple(
        WindowTrace.from_dict(value) for value in trace_document["windows"]
    )
    if len(windows) != 1:
        raise ValueError("the structural proof requires one target window")

    source_path = Path(trace_document["source"]["path"])
    target_path = Path(trace_document["target"]["path"])
    baseline_path = Path(trace_document["baseline_patch"]["path"])
    source = source_path.read_bytes()
    target = target_path.read_bytes()
    if sha256_bytes(source) != pair["old"]["bundle"]["sha256"]:
        raise ValueError("source bundle does not match the frozen corpus")
    if sha256_bytes(target) != pair["new"]["bundle"]["sha256"]:
        raise ValueError("target bundle does not match the frozen corpus")

    default_encoding = encode_file(windows, source, target)
    if default_encoding.encoded != baseline_path.read_bytes():
        raise AssertionError("default-table replay differs from the stock patch")

    probe = Pattern((Atom(ADD, 255),))
    header_lengths = [len(encode_file_header()[0])]
    for q in range(1, 94):
        table = build_custom_table((probe,), q)
        header_lengths.append(len(encode_file_header(table, q)[0]))

    def reject_solver_call(**_: Any) -> Any:
        raise AssertionError("zero-candidate proof unexpectedly invoked a solver")

    original_milp = optimizer_module.milp
    optimizer_module.milp = reject_solver_call
    try:
        proof = solve_global_selection(
            windows[0],
            93,
            file_header_lengths=header_lengths,
            data_bytes=default_encoding.windows[0].data_length,
            address_bytes=default_encoding.windows[0].address_length,
        )
    finally:
        optimizer_module.milp = original_milp

    if not (
        proof.observed_candidate_count == 0
        and proof.candidate_count == 0
        and proof.model_variables == 0
        and proof.model_constraints == 0
        and proof.solver_nodes == 0
        and proof.physical_slots == 0
        and not proof.selected
        and proof.patch_bytes == proof.patch_dual_bound == len(default_encoding.encoded)
    ):
        raise AssertionError("pair does not satisfy the zero-candidate proof branch")
    if decode_file(default_encoding.encoded, source) != target:
        raise AssertionError("Python decoder rejected the attained patch")

    arguments.patch.parent.mkdir(parents=True, exist_ok=True)
    arguments.patch.write_bytes(default_encoding.encoded)
    external = verify_external_decoder(
        arguments.custom_table_decoder, source_path, arguments.patch, target
    )
    certificate = {
        "format": "vcdiff-android-zero-candidate-certificate-v1",
        "pair_id": arguments.pair_id,
        "frozen_inputs": {
            "preregistration_sha256": sha256(PREREG),
            "corpus_lock_sha256": sha256(CORPUS),
            "execution_lock_sha256": sha256(EXECUTION),
            "source_sha256": sha256_bytes(source),
            "target_sha256": sha256_bytes(target),
            "trace_sha256": sha256(arguments.trace),
        },
        "trace": {
            "logical_instruction_count": sum(
                len(window.instructions) for window in windows
            ),
            "stock_patch_byte_replayed": True,
        },
        "baseline": {
            "bytes": len(default_encoding.encoded),
            "sha256": sha256_bytes(default_encoding.encoded),
        },
        "exact_restricted_optimum": {
            "bytes": proof.patch_bytes,
            "physical_slots": proof.physical_slots,
            "sha256": sha256(arguments.patch),
        },
        "proof": {
            "kind": "exhaustive zero-candidate structural branch",
            "physical_slot_range": [0, 93],
            "solver_invoked": False,
            "global_result": proof.to_dict(),
            "argument": (
                "The frozen family may install only observed implicit-size single or "
                "pair patterns. This trace has none, so every q>0 table is infeasible "
                "under the family's nonempty-installation rule and q=0 is the sole "
                f"feasible table. The exact default-table dynamic program emits "
                f"{proof.patch_bytes} bytes and attains the structural lower bound."
            ),
        },
        "verification": {
            "python_decoder": {
                "decoded_bytes": len(target),
                "decoded_sha256": sha256_bytes(target),
            },
            "unchanged_xdelta_decoder": external,
        },
        "evidence_boundary": (
            "Exact only for the frozen logical trace and restricted canonical q=0..93 "
            "table family. The zero-candidate branch uses no MILP. This public Android "
            "DEX surrogate supports no Meta or Superpack claim."
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")

    if arguments.update_state:
        update_state(
            arguments.pair_id,
            {
                "status": "complete",
                "certificate": str(arguments.output.resolve().relative_to(ROOT)),
                "certificate_sha256": sha256(arguments.output),
                "baseline_bytes": proof.patch_bytes,
                "oracle_bytes": proof.patch_bytes,
                "saving_bytes": 0,
                "saving_percent": 0.0,
                "physical_slots": 0,
                "logical_instructions": sum(
                    len(window.instructions) for window in windows
                ),
                "proof_backend": "exhaustive zero-candidate structural branch; no MILP",
            },
        )
    print(arguments.output)


if __name__ == "__main__":
    main()
