#!/usr/bin/env python3
"""Diagnose the exact lower-bound-plus-attainment path on one frozen DEX pair."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import vcdiff_opt.optimizer as optimizer
from benchmark.scip_exact_adapter import ScipExactAdapter
from vcdiff_opt.study import run_study


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
OUTPUT_ROOT = ROOT / "benchmark_android/diagnostics/continuous-relaxation-v1"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    arguments = parser.parse_args()
    corpus = json.loads(CORPUS.read_text())
    pair = next(value for value in corpus["pairs"] if value["pair_id"] == arguments.pair_id)
    output = OUTPUT_ROOT / pair["pair_id"]
    adapter = ScipExactAdapter(
        scipy_no_presolve_hint=True,
        promote_all_binary=False,
        strengthen_activation_links=True,
        time_limit_seconds=7200.0,
        memory_limit_mb=6000.0,
    )
    original = optimizer.milp
    optimizer.milp = adapter
    try:
        certificate_path = run_study(
            ROOT / pair["old"]["bundle"]["path"],
            ROOT / pair["new"]["bundle"]["path"],
            output,
            trace_xdelta=TRACE_XDELTA,
            custom_table_decoder=DECODER,
            max_slots=1,
            global_max_slots=93,
        )
    finally:
        optimizer.milp = original
    certificate = json.loads(certificate_path.read_text())
    certificate["format"] = "vcdiff-android-continuous-relaxation-diagnostic-v1"
    certificate["diagnostic"] = {
        "pair_id": pair["pair_id"],
        "corpus_lock_sha256": sha256(CORPUS),
        "adapter_sha256": sha256(ROOT / "benchmark/scip_exact_adapter.py"),
        "path_variables": "continuous in [0,1]",
        "selection_q_varint_variables": "binary",
        "activation_links": True,
        "acceptance_logic": (
            "the exact relaxed optimum is a lower bound on the intended binary model; "
            "run_study emits a result only if the independently integral selected-table "
            "DP and serialized patch attain that same bound"
        ),
        "calls": [call.__dict__ for call in adapter.calls],
        "evidence_boundary": (
            "diagnostic only; cannot label any new corpus result until independently "
            "validated and frozen as a protocol amendment"
        ),
    }
    certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    print(certificate_path)


if __name__ == "__main__":
    main()
