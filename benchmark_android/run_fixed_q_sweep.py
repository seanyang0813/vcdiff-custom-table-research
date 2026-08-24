#!/usr/bin/env python3
"""Run independent fixed-q integer-dual jobs with bounded concurrency."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RUN_ONE = ROOT / "benchmark_android/run_fixed_q_integer_dual.py"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--first-q", type=int, default=1)
    parser.add_argument("--last-q", type=int, default=93)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--time-limit-seconds", type=float, default=600.0)
    parser.add_argument("--bound-only", action="store_true")
    arguments = parser.parse_args()
    if not 1 <= arguments.first_q <= arguments.last_q <= 93:
        raise ValueError("q range must lie in 1..93")
    if not 1 <= arguments.workers <= 4:
        raise ValueError("workers must lie in 1..4 for the host memory policy")
    arguments.output_root.mkdir(parents=True, exist_ok=True)
    log_directory = arguments.output_root / "logs"
    log_directory.mkdir(exist_ok=True)
    status_path = arguments.output_root / "sweep-status.json"
    q_values = list(range(arguments.last_q, arguments.first_q - 1, -1))
    started = time.monotonic()
    statuses: dict[int, dict[str, object]] = {}

    def write_status() -> None:
        document = {
            "format": "vcdiff-fixed-q-integer-dual-sweep-status-v1",
            "trace": str(arguments.trace),
            "q_range": [arguments.first_q, arguments.last_q],
            "workers": arguments.workers,
            "elapsed_seconds": time.monotonic() - started,
            "counts": {
                label: sum(
                    value.get("status") == label for value in statuses.values()
                )
                for label in (
                    "exact",
                    "exact_lower_bound",
                    "failed",
                    "skipped_existing",
                )
            },
            "jobs": {str(q): statuses[q] for q in sorted(statuses)},
        }
        status_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

    def run_one(q: int) -> tuple[int, dict[str, object]]:
        output = arguments.output_root / f"{q:03d}"
        result = output / "result.json"
        lower_bound = output / "lower-bound.json"
        if arguments.bound_only and lower_bound.is_file():
            value = json.loads(lower_bound.read_text())
            if (
                value.get("status") == "exact_lower_bound_only"
                and int(value.get("physical_slots", -1)) == q
            ):
                return q, {
                    "status": "skipped_existing",
                    "lower_bound": str(lower_bound),
                }
        if result.is_file():
            value = json.loads(result.read_text())
            if (
                value.get("status") == "exact_fixed_q_only"
                and int(value.get("physical_slots", -1)) == q
            ):
                return q, {
                    "status": "skipped_existing",
                    "result": str(result),
                }
        command = [
            sys.executable,
            str(RUN_ONE),
            "--trace",
            str(arguments.trace),
            "--physical-slots",
            str(q),
            "--output",
            str(output),
            "--time-limit-seconds",
            str(arguments.time_limit_seconds),
        ]
        if arguments.bound_only:
            command.append("--bound-only")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = f"{ROOT / 'src'}:{ROOT}"
        job_started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        elapsed = time.monotonic() - job_started
        log = log_directory / f"q-{q:03d}.log"
        log.write_text(completed.stdout)
        if completed.returncode == 0 and result.is_file():
            return q, {
                "status": "exact",
                "elapsed_seconds": elapsed,
                "result": str(result),
                "log": str(log),
            }
        if completed.returncode == 0 and lower_bound.is_file():
            return q, {
                "status": "exact_lower_bound",
                "elapsed_seconds": elapsed,
                "lower_bound": str(lower_bound),
                "log": str(log),
            }
        return q, {
            "status": "failed",
            "elapsed_seconds": elapsed,
            "returncode": completed.returncode,
            "log": str(log),
        }

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=arguments.workers
    ) as executor:
        future_to_q = {executor.submit(run_one, q): q for q in q_values}
        for future in concurrent.futures.as_completed(future_to_q):
            q, status = future.result()
            statuses[q] = status
            write_status()
            print(f"q={q}: {status['status']}", flush=True)
    write_status()
    print(status_path)


if __name__ == "__main__":
    main()
