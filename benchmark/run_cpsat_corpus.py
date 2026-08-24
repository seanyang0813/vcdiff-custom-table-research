#!/usr/bin/env python3
"""Run the frozen 48-pair corpus under the locked CP-SAT amendment."""

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
LOCK_HASH = ROOT / "benchmark/artifact-lock-v1.sha256"
ANALYSIS = ROOT / "benchmark/analysis-spec-v1.json"
ANALYSIS_HASH = ROOT / "benchmark/analysis-spec-v1.sha256"
AMENDMENT = ROOT / "benchmark/validity-amendment-v1.json"
AMENDMENT_HASH = ROOT / "benchmark/validity-amendment-v1.sha256"
OUTPUT = ROOT / "benchmark_artifacts_cpsat"
LOGS = ROOT / "benchmark_work/cpsat-oracle-logs"
STATE = ROOT / "benchmark_work/cpsat-oracle-state.json"
PYTHON = ROOT / "benchmark_work/cpsat-venv/bin/python"
STUDY = ROOT / "benchmark/run_cpsat_study.py"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"
CUSTOM_DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash_file(hash_path: Path, target: Path) -> str:
    expected = hash_path.read_text().split()[0]
    actual = sha256(target)
    if actual != expected:
        raise ValueError(f"lock drift for {target}: {actual} != {expected}")
    return actual


def read_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {"format": "vcdiff-cpsat-oracle-state-v1", "pairs": {}}
    return json.loads(STATE.read_text())


def write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, STATE)


def update_state(pair_id: str, values: dict[str, Any]) -> None:
    state = read_state()
    state["pairs"][pair_id] = values
    write_state(state)


def verify_output_file(output: Path, name: str, expected_hash: str) -> None:
    path = output / name
    if not path.is_file() or sha256(path) != expected_hash:
        raise ValueError(f"output hash mismatch: {path}")


def audit_certificate(pair: dict[str, Any], certificate_path: Path) -> dict[str, Any]:
    certificate = json.loads(certificate_path.read_text())
    pair_id = pair["id"]
    if certificate.get("format") != "vcdiff-custom-table-certificate-v3-cpsat":
        raise ValueError(f"unexpected certificate format for {pair_id}")
    if certificate["validity_amendment"]["sha256"] != sha256(AMENDMENT):
        raise ValueError(f"validity amendment mismatch for {pair_id}")
    for side in ("source", "target"):
        if certificate[side]["sha256"] != pair[side]["sha256"]:
            raise ValueError(f"{side} hash mismatch for {pair_id}")
        if int(certificate[side]["size"]) != int(pair[side]["size"]):
            raise ValueError(f"{side} size mismatch for {pair_id}")

    proof = certificate["tools"]["independent_integer_proof"]
    if proof["api"] != "OR-Tools CP-SAT" or proof["status_required"] != "OPTIMAL":
        raise ValueError(f"wrong proof protocol for {pair_id}")
    if proof["ortools_version"] != "9.15.6755" or int(proof["workers"]) != 8:
        raise ValueError(f"wrong CP-SAT environment for {pair_id}")
    calls = proof["calls"]
    evaluations = certificate["custom_evaluations"]
    if len(calls) != len(evaluations) + 1:
        raise ValueError(f"proof call count mismatch for {pair_id}")
    for call in calls:
        if int(call["objective"]) != int(call["best_bound"]):
            raise ValueError(f"unequal CP-SAT primal/bound for {pair_id}")
        if call["returned_solution_source"] != "validated_scipy_no_presolve_hint":
            raise ValueError(f"unvalidated returned construction for {pair_id}")
    for evaluation, call in zip(evaluations, calls[:-1], strict=True):
        solver = evaluation["solver"]
        if float(solver["solver_gap"]) != 0.0:
            raise ValueError(f"nonzero fixed-q gap for {pair_id}")
        if not (
            int(solver["instruction_bytes"])
            == int(solver["solver_dual_bound"])
            == int(call["objective"])
        ):
            raise ValueError(f"fixed-q proof mismatch for {pair_id}")

    chosen = certificate["global_optimum"]
    solver = chosen["solver"]
    patch_bytes = int(chosen["file_bytes"])
    if float(solver["solver_gap"]) != 0.0:
        raise ValueError(f"nonzero global gap for {pair_id}")
    if not (
        patch_bytes
        == int(solver["patch_bytes"])
        == int(solver["patch_dual_bound"])
    ):
        raise ValueError(f"global primal/dual/emitted mismatch for {pair_id}")
    if int(solver["variable_patch_bytes"]) != int(calls[-1]["objective"]):
        raise ValueError(f"global CP-SAT objective mismatch for {pair_id}")
    if patch_bytes > int(certificate["baseline"]["size"]):
        raise ValueError(f"global optimum grew versus included q=0 for {pair_id}")

    output = certificate_path.parent
    verify_output_file(output, "baseline-xdelta3.vcdiff", certificate["baseline"]["sha256"])
    verify_output_file(output, "default-table-optimal.vcdiff", certificate["default_table_optimum"]["file_sha256"])
    verify_output_file(output, "trace.json", certificate["trace"]["sha256"])
    verify_output_file(output, "restricted-optimal.vcdiff", chosen["file_sha256"])
    verify_output_file(output, "restricted-parse.json", chosen["parse_sha256"])
    if chosen.get("table_sha256") is not None:
        verify_output_file(output, "restricted-code-table.bin", chosen["table_sha256"])

    target_hash = pair["target"]["sha256"]
    verification = certificate["verification"]
    if verification["independent_python_decoder"]["decoded_sha256"] != target_hash:
        raise ValueError(f"Python decoder mismatch for {pair_id}")
    historical = verification["unchanged_xdelta_decoder"]
    if int(historical["returncode"]) != 0 or historical["decoded_sha256"] != target_hash:
        raise ValueError(f"historical decoder mismatch for {pair_id}")
    return {
        "status": "complete",
        "certificate": str(certificate_path.relative_to(ROOT)),
        "certificate_sha256": sha256(certificate_path),
        "baseline_bytes": int(certificate["baseline"]["size"]),
        "oracle_bytes": patch_bytes,
        "physical_slots": int(chosen["physical_slots"]),
        "solver_gap": float(solver["solver_gap"]),
        "proof_calls": len(calls),
        "trace_xdelta_sha256": certificate["tools"]["trace_xdelta"]["binary_sha256"],
        "historical_decoder_sha256": certificate["tools"]["unchanged_custom_table_decoder"]["binary_sha256"],
    }


