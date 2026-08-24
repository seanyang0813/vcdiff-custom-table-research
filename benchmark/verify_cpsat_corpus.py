#!/usr/bin/env python3
"""Independently replay every amended CP-SAT corpus certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import ortools

import vcdiff_opt.optimizer as optimizer
from benchmark.cpsat_adapter import BinaryCpSatAdapter
from vcdiff_opt.verify import verify_certificate


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
LOCK_HASH = ROOT / "benchmark/artifact-lock-v1.sha256"
AMENDMENT = ROOT / "benchmark/validity-amendment-v1.json"
AMENDMENT_HASH = ROOT / "benchmark/validity-amendment-v1.sha256"
CERTIFICATES = ROOT / "benchmark_artifacts_cpsat"
OUTPUT = ROOT / "results/generality/verification-cpsat-v1.json"
STATE = ROOT / "benchmark_work/verification-cpsat-state.json"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"
EXECUTION_DEVIATIONS = ROOT / "benchmark/execution-deviations.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash_file(hash_path: Path, target: Path) -> None:
    expected = hash_path.read_text().split()[0]
    actual = sha256(target)
    if actual != expected:
        raise ValueError(f"lock drift for {target}: {actual} != {expected}")


def read_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {"format": "vcdiff-cpsat-verification-state-v1", "pairs": {}}
    return json.loads(STATE.read_text())


def write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, STATE)


def replay(certificate_path: Path, amendment: dict[str, Any]) -> dict[str, Any]:
    certificate = json.loads(certificate_path.read_text())
    if certificate.get("format") != "vcdiff-custom-table-certificate-v3-cpsat":
        raise ValueError("not an amended CP-SAT certificate")
    if certificate["validity_amendment"]["sha256"] != sha256(AMENDMENT):
        raise ValueError("certificate refers to a different validity amendment")

    # The core verifier supports the unchanged v2 data schema. A temporary view
    # changes only its format discriminator; all artifact paths, hashes, claimed
    # bounds, selected patterns, parse ledger, and decoder checks remain intact.
    replay_document = dict(certificate)
    replay_document["format"] = "vcdiff-custom-table-certificate-v2"
    adapter = BinaryCpSatAdapter(
        workers=int(amendment["replacement_oracle"]["proof_solver_workers"]),
        scipy_no_presolve_hint=True,
    )
    original = optimizer.milp
    try:
        with tempfile.TemporaryDirectory(prefix="vcdiff-cpsat-verify-") as directory:
            replay_path = Path(directory) / "certificate-v2-view.json"
            replay_path.write_text(json.dumps(replay_document, sort_keys=True) + "\n")
            optimizer.milp = adapter
            result = verify_certificate(
                replay_path,
                custom_table_decoder=DECODER,
            )
    finally:
        optimizer.milp = original

    if len(adapter.calls) != 1:
        raise ValueError(f"expected one replay proof call, got {len(adapter.calls)}")
    call = adapter.calls[0]
    chosen = certificate["global_optimum"]
    solver = chosen["solver"]
    if not (
        call.objective
        == call.best_bound
        == int(solver["variable_patch_bytes"])
    ):
        raise ValueError("replayed CP-SAT objective differs from certificate")
    if call.returned_solution_source != "validated_scipy_no_presolve_hint":
        raise ValueError("replay did not return the validated deterministic construction")
    if not (
        result["status"] == "verified"
        and int(result["patch_primal"]) == int(result["patch_dual"])
        and int(result["patch_primal"]) == int(chosen["file_bytes"])
        and float(result["solver_gap"]) == 0.0
        and result["unchanged_decoder"]["returncode"] == 0
    ):
        raise ValueError("core replay checks failed")
    result["certificate"] = str(certificate_path)
    result["independent_integer_proof"] = {
        "api": "OR-Tools CP-SAT",
        "ortools_version": ortools.__version__,
        "workers": adapter.workers,
        "objective": call.objective,
        "best_bound": call.best_bound,
        "returned_solution_source": call.returned_solution_source,
        "variables": call.variables,
        "constraints": call.constraints,
        "nonzeros": call.nonzeros,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--pair", action="append", default=[])
    arguments = parser.parse_args()
    verify_hash_file(LOCK_HASH, LOCK)
    verify_hash_file(AMENDMENT_HASH, AMENDMENT)
    lock = json.loads(LOCK.read_text())
    amendment = json.loads(AMENDMENT.read_text())
    if sha256(ROOT / amendment["replacement_oracle"]["adapter_path"]) != amendment["replacement_oracle"]["adapter_sha256"]:
        raise ValueError("CP-SAT adapter drift")
    if sha256(ROOT / amendment["unchanged_scope"]["optimizer_path"]) != amendment["unchanged_scope"]["optimizer_sha256"]:
        raise ValueError("frozen optimizer drift")
    pairs = lock["pairs"]
    if arguments.pair:
        requested = set(arguments.pair)
        known = {pair["id"] for pair in pairs}
        if requested - known:
            raise ValueError(f"unknown pair IDs: {sorted(requested - known)}")
        pairs = [pair for pair in pairs if pair["id"] in requested]
    if not pairs:
        raise ValueError("selection contains no pairs")

    state = read_state()
    for number, pair in enumerate(pairs, 1):
        pair_id = pair["id"]
        certificate_path = CERTIFICATES / pair_id / "certificate.json"
        if not certificate_path.is_file():
            raise FileNotFoundError(certificate_path)
        certificate_hash = sha256(certificate_path)
        previous = state["pairs"].get(pair_id)
        if (
            not arguments.rerun
            and previous is not None
            and previous.get("status") == "verified"
            and previous.get("certificate_sha256") == certificate_hash
        ):
            print(f"[{number}/{len(pairs)}] reuse {pair_id}", flush=True)
            continue
        print(f"[{number}/{len(pairs)}] verify {pair_id}", flush=True)
        start = time.monotonic()
        result = replay(certificate_path, amendment)
        if result["decoded_sha256"] != pair["target"]["sha256"]:
            raise ValueError(f"target replay mismatch for {pair_id}")
        state["pairs"][pair_id] = {
            "status": "verified",
            "certificate": str(certificate_path.relative_to(ROOT)),
            "certificate_sha256": certificate_hash,
            "elapsed_seconds": time.monotonic() - start,
            "result": result,
        }
        write_state(state)

    selected_ids = {pair["id"] for pair in pairs}
    if not arguments.pair and set(state["pairs"]) != selected_ids:
        raise ValueError("verification state contains an unexpected pair set")
    if arguments.pair:
        print(f"verified {len(pairs)} selected certificate(s)")
        return
    ledger = {
        "format": "vcdiff-generality-cpsat-verification-ledger-v1",
        "artifact_lock_sha256": sha256(LOCK),
        "validity_amendment_sha256": sha256(AMENDMENT),
        "execution_deviations_sha256": sha256(EXECUTION_DEVIATIONS),
        "replay_decoder_sha256": sha256(DECODER),
        "pair_count": len(pairs),
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
