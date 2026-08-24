from __future__ import annotations

import json
from pathlib import Path

from benchmark.prepare_pair_trace import semantic_trace_sha256


def write_trace(path: Path, *, prefix: str, instruction_size: int = 4) -> None:
    value = {
        "baseline_patch": {
            "path": f"{prefix}/baseline.vcdiff",
            "sha256": "baseline-hash",
            "size": 17,
        },
        "format": "vcdiff-xdelta-logical-trace-v1",
        "source": {
            "path": f"{prefix}/source.bin",
            "sha256": "source-hash",
            "size": 10,
        },
        "target": {
            "path": f"{prefix}/target.bin",
            "sha256": "target-hash",
            "size": 14,
        },
        "windows": [
            {
                "index": 0,
                "instructions": [
                    {"mode": 0, "size": instruction_size, "type": "ADD"}
                ],
                "source_length": 0,
                "source_position": 0,
                "source_used": False,
                "target_length": instruction_size,
                "target_offset": 0,
            }
        ],
    }
    path.write_text(json.dumps(value))


def test_semantic_trace_hash_ignores_only_checkout_paths(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    changed = tmp_path / "changed.json"
    write_trace(first, prefix="/checkout/one")
    write_trace(second, prefix="/different/output")
    write_trace(changed, prefix="/checkout/one", instruction_size=5)

    assert semantic_trace_sha256(first) == semantic_trace_sha256(second)
    assert semantic_trace_sha256(first) != semantic_trace_sha256(changed)
