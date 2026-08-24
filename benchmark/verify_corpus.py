#!/usr/bin/env python3
"""Replay every frozen confirmatory certificate and write an audit ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
OUTPUT = ROOT / "results/generality/verification-v1.json"
STATE = ROOT / "benchmark_work/verification-state.json"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"
EXECUTION_DEVIATIONS = ROOT / "benchmark/execution-deviations.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {"format": "vcdiff-generality-verification-state-v1", "pairs": {}}
    return json.loads(STATE.read_text())


def write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    state_path = STATE.with_suffix(".json.tmp")
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(state_path, STATE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true")
    arguments = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    state = read_state()
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    for number, pair in enumerate(lock["pairs"], 1):
        pair_id = pair["id"]
        certificate = ROOT / "benchmark_artifacts" / pair_id / "certificate.json"
        if not certificate.is_file():
            raise FileNotFoundError(certificate)
        certificate_sha256 = sha256(certificate)
        previous = state["pairs"].get(pair_id)
        if (
            not arguments.rerun
            and previous is not None
            and previous.get("status") == "verified"
            and previous.get("certificate_sha256") == certificate_sha256
        ):
            print(f"[{number}/48] reuse {pair_id}", flush=True)
            continue
        print(f"[{number}/48] verify {pair_id}", flush=True)
        start = time.monotonic()
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "vcdiff_opt.cli",
                "verify",
                "--certificate",
                str(certificate),
                "--custom-table-decoder",
                str(DECODER),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"verification failed for {pair_id}:\n{completed.stdout}\n{completed.stderr}"
            )
        result = json.loads(completed.stdout)
        if (
            result.get("status") != "verified"
            or int(result["patch_primal"]) != int(result["patch_dual"])
            or float(result["solver_gap"]) != 0.0
            or result["unchanged_decoder"]["returncode"] != 0
        ):
            raise ValueError(f"invalid replay result for {pair_id}")
        state["pairs"][pair_id] = {
            "status": "verified",
            "certificate": str(certificate.relative_to(ROOT)),
            "certificate_sha256": certificate_sha256,
            "elapsed_seconds": time.monotonic() - start,
            "result": result,
        }
        write_state(state)
    if set(state["pairs"]) != {pair["id"] for pair in lock["pairs"]}:
        raise ValueError("verification state contains an unexpected pair set")
    ledger = {
        "format": "vcdiff-generality-verification-ledger-v1",
        "artifact_lock_sha256": sha256(LOCK),
        "execution_deviations_sha256": sha256(EXECUTION_DEVIATIONS),
        "replay_decoder_sha256": sha256(DECODER),
        "pair_count": len(lock["pairs"]),
        "all_verified": all(
            value["status"] == "verified" for value in state["pairs"].values()
        ),
        "pairs": state["pairs"],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    print(f"verified {ledger['pair_count']} certificates")


if __name__ == "__main__":
    main()
