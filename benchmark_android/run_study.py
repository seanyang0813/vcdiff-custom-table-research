#!/usr/bin/env python3
"""Run one frozen Android DEX pair through the locked exact-SCIP study."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PREREG = ROOT / "benchmark_android/preregistration-v1.json"
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
EXECUTION = ROOT / "benchmark_android/execution-lock-v1.json"
EXECUTION_HASH = ROOT / "benchmark_android/execution-lock-v1.sha256"
SCIP_STUDY = ROOT / "benchmark/run_scip_study.py"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if EXECUTION_HASH.read_text().split()[0] != sha256(EXECUTION):
        raise ValueError("Android execution lock drift")
    execution = json.loads(EXECUTION.read_text())
    for item in execution["locked_inputs"].values():
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"locked Android input drift: {item['path']}")
    corpus = json.loads(CORPUS.read_text())
    pair = next((value for value in corpus["pairs"] if value["pair_id"] == arguments.pair_id), None)
    if pair is None:
        raise ValueError(f"pair is not in frozen Android corpus: {arguments.pair_id}")
    arguments.output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(SCIP_STUDY),
        "--source", str(ROOT / pair["old"]["bundle"]["path"]),
        "--target", str(ROOT / pair["new"]["bundle"]["path"]),
        "--output", str(arguments.output),
        "--trace-xdelta", str(TRACE_XDELTA),
        "--custom-table-decoder", str(DECODER),
        "--max-slots", "1",
        "--global-max-slots", "93",
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = f"{ROOT / 'src'}:{ROOT}"
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    certificate_path = arguments.output / "certificate.json"
    certificate = json.loads(certificate_path.read_text())
    certificate["format"] = "vcdiff-public-android-dex-certificate-v1-scip-exact"
    certificate["android_study"] = {
        "preregistration_sha256": sha256(PREREG),
        "corpus_lock_sha256": sha256(CORPUS),
        "execution_lock_sha256": sha256(EXECUTION),
        "pair_id": pair["pair_id"],
        "package_id": pair["package_id"],
        "project_name": pair.get("project_name"),
        "source_code": pair["source_code"],
        "candidate_rank": pair["candidate_rank"],
        "old_release": pair["old"]["release"],
        "new_release": pair["new"]["release"],
        "old_dex_bundle": pair["old"]["bundle"],
        "new_dex_bundle": pair["new"]["bundle"],
        "evidence_boundary": (
            "public F-Droid DEX-bundle surrogate; no Meta/Superpack claim"
        ),
    }
    certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    print(certificate_path)


if __name__ == "__main__":
    main()
