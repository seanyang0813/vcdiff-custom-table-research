from __future__ import annotations

import json

from vcdiff_opt.trace import TRACE_PREFIX, parse_trace


def test_parse_trace_accepts_window_record_after_instructions() -> None:
    records = [
        {
            "kind": "instruction",
            "window": 0,
            "position": 0,
            "type": "ADD",
            "size": 3,
            "mode": 0,
        },
        {
            "kind": "window",
            "window": 0,
            "target_offset": 0,
            "target_length": 3,
            "source_used": False,
            "source_position": 0,
            "source_length": 0,
        },
    ]
    stderr = "noise\n" + "\n".join(TRACE_PREFIX + json.dumps(record) for record in records)
    windows = parse_trace(stderr)
    assert len(windows) == 1
    assert windows[0].target_length == 3
    assert windows[0].instructions[0].type_name == "ADD"