def run_pair(pair: dict[str, Any], rerun: bool) -> dict[str, Any]:
    pair_id = pair["id"]
    output = OUTPUT / pair_id
    certificate_path = output / "certificate.json"
    if certificate_path.is_file() and not rerun:
        result = audit_certificate(pair, certificate_path)
        result["reused"] = True
        update_state(pair_id, result)
        return result

    started = datetime.now(timezone.utc).isoformat()
    update_state(pair_id, {"status": "running", "started_utc": started})
    output.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{pair_id}.log"
    command = [
        str(PYTHON),
        str(STUDY),
        "--source",
        str(ROOT / pair["source"]["artifact"]),
        "--target",
        str(ROOT / pair["target"]["artifact"]),
        "--output",
        str(output),
        "--trace-xdelta",
        str(TRACE_XDELTA),
        "--custom-table-decoder",
        str(CUSTOM_DECODER),
        "--max-slots",
        "1",
        "--global-max-slots",
        "93",
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
    start_clock = time.monotonic()
    with log_path.open("w") as log:
        log.write("$ " + " ".join(command) + "\n")
        log.flush()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed = time.monotonic() - start_clock
    if completed.returncode != 0:
        failure = {
            "status": "failed",
            "started_utc": started,
            "elapsed_seconds": elapsed,
            "returncode": completed.returncode,
            "log": str(log_path.relative_to(ROOT)),
        }
        update_state(pair_id, failure)
        raise RuntimeError(f"study failed for {pair_id}; see {log_path}")
    result = audit_certificate(pair, certificate_path)
    result.update(
        {
            "reused": False,
            "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "log": str(log_path.relative_to(ROOT)),
        }
    )
    update_state(pair_id, result)
    return result


def verify_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_hash_file(LOCK_HASH, LOCK)
    verify_hash_file(ANALYSIS_HASH, ANALYSIS)
    verify_hash_file(AMENDMENT_HASH, AMENDMENT)
    lock = json.loads(LOCK.read_text())
    amendment = json.loads(AMENDMENT.read_text())
    if sha256(ROOT / lock["optimizer"]["optimizer_path"]) != lock["optimizer"]["optimizer_sha256"]:
        raise ValueError("frozen optimizer drift")
    if amendment["unchanged_scope"]["artifact_lock_sha256"] != sha256(LOCK):
        raise ValueError("amendment/artifact lock mismatch")
    if amendment["unchanged_scope"]["analysis_spec_sha256"] != sha256(ANALYSIS):
        raise ValueError("amendment/analysis lock mismatch")
    if sha256(ROOT / amendment["replacement_oracle"]["adapter_path"]) != amendment["replacement_oracle"]["adapter_sha256"]:
        raise ValueError("CP-SAT adapter drift")
    if sha256(ROOT / amendment["replacement_oracle"]["requirements_path"]) != amendment["replacement_oracle"]["requirements_sha256"]:
        raise ValueError("CP-SAT requirements drift")
    for executable in (PYTHON, STUDY, TRACE_XDELTA, CUSTOM_DECODER):
        if not executable.is_file() or (executable != STUDY and not os.access(executable, os.X_OK)):
            raise FileNotFoundError(executable)
    for name, metadata in lock["artifacts"].items():
        artifact = ROOT / name
        if artifact.stat().st_size != metadata["size"] or sha256(artifact) != metadata["sha256"]:
            raise ValueError(f"frozen artifact drift: {name}")
    return lock, amendment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rerun", action="store_true")
    arguments = parser.parse_args()
    lock, _ = verify_frozen_inputs()
    pairs = lock["pairs"]
    if arguments.pair:
        requested = set(arguments.pair)
        known = {pair["id"] for pair in pairs}
        if requested - known:
            raise ValueError(f"unknown pair IDs: {sorted(requested - known)}")
        pairs = [pair for pair in pairs if pair["id"] in requested]
    if arguments.category:
        pairs = [pair for pair in pairs if pair["category"] in arguments.category]
    if arguments.split:
        pairs = [pair for pair in pairs if pair["split"] in arguments.split]
    if arguments.limit is not None:
        pairs = pairs[: arguments.limit]
    if not pairs:
        raise ValueError("selection contains no pairs")

    print(f"running {len(pairs)} frozen pairs serially under the CP-SAT amendment", flush=True)
    for index, pair in enumerate(pairs, start=1):
        try:
            result = run_pair(pair, arguments.rerun)
        except Exception:
            print(f"FAILED {pair['id']}; fail-fast amendment stops the run", flush=True)
            raise
        print(
            f"[{index}/{len(pairs)}] complete {pair['id']}: "
            f"{result['baseline_bytes']} -> {result['oracle_bytes']} bytes "
            f"q={result['physical_slots']} elapsed={result.get('elapsed_seconds', 0):.1f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
