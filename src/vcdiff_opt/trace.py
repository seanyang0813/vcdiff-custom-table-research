from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .model import Instruction, TYPE_TO_ID, WindowTrace

TRACE_PREFIX = "VCDIFF_TRACE "


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_trace(stderr: str) -> tuple[WindowTrace, ...]:
    instructions: dict[int, list[Instruction]] = {}
    metadata: dict[int, dict[str, Any]] = {}
    for line in stderr.splitlines():
        if not line.startswith(TRACE_PREFIX):
            continue
        record = json.loads(line[len(TRACE_PREFIX) :])
        window = int(record["window"])
        if record["kind"] == "instruction":
            instructions.setdefault(window, []).append(
                Instruction(
                    position=int(record["position"]),
                    type_id=TYPE_TO_ID[str(record["type"])],
                    size=int(record["size"]),
                    mode=int(record.get("mode", 0)),
                    address=None if "address" not in record else int(record["address"]),
                    source_copy=record.get("source_copy"),
                    run_byte=None if "byte" not in record else int(record["byte"]),
                )
            )
        elif record["kind"] == "window":
            if window in metadata:
                raise ValueError(f"duplicate trace metadata for window {window}")
            metadata[window] = record
        else:
            raise ValueError(f"unknown trace record kind: {record['kind']}")

    if not metadata:
        raise ValueError("xdelta produced no trace records")
    if set(instructions) - set(metadata):
        raise ValueError("trace has instructions without window metadata")

    windows: list[WindowTrace] = []
    expected_target_offset = 0
    for index in sorted(metadata):
        if index != len(windows):
            raise ValueError(f"nonconsecutive trace window index {index}")
        record = metadata[index]
        window = WindowTrace(
            index=index,
            target_offset=int(record["target_offset"]),
            target_length=int(record["target_length"]),
            source_used=bool(record["source_used"]),
            source_position=int(record["source_position"]),
            source_length=int(record["source_length"]),
            instructions=tuple(instructions.get(index, [])),
        )
        if window.target_offset != expected_target_offset:
            raise ValueError("trace target windows are not contiguous")
        expected_target_offset += window.target_length
        windows.append(window)
    return tuple(windows)


def run_xdelta_trace(
    executable: Path,
    source: Path,
    target: Path,
    baseline_patch: Path,
    *,
    window_size: int | None = None,
) -> tuple[tuple[WindowTrace, ...], subprocess.CompletedProcess[str]]:
    command = [
        str(executable),
        "-e",
        "-f",
        "-n",
        "-S",
        "none",
        "-A",
    ]
    if window_size is not None:
        command.extend(["-W", str(window_size)])
    command.extend(["-s", str(source), str(target), str(baseline_patch)])
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"xdelta trace command failed with {completed.returncode}:\n{completed.stderr}"
        )
    windows = parse_trace(completed.stderr)
    if sum(window.target_length for window in windows) != target.stat().st_size:
        raise ValueError("trace target length does not match the target file")
    return windows, completed


def trace_document(
    source: Path,
    target: Path,
    baseline_patch: Path,
    windows: tuple[WindowTrace, ...],
) -> dict[str, Any]:
    return {
        "format": "vcdiff-xdelta-logical-trace-v1",
        "source": {
            "path": str(source.resolve()),
            "size": source.stat().st_size,
            "sha256": sha256_file(source),
        },
        "target": {
            "path": str(target.resolve()),
            "size": target.stat().st_size,
            "sha256": sha256_file(target),
        },
        "baseline_patch": {
            "path": str(baseline_patch.resolve()),
            "size": baseline_patch.stat().st_size,
            "sha256": sha256_file(baseline_patch),
        },
        "windows": [window.to_dict() for window in windows],
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

