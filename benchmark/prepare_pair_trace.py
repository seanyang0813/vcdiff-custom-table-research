#!/usr/bin/env python3
"""Generate and independently replay one frozen legacy-corpus stock trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from vcdiff_opt.codec import encode_file
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.trace import run_xdelta_trace, trace_document


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
LOCK_HASH = ROOT / "benchmark/artifact-lock-v1.sha256"
TRACE_XDELTA = ROOT / "build/xdelta/xdelta3-trace"
DECODER = ROOT / "build/xdelta/xdelta3-rfc-custom-decoder"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_trace_sha256(path: Path) -> str:
    """Hash trace evidence after removing checkout/output path strings."""
    document = json.loads(path.read_text())
    for name in ("baseline_patch", "source", "target"):
        document[name].pop("path", None)
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def verify_external_decoder(
    source: Path, patch: Path, expected_target: bytes
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vcdiff-legacy-trace-") as directory:
        decoded = Path(directory) / "decoded.bin"
        command = [
            str(DECODER.resolve()),
            "-d",
            "-f",
            "-s",
            str(source.resolve()),
            str(patch.resolve()),
            str(decoded),
        ]
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"historical decoder failed with {completed.returncode}: "
                f"{completed.stderr}"
            )
        value = decoded.read_bytes()
        if value != expected_target:
            raise ValueError("historical decoder output differs from target")
        return {
            "command": [*command[:-1], "<temporary-output>"],
            "returncode": completed.returncode,
            "decoded_bytes": len(value),
            "decoded_sha256": hashlib.sha256(value).hexdigest(),
            "stderr": completed.stderr.strip(),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    expected_lock_hash = LOCK_HASH.read_text().split()[0]
    if sha256(LOCK) != expected_lock_hash:
        raise ValueError("frozen legacy artifact lock drift")
    lock = json.loads(LOCK.read_text())
    pair = next(
        (value for value in lock["pairs"] if value["id"] == arguments.pair_id),
        None,
    )
    if pair is None:
        raise ValueError("pair is not in the frozen 48-pair corpus")
    source = ROOT / pair["source"]["artifact"]
    target = ROOT / pair["target"]["artifact"]
    for name, path, metadata in (
        ("source", source, pair["source"]),
        ("target", target, pair["target"]),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"frozen {name} artifact is missing: {path}")
        if path.stat().st_size != int(metadata["size"]):
            raise ValueError(f"frozen {name} artifact size drift")
        if sha256(path) != metadata["sha256"]:
            raise ValueError(f"frozen {name} artifact hash drift")
    if not TRACE_XDELTA.is_file() or not DECODER.is_file():
        raise FileNotFoundError("pinned trace encoder or historical decoder is missing")

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
        raise AssertionError("strict Python decoder rejected the stock replay")
    historical = verify_external_decoder(source, baseline, target_bytes)
    default_path = arguments.output / "default-table-optimal.vcdiff"
    default_path.write_bytes(default_encoding.encoded)

    result = {
        "format": "vcdiff-legacy-pair-trace-preparation-v1",
        "status": "stock_trace_byte_replayed",
        "pair_id": pair["id"],
        "category": pair["category"],
        "frozen_artifact_lock_sha256": expected_lock_hash,
        "source_sha256": pair["source"]["sha256"],
        "target_sha256": pair["target"]["sha256"],
        "trace_path": str(trace_path),
        "trace_semantic_sha256": semantic_trace_sha256(trace_path),
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
        "tools": {
            "trace_xdelta_sha256": sha256(TRACE_XDELTA),
            "historical_decoder_sha256": sha256(DECODER),
        },
        "verification": {
            "strict_python_decoder_round_trip": True,
            "historical_xdelta_decoder": historical,
        },
        "evidence_boundary": (
            "Outcome-neutral preparation of the frozen stock trace only. No custom "
            "table solver was invoked and no exact-oracle label or gain is claimed."
        ),
    }
    result_path = arguments.output / "trace-preparation.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result_path)


if __name__ == "__main__":
    main()
