#!/usr/bin/env python3
"""Write an explicitly partial summary of exact-SCIP frozen-corpus results."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
STATE = ROOT / "benchmark_work/scip-oracle/state-v1.json"
JSON_OUTPUT = ROOT / "results/generality/scip-partial-summary-v1.json"
MD_OUTPUT = ROOT / "results/generality/scip-partial-summary-v1.md"


def main() -> None:
    lock = json.loads(LOCK.read_text())
    state = json.loads(STATE.read_text())["pairs"]
    metadata = {pair["id"]: pair for pair in lock["pairs"]}
    rows = []
    for pair_id, result in state.items():
        if result["status"] != "complete":
            continue
        baseline = int(result["baseline_bytes"])
        oracle = int(result["oracle_bytes"])
        rows.append(
            {
                "pair_id": pair_id,
                "category": metadata[pair_id]["category"],
                "project": metadata[pair_id]["project"],
                "baseline_bytes": baseline,
                "oracle_bytes": oracle,
                "saving_bytes": baseline - oracle,
                "saving_percent": 100.0 * (baseline - oracle) / baseline,
                "physical_slots": int(result["physical_slots"]),
                "certificate": result["certificate"],
                "certificate_sha256": result["certificate_sha256"],
            }
        )
    rows.sort(key=lambda row: [pair["id"] for pair in lock["pairs"]].index(row["pair_id"]))
    complete_ids = {row["pair_id"] for row in rows}
    value = {
        "format": "vcdiff-frozen-corpus-exact-scip-partial-summary-v1",
        "status": "partial_nonconfirmatory",
        "frozen_pair_count": len(lock["pairs"]),
        "exact_pair_count": len(rows),
        "not_yet_run_count": len(lock["pairs"]) - len(rows),
        "confirmatory_use": False,
        "reason": "The preregistered 48-pair distribution is incomplete.",
        "rows": rows,
        "not_yet_run": [pair["id"] for pair in lock["pairs"] if pair["id"] not in complete_ids],
    }
    JSON_OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Frozen-corpus exact-SCIP partial status",
        "",
        f"**Partial and nonconfirmatory:** {len(rows)}/48 frozen pairs have exact-SCIP certificates. "
        "The preregistered distribution, predictor, and table-bank gates have not been evaluated.",
        "",
        "| Pair | Category | Stock | Exact | Saving | q |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['pair_id']} | {row['category']} | {row['baseline_bytes']:,} | "
            f"{row['oracle_bytes']:,} | {row['saving_bytes']:,} "
            f"({row['saving_percent']:.4f}%) | {row['physical_slots']} |"
        )
    lines.extend(
        [
            "",
            "Every listed row has equal exact-SCIP primal/dual bounds, independent DP "
            "attainment, emitted-byte equality, and two successful decoder replays. "
            "Unrun pairs are not treated as zero-gain or excluded.",
            "",
        ]
    )
    MD_OUTPUT.write_text("\n".join(lines))
    print(JSON_OUTPUT)
    print(MD_OUTPUT)


if __name__ == "__main__":
    main()
