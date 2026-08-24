#!/usr/bin/env python3
"""Run frozen Android DEX pairs serially with fail-visible accounting."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
EXECUTION = ROOT / "benchmark_android/execution-lock-v1.json"
EXECUTION_HASH = ROOT / "benchmark_android/execution-lock-v1.sha256"
OUTPUT = ROOT / "benchmark_android/artifacts"
WORK = ROOT / "benchmark_android/work"
STATE = WORK / "oracle-state-v1.json"
PYTHON = ROOT / "benchmark_work/scip-conda/bin/python"
STUDY = ROOT / "benchmark_android/run_study.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state() -> dict[str, Any]:
    if STATE.is_file():
        return json.loads(STATE.read_text())
    return {"format": "vcdiff-public-android-oracle-state-v1", "pairs": {}}


def update(pair_id: str, value: dict[str, Any]) -> None:
    current = state()
    current["pairs"][pair_id] = value
    WORK.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, STATE)


def peak_rss(log: Path) -> int | None:
    if not log.is_file():
        return None
    match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", log.read_text())
    return None if match is None else int(match.group(1))


def audit(pair: dict[str, Any], path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("format") != "vcdiff-public-android-dex-certificate-v1-scip-exact":
        raise ValueError("wrong Android certificate format")
    android = value["android_study"]
    if android["pair_id"] != pair["pair_id"] or android["corpus_lock_sha256"] != sha256(CORPUS):
        raise ValueError("Android corpus identity mismatch")
    proof = value["tools"]["independent_integer_proof"]
    for call in proof["calls"]:
        if not call["exact_mode"] or int(call["objective"]) != int(call["best_bound"]):
            raise ValueError("non-exact SCIP call")
    optimum = value["global_optimum"]
    solver = optimum["solver"]
    if not (
        int(optimum["file_bytes"])
        == int(solver["patch_bytes"])
        == int(solver["patch_dual_bound"])
    ):
        raise ValueError("patch primal/dual mismatch")
    target_hash = pair["new"]["bundle"]["sha256"]
    verification = value["verification"]
    if verification["independent_python_decoder"]["decoded_sha256"] != target_hash:
        raise ValueError("Python decoder mismatch")
    historical = verification["unchanged_xdelta_decoder"]
    if historical["returncode"] != 0 or historical["decoded_sha256"] != target_hash:
        raise ValueError("historical decoder mismatch")
    baseline = int(value["baseline"]["size"])
    oracle = int(optimum["file_bytes"])
    return {
        "status": "complete",
        "certificate": str(path.relative_to(ROOT)),
        "certificate_sha256": sha256(path),
        "baseline_bytes": baseline,
        "oracle_bytes": oracle,
        "saving_bytes": baseline - oracle,
        "saving_percent": 100.0 * (baseline - oracle) / baseline,
        "physical_slots": int(optimum["physical_slots"]),
        "logical_instructions": int(value["trace"]["instruction_count"]),
        "global_nodes": int(proof["calls"][-1]["nodes"]),
        "global_mps_sha256": proof["calls"][-1]["mps_sha256"],
    }


def run(pair: dict[str, Any], rerun: bool) -> dict[str, Any]:
    pair_id = pair["pair_id"]
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
        "--pair-id", pair_id, "--output", str(output),
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
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=14_700,
                check=False,
            )
        status = "completed_process" if completed.returncode == 0 else "failed"
        returncode: int | None = completed.returncode
    except subprocess.TimeoutExpired:
        status, returncode = "external_timeout", None
    elapsed = time.monotonic() - began
    if status != "completed_process":
        result = {
            "status": status,
            "returncode": returncode,
            "started_utc": started,
            "elapsed_seconds": elapsed,
            "peak_rss_kb": peak_rss(log),
            "log": str(log.relative_to(ROOT)),
        }
        update(pair_id, result)
        return result
    try:
        result = audit(pair, certificate)
    except Exception as error:
        result = {
            "status": "audit_failed",
            "error": repr(error),
            "started_utc": started,
            "elapsed_seconds": elapsed,
            "peak_rss_kb": peak_rss(log),
            "log": str(log.relative_to(ROOT)),
        }
        update(pair_id, result)
        return result
    result.update(
        {
            "reused": False,
            "started_utc": started,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "peak_rss_kb": peak_rss(log),
            "log": str(log.relative_to(ROOT)),
        }
    )
    update(pair_id, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--continue-after-failure", action="store_true")
    arguments = parser.parse_args()
    if EXECUTION_HASH.read_text().split()[0] != sha256(EXECUTION):
        raise ValueError("Android execution lock drift")
    execution = json.loads(EXECUTION.read_text())
    runner = execution["locked_inputs"]["corpus_runner"]
    if sha256(ROOT / runner["path"]) != runner["sha256"]:
        raise ValueError("Android corpus runner drift")
    corpus = json.loads(CORPUS.read_text())
    by_id = {pair["pair_id"]: pair for pair in corpus["pairs"]}
    schedule = execution["schedule"]
    selected = set(arguments.pair)
    ids = [pair_id for pair_id in schedule if not selected or pair_id in selected]
    if selected - set(ids):
        raise ValueError(f"unknown pair ids: {sorted(selected - set(ids))}")
    if arguments.limit is not None:
        ids = ids[: arguments.limit]
    for pair_id in ids:
        result = run(by_id[pair_id], arguments.rerun)
        print(pair_id, json.dumps(result, sort_keys=True), flush=True)
        if result["status"] != "complete" and not arguments.continue_after_failure:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
