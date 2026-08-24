#!/usr/bin/env python3
"""Write the current evidence-bounded Android study status."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
STATE = ROOT / "benchmark_android/work/oracle-state-v1.json"
JSON_OUTPUT = ROOT / "results/android/status-v1.json"
MD_OUTPUT = ROOT / "results/android/status-v1.md"


def main() -> None:
    corpus = json.loads(CORPUS.read_text())
    state = json.loads(STATE.read_text()) if STATE.is_file() else {"pairs": {}}
    exact = [value | {"pair_id": key} for key, value in state["pairs"].items() if value["status"] == "complete"]
    failures = [value | {"pair_id": key} for key, value in state["pairs"].items() if value["status"] != "complete"]
    material = [row for row in exact if float(row["saving_percent"]) >= 1.0]
    coverage_gate = len(exact) >= 30
    signal_gate = coverage_gate and len(material) / len(exact) >= 0.25
    value = {
        "format": "vcdiff-public-android-status-v1",
        "status": "partial_nonconfirmatory",
        "frozen_pair_count": corpus["accepted_pair_count"],
        "exact_pair_count": len(exact),
        "nonexact_attempt_count": len(failures),
        "not_yet_attempted_count": corpus["accepted_pair_count"] - len(exact) - len(failures),
        "minimum_exact_coverage_gate_passed": coverage_gate,
        "material_signal_gate_passed": signal_gate,
        "predictor_or_table_bank_authorized": signal_gate,
        "exact_rows": exact,
        "nonexact_attempts": failures,
        "operational_diagnostics": [
            "results/android/fixed-q1-diagnostic-v1.json",
            "results/android/continuous-relaxation-stop-v1.json"
        ],
        "evidence_boundary": (
            "One exact favorable DEX pair is an anecdote, not held-out preregistered "
            "generalization. No predictor, table bank, production prototype, or "
            "Superpack claim is authorized."
        ),
    }
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Public Android DEX study status",
        "",
        "**Partial and nonconfirmatory.** The corpus is frozen at 40 independent "
        "F-Droid projects, but the preregistered minimum is 30 exact labels.",
        "",
        f"Exact: {len(exact)}/40. Nonexact attempted: {len(failures)}. "
        f"Not attempted: {value['not_yet_attempted_count']}.",
        "",
    ]
    for row in exact:
        lines.extend(
            [
                "## Exact result available",
                "",
                f"`{row['pair_id']}`: {row['baseline_bytes']:,} → {row['oracle_bytes']:,} "
                f"bytes, saving {row['saving_bytes']:,} bytes ({row['saving_percent']:.4f}%), "
                f"q={row['physical_slots']}. Both decoders passed.",
                "",
            ]
        )
    lines.extend(
        [
            "## Scaling stop",
            "",
            "The second scheduled pair has 70,913 logical instructions. Global binary "
            "SCIP was stopped at 8.5 GiB RSS; the continuous-path relaxation was stopped "
            "at 8.8 GiB without a bound. Fixed q=1 proved exactly but required 438 seconds "
            "and 5.67 GiB, so q=0..93 enumeration is not practical.",
            "",
            "The next required step is a problem-specific exact decomposition or stronger "
            "certificate. Approximate solver outputs will not be used as oracle labels.",
            "",
            "No predictor, reusable table bank, deployment experiment, or Superpack claim "
            "is supported at this stage.",
            "",
        ]
    )
    MD_OUTPUT.write_text("\n".join(lines))
    print(JSON_OUTPUT)
    print(MD_OUTPUT)


if __name__ == "__main__":
    main()
