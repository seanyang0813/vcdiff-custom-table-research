#!/usr/bin/env python3
"""Run the frozen exact-oracle corpus, resumably and without pair selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
LOCK_HASH = ROOT / "benchmark/artifact-lock-v1.sha256"
ANALYSIS = ROOT / "benchmark/analysis-spec-v1.json"
ANALYSIS_HASH = ROOT / "benchmark/analysis-spec-v1.sha256"
OUTPUT = ROOT / "benchmark_artifacts"
LOGS = ROOT / "benchmark_work/oracle-logs"
STATE = ROOT / "benchmark_work/oracle-state.json"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"
CUSTOM_DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"
STATE_MUTEX = threading.Lock()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash_file(path: Path, expected_target: Path) -> str:
    expected = path.read_text().split()[0]
    actual = sha256(expected_target)
    if actual != expected:
        raise ValueError(f"lock drift for {expected_target}: {actual} != {expected}")
    return actual


def read_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {"format": "vcdiff-generality-oracle-state-v1", "pairs": {}}
    return json.loads(STATE.read_text())


def write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, STATE)


def update_state(pair_id: str, values: dict[str, Any]) -> None:
    with STATE_MUTEX:
        state = read_state()
        state["pairs"][pair_id] = values
        write_state(state)


def audit_certificate(pair: dict[str, Any], certificate_path: Path) -> dict[str, Any]:
    certificate = json.loads(certificate_path.read_text())
    if certificate.get("format") != "vcdiff-custom-table-certificate-v2":
        raise ValueError(f"unexpected certificate format for {pair['id']}")
    for side in ("source", "target"):
        if certificate[side]["sha256"] != pair[side]["sha256"]:
            raise ValueError(f"{side} hash mismatch for {pair['id']}")
        if int(certificate[side]["size"]) != int(pair[side]["size"]):
            raise ValueError(f"{side} size mismatch for {pair['id']}")
    chosen = certificate["global_optimum"]
    solver = chosen["solver"]
    patch_bytes = int(chosen["file_bytes"])
    if float(solver["solver_gap"]) != 0.0:
        raise ValueError(f"nonzero solver gap for {pair['id']}")
    if not (
        patch_bytes
        == int(solver["patch_bytes"])
        == int(solver["patch_dual_bound"])
    ):
        raise ValueError(f"primal/dual/emitted patch mismatch for {pair['id']}")
    if patch_bytes > int(certificate["baseline"]["size"]):
        raise ValueError(f"global optimum grew versus included q=0 for {pair['id']}")
    verification = certificate["verification"]
    if verification["independent_python_decoder"]["decoded_sha256"] != pair["target"]["sha256"]:
        raise ValueError(f"Python decoder mismatch for {pair['id']}")
    historical = verification["unchanged_xdelta_decoder"]
    if int(historical["returncode"]) != 0 or historical["decoded_sha256"] != pair["target"]["sha256"]:
        raise ValueError(f"historical decoder mismatch for {pair['id']}")
    return {
        "certificate": str(certificate_path.relative_to(ROOT)),
        "certificate_sha256": sha256(certificate_path),
        "baseline_bytes": int(certificate["baseline"]["size"]),
        "oracle_bytes": patch_bytes,
        "physical_slots": int(chosen["physical_slots"]),
        "solver_gap": float(solver["solver_gap"]),
        "trace_xdelta_sha256": certificate["tools"]["trace_xdelta"]["binary_sha256"],
        "historical_decoder_sha256": certificate["tools"]["unchanged_custom_table_decoder"]["binary_sha256"],
        "status": "complete",
    }


def run_pair(pair: dict[str, Any], rerun: bool) -> tuple[str, dict[str, Any]]:
    pair_id = pair["id"]
    output = OUTPUT / pair_id
    certificate_path = output / "certificate.json"
    if certificate_path.is_file() and not rerun:
        result = audit_certificate(pair, certificate_path)
        result["reused"] = True
        update_state(pair_id, result)
        return pair_id, result

    started = datetime.now(timezone.utc).isoformat()
    update_state(pair_id, {"status": "running", "started_utc": started})
    output.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{pair_id}.log"
    command = [
        sys.executable,
        "-m",
        "vcdiff_opt.cli",
        "study",
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
            "PYTHONPATH": str(ROOT / "src"),
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
    return pair_id, result


def main() -> None:
    global STATE
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--state-path", type=Path)
    arguments = parser.parse_args()
    if arguments.state_path is not None:
        candidate_state = arguments.state_path.resolve()
        state_root = (ROOT / "benchmark_work").resolve()
        if state_root not in candidate_state.parents:
            raise ValueError("alternate state path must be beneath benchmark_work")
        STATE = candidate_state
    if arguments.workers < 1:
        raise ValueError("workers must be positive")
    verify_hash_file(LOCK_HASH, LOCK)
    verify_hash_file(ANALYSIS_HASH, ANALYSIS)
    lock = json.loads(LOCK.read_text())
    analysis = json.loads(ANALYSIS.read_text())
    optimizer = ROOT / lock["optimizer"]["optimizer_path"]
    if sha256(optimizer) != lock["optimizer"]["optimizer_sha256"]:
        raise ValueError("frozen optimizer drift")
    if analysis["locks"]["artifact_lock_sha256"] != sha256(LOCK):
        raise ValueError("analysis/artifact lock mismatch")
    for executable in (TRACE_XDELTA, CUSTOM_DECODER):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise FileNotFoundError(executable)
    for name, metadata in lock["artifacts"].items():
        artifact = ROOT / name
        if artifact.stat().st_size != metadata["size"] or sha256(artifact) != metadata["sha256"]:
            raise ValueError(f"frozen artifact drift: {name}")

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
    print(f"running {len(pairs)} frozen pairs with {arguments.workers} worker(s)", flush=True)
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
        futures = {
            executor.submit(run_pair, pair, arguments.rerun): pair["id"]
            for pair in pairs
        }
        for future in as_completed(futures):
            pair_id = futures[future]
            try:
                _, result = future.result()
                print(
                    f"complete {pair_id}: {result['baseline_bytes']} -> "
                    f"{result['oracle_bytes']} bytes q={result['physical_slots']} "
                    f"elapsed={result.get('elapsed_seconds', 0):.1f}s",
                    flush=True,
                )
            except Exception as error:  # continue to preserve all independent runs
                failures.append(pair_id)
                print(f"FAILED {pair_id}: {error}", file=sys.stderr, flush=True)
    if failures:
        raise SystemExit(f"{len(failures)} pair(s) failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
