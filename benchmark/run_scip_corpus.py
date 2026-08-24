#!/usr/bin/env python3
"""Run the frozen corpus serially under the exact-SCIP amendment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
AMENDMENT = ROOT / "benchmark/scip-validity-amendment-v2.json"
AMENDMENT_HASH = ROOT / "benchmark/scip-validity-amendment-v2.sha256"
OUTPUT = ROOT / "benchmark_artifacts_scip"
WORK = ROOT / "benchmark_work/scip-oracle"
STATE = WORK / "state-v1.json"
PYTHON = ROOT / "benchmark_work/scip-conda/bin/python"
STUDY = ROOT / "benchmark/run_scip_study.py"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_state() -> dict[str, Any]:
    if STATE.is_file():
        return json.loads(STATE.read_text())
    return {"format": "vcdiff-scip-exact-corpus-state-v1", "pairs": {}}


def write_state(state: dict[str, Any]) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, STATE)


def update(pair_id: str, value: dict[str, Any]) -> None:
    state = read_state()
    state["pairs"][pair_id] = value
    write_state(state)


def verify_file(parent: Path, name: str, expected: str) -> None:
    path = parent / name
    if not path.is_file() or sha256(path) != expected:
        raise ValueError(f"artifact mismatch: {path}")


def audit(pair: dict[str, Any], certificate_path: Path) -> dict[str, Any]:
    value = json.loads(certificate_path.read_text())
    pair_id = pair["id"]
    if value.get("format") != "vcdiff-custom-table-certificate-v4-scip-exact":
        raise ValueError(f"wrong certificate format for {pair_id}")
    amendment_sha = AMENDMENT_HASH.read_text().split()[0]
    if value["validity_amendment"]["sha256"] != amendment_sha:
        raise ValueError(f"amendment mismatch for {pair_id}")
    for side in ("source", "target"):
        if value[side]["sha256"] != pair[side]["sha256"]:
            raise ValueError(f"{side} hash mismatch for {pair_id}")
    proof = value["tools"]["independent_integer_proof"]
    if proof["api"] != "PySCIPOpt / SCIP numerically exact mode":
        raise ValueError(f"wrong proof backend for {pair_id}")
    calls = proof["calls"]
    if len(calls) != len(value["custom_evaluations"]) + 1:
        raise ValueError(f"proof call count mismatch for {pair_id}")
    for call in calls:
        if not call["exact_mode"] or int(call["objective"]) != int(call["best_bound"]):
            raise ValueError(f"invalid exact bound for {pair_id}")
        if call["returned_solution_source"] != "validated_scipy_no_presolve_hint":
            raise ValueError(f"unvalidated construction for {pair_id}")
        if int(call["threads"]) != 1:
            raise ValueError(f"nondeterministic thread count for {pair_id}")
    optimum = value["global_optimum"]
    solver = optimum["solver"]
    patch_bytes = int(optimum["file_bytes"])
    if not (
        patch_bytes
        == int(solver["patch_bytes"])
        == int(solver["patch_dual_bound"])
    ):
        raise ValueError(f"patch proof mismatch for {pair_id}")
    if patch_bytes > int(value["baseline"]["size"]):
        raise ValueError(f"oracle enlarged patch for {pair_id}")
    parent = certificate_path.parent
    verify_file(parent, "baseline-xdelta3.vcdiff", value["baseline"]["sha256"])
    verify_file(
        parent,
        "default-table-optimal.vcdiff",
        value["default_table_optimum"]["file_sha256"],
    )
    verify_file(parent, "trace.json", value["trace"]["sha256"])
    verify_file(parent, "restricted-optimal.vcdiff", optimum["file_sha256"])
    verify_file(parent, "restricted-parse.json", optimum["parse_sha256"])
    if optimum.get("table_sha256"):
        verify_file(parent, "restricted-code-table.bin", optimum["table_sha256"])
    target_hash = pair["target"]["sha256"]
    verification = value["verification"]
    if verification["independent_python_decoder"]["decoded_sha256"] != target_hash:
        raise ValueError(f"Python decode mismatch for {pair_id}")
    historical = verification["unchanged_xdelta_decoder"]
    if historical["returncode"] != 0 or historical["decoded_sha256"] != target_hash:
        raise ValueError(f"historical decode mismatch for {pair_id}")
    return {
        "status": "complete",
        "certificate": str(certificate_path.relative_to(ROOT)),
        "certificate_sha256": sha256(certificate_path),
        "baseline_bytes": int(value["baseline"]["size"]),
        "oracle_bytes": patch_bytes,
        "saving_bytes": int(value["baseline"]["size"]) - patch_bytes,
        "physical_slots": int(optimum["physical_slots"]),
        "proof_calls": len(calls),
        "global_nodes": int(calls[-1]["nodes"]),
        "global_mps_sha256": calls[-1]["mps_sha256"],
    }


def run_pair(pair: dict[str, Any], rerun: bool) -> dict[str, Any]:
    pair_id = pair["id"]
    output = OUTPUT / pair_id
    certificate = output / "certificate.json"
    if certificate.is_file() and not rerun:
        result = audit(pair, certificate)
        result["reused"] = True
        update(pair_id, result)
        return result
    output.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    log = WORK / f"{pair_id}.log"
    started = datetime.now(timezone.utc).isoformat()
    update(pair_id, {"status": "running", "started_utc": started})
    command = [
        "/usr/bin/time", "-v", str(PYTHON), str(STUDY),
        "--source", str(ROOT / pair["source"]["artifact"]),
        "--target", str(ROOT / pair["target"]["artifact"]),
        "--output", str(output),
        "--trace-xdelta", str(TRACE_XDELTA),
        "--custom-table-decoder", str(DECODER),
        "--max-slots", "1", "--global-max-slots", "93",
    ]
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
    )
    began = time.monotonic()
    try:
        with log.open("w") as handle:
            handle.write("$ " + " ".join(command) + "\n")
            handle.flush()
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=14_700,
                check=False,
            )
        returncode = completed.returncode
        status = "failed" if returncode else "completed_process"
    except subprocess.TimeoutExpired:
        returncode = None
        status = "external_timeout"
    elapsed = time.monotonic() - began
    if status != "completed_process":
        failure = {
            "status": status,
            "started_utc": started,
            "elapsed_seconds": elapsed,
            "returncode": returncode,
            "log": str(log.relative_to(ROOT)),
        }
        update(pair_id, failure)
        return failure
    try:
        result = audit(pair, certificate)
    except Exception as error:
        failure = {
            "status": "audit_failed",
            "started_utc": started,
            "elapsed_seconds": elapsed,
            "returncode": returncode,
            "error": repr(error),
            "log": str(log.relative_to(ROOT)),
        }
        update(pair_id, failure)
        return failure
    result.update(
        {
            "reused": False,
            "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "log": str(log.relative_to(ROOT)),
        }
    )
    update(pair_id, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--continue-after-failure", action="store_true")
    arguments = parser.parse_args()
    if AMENDMENT_HASH.read_text().split()[0] != sha256(AMENDMENT):
        raise ValueError("exact-SCIP amendment drift")
    amendment = json.loads(AMENDMENT.read_text())
    runner = amendment["proof_backend"]["corpus_runner"]
    if sha256(ROOT / runner["path"]) != runner["sha256"]:
        raise ValueError("exact-SCIP corpus runner drift")
    lock = json.loads(LOCK.read_text())
    selected = set(arguments.pair)
    pairs = [pair for pair in lock["pairs"] if not selected or pair["id"] in selected]
    missing = selected - {pair["id"] for pair in pairs}
    if missing:
        raise ValueError(f"unknown pair ids: {sorted(missing)}")
    for pair in pairs:
        result = run_pair(pair, arguments.rerun)
        print(pair["id"], json.dumps(result, sort_keys=True), flush=True)
        if result["status"] != "complete" and not arguments.continue_after_failure:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
