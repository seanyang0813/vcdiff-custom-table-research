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
            "results/android/continuous-relaxation-stop-v1.json",
            "results/android/strengthened-root-lp-global-presolve-v1.json",
            "results/android/e6b-fixed-q-bound-replay-v1.json",
            "results/android/strengthened-scip-validation-v1.json",
            "results/android/mmrl-q93-witness-stop-v1.json",
            "results/android/icicle-q93-witness-stop-v1.json",
            "results/android/tranquilstopwatch-q93-root-gap-v1.json",
            "results/android/ariane-q93-root-gap-v1.json",
            "results/android/pimiwidget-q93-scip-safety-stop-v1.json",
            "results/android/pathfinder-q93-root-gap-v1.json"
        ],
        "evidence_boundary": (
            f"{len(exact)} exact DEX pairs are insufficient for the preregistered "
            "30-pair coverage gate. No predictor, table bank, production prototype, "
            "or Superpack claim is authorized."
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
    if failures:
        lines.extend(["## Nonexact attempts", ""])
        for row in failures:
            lines.extend(
                [
                    f"`{row['pair_id']}`: stopped without an exact pair label "
                    f"(`{row['status']}`). The retained q={row['attempted_physical_slots']} "
                    f"bound is {row['q93_full_patch_bytes_integer_lower_bound']:,} bytes; "
                    "it is not an attained optimum.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Exact-oracle scaling recovery",
            "",
            "The second scheduled pair has 70,913 logical instructions. Earlier global "
            "SCIP attempts were stopped at 8.5--8.8 GiB RSS and remain nonresults. The "
            "replacement proof removes LP-redundant aggregate big-M rows, replays exact "
            "rational dual vectors, uses q-monotonicity to transfer the q=80 bound to "
            "q=1..79, and matches q=93 with a binary decoded witness.",
            "",
            "This certificate architecture has passed on the scaling trigger, but the "
            "preregistered corpus still requires at least 30 exact independent pairs. "
            "Approximate solver outputs will not be used as oracle labels.",
            "",
            "A separate aggregate-free exact-SCIP formulation reproduced the QuickDice "
            "q=83 and E6 q=93 fixed-q optima in one node while retaining continuous path "
            "variables. It still reached a host memory safety stop on Pimi Widget, so it "
            "is a bounded validation tool rather than a general scaling solution.",
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
