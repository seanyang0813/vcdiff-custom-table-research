#!/usr/bin/env python3
"""Freeze Android exact-oracle execution order and runners."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "benchmark_android/execution-lock-v1.json"
HASH_OUTPUT = ROOT / "benchmark_android/execution-lock-v1.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked(path: str) -> dict[str, str]:
    return {"path": path, "sha256": sha256(ROOT / path)}


def main() -> None:
    corpus = json.loads((ROOT / "benchmark_android/corpus-lock-v1.json").read_text())
    ordered = sorted(
        corpus["pairs"],
        key=lambda pair: (
            max(pair["old"]["bundle"]["size"], pair["new"]["bundle"]["size"]),
            pair["candidate_rank"],
            pair["pair_id"],
        ),
    )
    value = {
        "format": "vcdiff-public-android-execution-lock-v1",
        "registered_date": str(date.today()),
        "status": "locked before any frozen Android pair was traced or optimized",
        "locked_inputs": {
            "preregistration": locked("benchmark_android/preregistration-v1.json"),
            "corpus": locked("benchmark_android/corpus-lock-v1.json"),
            "scip_amendment": locked("benchmark/scip-validity-amendment-v2.json"),
            "scip_study_runner": locked("benchmark/run_scip_study.py"),
            "android_study_runner": locked("benchmark_android/run_study.py"),
            "corpus_runner": locked("benchmark_android/run_corpus.py"),
            "trace_binary": locked("build/xdelta/xdelta3-trace"),
            "historical_decoder": locked("build/xdelta/xdelta3-rfc-custom-decoder"),
        },
        "ordering": (
            "ascending max(old_bundle_bytes,new_bundle_bytes), then frozen candidate "
            "rank, then pair id; uses no VCDIFF trace or outcome"
        ),
        "schedule": [pair["pair_id"] for pair in ordered],
        "resource_and_failure_policy": (
            "locked exact-SCIP 6 GB and 7200 second per-model limits; serial execution; "
            "14700 second outer process limit; every non-complete status remains visible"
        ),
        "stop_policy": (
            "seek all 40; after at least 30 exact pairs, apply the preregistered signal "
            "gate. Do not substitute bounded results for exact labels."
        ),
    }
    OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    HASH_OUTPUT.write_text(f"{sha256(OUTPUT)}  {OUTPUT.relative_to(ROOT)}\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
