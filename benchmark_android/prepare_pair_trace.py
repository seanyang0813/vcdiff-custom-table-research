#!/usr/bin/env python3
"""Generate and byte-replay the frozen stock trace for one Android pair."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from vcdiff_opt.codec import encode_file
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.trace import run_xdelta_trace, trace_document


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
EXECUTION = ROOT / "benchmark_android/execution-lock-v1.json"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    execution = json.loads(EXECUTION.read_text())
    if arguments.pair_id not in execution["schedule"]:
        raise ValueError("pair is not in the frozen execution schedule")
    for item in execution["locked_inputs"].values():
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"locked Android input drift: {item['path']}")
    corpus = json.loads(CORPUS.read_text())
    pair = next(
        value for value in corpus["pairs"] if value["pair_id"] == arguments.pair_id
    )
    source = ROOT / pair["old"]["bundle"]["path"]
    target = ROOT / pair["new"]["bundle"]["path"]
    if sha256(source) != pair["old"]["bundle"]["sha256"]:
        raise ValueError("frozen source bundle hash mismatch")
    if sha256(target) != pair["new"]["bundle"]["sha256"]:
        raise ValueError("frozen target bundle hash mismatch")
    arguments.output.mkdir(parents=True, exist_ok=True)
    baseline = arguments.output / "baseline-xdelta3.vcdiff"
    windows, completed = run_xdelta_trace(
        TRACE_XDELTA,
        source,
        target,
        baseline,
        window_size=max(16 * 1024, target.stat().st_size),
    )
    if len(windows) != 1:
        raise ValueError(f"expected one trace window, got {len(windows)}")
    trace_path = arguments.output / "trace.json"
    trace_path.write_text(
        json.dumps(
            trace_document(source, target, baseline, windows),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    source_bytes = source.read_bytes()
    target_bytes = target.read_bytes()
    default_encoding = encode_file(windows, source_bytes, target_bytes)
    if default_encoding.encoded != baseline.read_bytes():
        raise AssertionError("logical trace does not reproduce the stock patch")
    if decode_file(default_encoding.encoded, source_bytes) != target_bytes:
        raise AssertionError("Python decoder rejected the stock replay")
    default_path = arguments.output / "default-table-optimal.vcdiff"
    default_path.write_bytes(default_encoding.encoded)
    result = {
        "format": "vcdiff-android-pair-trace-preparation-v1",
        "status": "stock_trace_byte_replayed",
        "pair_id": pair["pair_id"],
        "trace_path": str(trace_path),
        "trace_sha256": sha256(trace_path),
        "logical_instruction_count": sum(
            len(window.instructions) for window in windows
        ),
        "baseline_bytes": len(default_encoding.encoded),
        "baseline_sha256": sha256(baseline),
        "data_bytes": sum(window.data_length for window in default_encoding.windows),
        "instruction_bytes": sum(
            window.instruction_length for window in default_encoding.windows
        ),
        "address_bytes": sum(
            window.address_length for window in default_encoding.windows
        ),
        "trace_command": completed.args,
        "trace_returncode": completed.returncode,
        "python_decoder_round_trip": True,
    }
    result_path = arguments.output / "trace-preparation.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result_path)


if __name__ == "__main__":
    main()
