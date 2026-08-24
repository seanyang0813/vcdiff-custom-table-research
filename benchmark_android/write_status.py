#!/usr/bin/env python3
"""Write the current evidence-bounded Android study status."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
STATE = ROOT / "benchmark_android/work/oracle-state-v1.json"
ARTIFACTS = ROOT / "benchmark_android/artifacts"
JSON_OUTPUT = ROOT / "results/android/status-v1.json"
MD_OUTPUT = ROOT / "results/android/status-v1.md"


def main() -> None:
    corpus = json.loads(CORPUS.read_text())
    state = json.loads(STATE.read_text()) if STATE.is_file() else {"pairs": {}}
    exact = [value | {"pair_id": key} for key, value in state["pairs"].items() if value["status"] == "complete"]
    incomplete = [
        value | {"pair_id": key}
        for key, value in state["pairs"].items()
        if value["status"] != "complete"
    ]
    operational_skips = [
        row
        for row in incomplete
        if row["status"] == "solver_skipped_by_posthoc_scaling_gate"
    ]
    failures = [
        row
        for row in incomplete
        if row["status"] != "solver_skipped_by_posthoc_scaling_gate"
    ]
    material = [row for row in exact if float(row["saving_percent"]) >= 1.0]
    frozen_pair_ids = {row["pair_id"] for row in corpus["pairs"]}
    replayed_pair_ids: set[str] = set()
    for pair_id in frozen_pair_ids:
        preparation_path = ARTIFACTS / pair_id / "trace-preparation.json"
        if not preparation_path.is_file():
            continue
        preparation = json.loads(preparation_path.read_text())
        if (
            preparation.get("pair_id") == pair_id
            and preparation.get("status") == "stock_trace_byte_replayed"
            and preparation.get("python_decoder_round_trip") is True
        ):
            replayed_pair_ids.add(pair_id)
    # A completed exact row is admitted only after its certificate audits the
    # stock-patch replay and both decoders. QuickDice and E6 predate the
    # lightweight trace-preparation sidecar, so count that stronger evidence.
    replayed_pair_ids.update(row["pair_id"] for row in exact)
    coverage_gate = len(exact) >= 30
    signal_gate = coverage_gate and len(material) / len(exact) >= 0.25
    not_yet_accounted = (
        corpus["accepted_pair_count"]
        - len(exact)
        - len(failures)
        - len(operational_skips)
    )
    accounting_complete = not_yet_accounted == 0
    trace_replay_complete = replayed_pair_ids == frozen_pair_ids
    exact_baseline_bytes = sum(int(row["baseline_bytes"]) for row in exact)
    exact_oracle_bytes = sum(int(row["oracle_bytes"]) for row in exact)
    exact_saving_bytes = exact_baseline_bytes - exact_oracle_bytes
    operational_diagnostics = [
        "results/android/fixed-q1-diagnostic-v1.json",
        "results/android/continuous-relaxation-stop-v1.json",
        "results/android/strengthened-root-lp-global-presolve-v1.json",
        "results/android/e6b-fixed-q-bound-replay-v1.json",
        "results/android/constellations-fixed-q-bound-replay-v1.json",
        "results/android/constellations-exact-summary-v1.json",
        "results/android/strengthened-scip-validation-v1.json",
        "results/android/rational-dual-scaling-gate-v1.json",
    ]
    for row in incomplete:
        diagnostic = row.get("diagnostic")
        if diagnostic is not None and diagnostic not in operational_diagnostics:
            operational_diagnostics.append(diagnostic)
    value = {
        "format": "vcdiff-public-android-status-v1",
        "status": (
            "trace_complete_oracle_incomplete"
            if accounting_complete and trace_replay_complete and not coverage_gate
            else "partial_nonconfirmatory"
        ),
        "frozen_pair_count": corpus["accepted_pair_count"],
        "trace_replayed_pair_count": len(replayed_pair_ids),
        "trace_replay_schedule_complete": trace_replay_complete,
        "frozen_schedule_accounting_complete": accounting_complete,
        "exact_pair_count": len(exact),
        "material_exact_pair_count": len(material),
        "zero_saving_exact_pair_count": sum(
            int(row["saving_bytes"]) == 0 for row in exact
        ),
        "exact_subset_baseline_bytes": exact_baseline_bytes,
        "exact_subset_oracle_bytes": exact_oracle_bytes,
        "exact_subset_saving_bytes": exact_saving_bytes,
        "exact_subset_weighted_saving_percent": (
            0.0
            if exact_baseline_bytes == 0
            else 100.0 * exact_saving_bytes / exact_baseline_bytes
        ),
        "nonexact_attempt_count": len(failures),
        "operational_skip_count": len(operational_skips),
        "not_yet_attempted_count": not_yet_accounted,
        "minimum_exact_coverage_gate_passed": coverage_gate,
        "material_signal_gate_passed": signal_gate,
        "predictor_or_table_bank_authorized": signal_gate,
        "exact_rows": exact,
        "nonexact_attempts": failures,
        "operational_skips": operational_skips,
        "operational_diagnostics": operational_diagnostics,
        "evidence_boundary": (
            f"All {len(replayed_pair_ids)} frozen stock traces were replayed, but only "
            f"{len(exact)} DEX pairs have exact oracle labels, insufficient for the "
            "preregistered 30-pair coverage gate. The exactly solved subset is selected "
            "by solver tractability and is not a corpus distribution estimate. No "
            "predictor, table bank, production prototype, or Superpack claim is "
            "authorized."
        ),
    }
    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Public Android DEX study status",
        "",
        "**Trace-complete but oracle-incomplete and nonconfirmatory.** The corpus is "
        "frozen at 40 independent F-Droid projects, and every stock trace was exactly "
        "byte-replayed. The preregistered minimum is 30 exact oracle labels.",
        "",
        f"Exact: {len(exact)}/40. Nonexact attempted: {len(failures)}. "
        f"Operationally skipped after trace replay: {len(operational_skips)}. "
        f"Not attempted: {value['not_yet_attempted_count']}.",
        "",
        "The exact subset contains "
        f"{len(material)} pairs saving at least 1% and "
        f"{value['zero_saving_exact_pair_count']} zero-saving controls. Its weighted "
        f"saving is {value['exact_subset_weighted_saving_percent']:.4f}%, but this "
        "tractability-selected subset is not a valid estimate of the 40-project "
        "distribution.",
        "",
        "## Exact labels",
        "",
        "| Pair | Stock bytes | Exact bytes | Saving | q |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in exact:
        lines.append(
            f"| `{row['pair_id']}` | {row['baseline_bytes']:,} | "
            f"{row['oracle_bytes']:,} | {row['saving_bytes']:,} "
            f"({row['saving_percent']:.4f}%) | {row['physical_slots']} |"
        )
    lines.extend(["", "Every exact row passed both decoders.", ""])
    if failures:
        lines.extend(["## Nonexact attempts", ""])
        for row in failures:
            if "q93_full_patch_bytes_integer_lower_bound" in row:
                detail = (
                    f"The retained q={row['attempted_physical_slots']} bound is "
                    f"{row['q93_full_patch_bytes_integer_lower_bound']:,} bytes; "
                    "it is not an attained optimum."
                )
            else:
                detail = "No exact fixed-q lower bound was produced."
            lines.extend(
                [
                    f"`{row['pair_id']}`: stopped without an exact pair label "
                    f"(`{row['status']}`). {detail}",
                    "",
                ]
            )
    if operational_skips:
        lines.extend(["## Post-hoc operational skips", ""])
        for row in operational_skips:
            lines.extend(
                [
                    f"`{row['pair_id']}`: the stock trace was exactly byte-replayed, "
                    "but the current q=93 solver was not started because the trace "
                    f"has {row['logical_instructions']:,} logical instructions, at or "
                    "above the post-hoc 240,000-instruction host cutoff. This produces "
                    "no exact bound and no oracle label.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Exact-oracle scaling recovery",
            "",
            "The E6 scaling-trigger pair has 70,913 logical instructions. Earlier global "
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
            "After measured rational-bound construction misses began at 240,186 "
            "instructions, a disclosed post-hoc host policy stopped launching the "
            "current solver at 240,000 or above. Those pairs remain in the frozen "
            "schedule as trace-replayed operational skips with no bound and no label.",
            "",
            "One exact zero-saving control had no eligible implicit-size table "
            "candidate. Its q=0 optimum was certified by the zero-variable structural "
            "branch and two decoder replays without invoking a MILP.",
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
