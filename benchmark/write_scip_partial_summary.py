#!/usr/bin/env python3
"""Write an explicitly partial summary of exact-SCIP frozen-corpus results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
STATE = ROOT / "benchmark_work/scip-oracle/state-v1.json"
ARTIFACTS = ROOT / "benchmark_artifacts_scip"
JSON_OUTPUT = ROOT / "results/generality/scip-partial-summary-v1.json"
MD_OUTPUT = ROOT / "results/generality/scip-partial-summary-v1.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_trace_sha256(path: Path) -> str:
    document = json.loads(path.read_text())
    for name in ("baseline_patch", "source", "target"):
        document[name].pop("path", None)
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def elapsed_seconds(value: str) -> float:
    fields = [float(field) for field in value.split(":")]
    if len(fields) == 2:
        minutes, seconds = fields
        return 60.0 * minutes + seconds
    if len(fields) == 3:
        hours, minutes, seconds = fields
        return 3600.0 * hours + 60.0 * minutes + seconds
    raise ValueError(f"unexpected GNU time elapsed value: {value}")


def read_resource_usage(pair_id: str, result: dict) -> dict:
    log_path = ROOT / result.get(
        "log", f"benchmark_work/scip-oracle/{pair_id}.log"
    )
    if not log_path.is_file():
        raise FileNotFoundError(f"missing resource log for {pair_id}")
    values = {}
    for raw_line in log_path.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("Elapsed (wall clock) time"):
            values["elapsed_wall_seconds"] = elapsed_seconds(line.rsplit(": ", 1)[1])
        elif line.startswith("Maximum resident set size (kbytes):"):
            values["maximum_resident_kib"] = int(line.rsplit(":", 1)[1])
        elif line.startswith("Swaps:"):
            values["swap_count"] = int(line.rsplit(":", 1)[1])
        elif line.startswith("Exit status:"):
            values["exit_status"] = int(line.rsplit(":", 1)[1])
    required = {
        "elapsed_wall_seconds",
        "maximum_resident_kib",
        "swap_count",
        "exit_status",
    }
    if set(values) != required or values["exit_status"] != 0:
        raise ValueError(f"invalid or incomplete resource log for {pair_id}")
    if "elapsed_seconds" in result:
        values["runner_elapsed_seconds"] = float(result["elapsed_seconds"])
    values["log"] = str(log_path.relative_to(ROOT))
    return values


def verify_exact_certificate(pair: dict, result: dict) -> dict:
    pair_id = pair["id"]
    certificate_path = ROOT / result["certificate"]
    if not certificate_path.is_file():
        raise FileNotFoundError(f"missing exact certificate for {pair_id}")
    if sha256(certificate_path) != result["certificate_sha256"]:
        raise ValueError(f"exact certificate hash drift for {pair_id}")
    certificate = json.loads(certificate_path.read_text())
    if certificate.get("format") != "vcdiff-custom-table-certificate-v4-scip-exact":
        raise ValueError(f"unexpected exact certificate format for {pair_id}")
    for name in ("source", "target"):
        expected = pair[name]
        actual = certificate.get(name, {})
        if (
            actual.get("sha256") != expected["sha256"]
            or int(actual.get("size", -1)) != int(expected["size"])
        ):
            raise ValueError(f"frozen {name} identity drift for {pair_id}")

    baseline = certificate.get("baseline", {})
    optimum = certificate.get("global_optimum", {})
    if (
        int(baseline.get("size", -1)) != int(result["baseline_bytes"])
        or int(optimum.get("file_bytes", -1)) != int(result["oracle_bytes"])
        or int(optimum.get("physical_slots", -1)) != int(result["physical_slots"])
    ):
        raise ValueError(f"state/certificate objective drift for {pair_id}")
    patch_path = Path(optimum.get("patch_path", ""))
    if not patch_path.is_file() or sha256(patch_path) != optimum.get("file_sha256"):
        raise ValueError(f"emitted optimum drift for {pair_id}")

    proof = certificate.get("tools", {}).get("independent_integer_proof", {})
    calls = proof.get("calls", [])
    if (
        proof.get("scip_version") != "10.0.2"
        or proof.get("pyscipopt_version") != "6.2.1"
        or not calls
        or any(
            call.get("exact_mode") is not True
            or int(call.get("objective", -1)) != int(call.get("best_bound", -2))
            for call in calls
        )
        or calls[-1].get("mps_sha256") != result.get("global_mps_sha256")
    ):
        raise ValueError(f"locked exact-SCIP proof drift for {pair_id}")

    target_hash = pair["target"]["sha256"]
    verification = certificate.get("verification", {})
    python_decoder = verification.get("independent_python_decoder", {})
    historical_decoder = verification.get("unchanged_xdelta_decoder", {})
    if not (
        python_decoder.get("decoded_sha256") == target_hash
        and historical_decoder.get("returncode") == 0
        and historical_decoder.get("decoded_sha256") == target_hash
    ):
        raise ValueError(f"decoder replay drift for {pair_id}")
    return certificate


def main() -> None:
    lock = json.loads(LOCK.read_text())
    state = json.loads(STATE.read_text())["pairs"]
    metadata = {pair["id"]: pair for pair in lock["pairs"]}
    rows = []
    for pair_id, result in state.items():
        if result["status"] != "complete":
            continue
        if pair_id not in metadata:
            raise ValueError(f"state contains non-frozen pair {pair_id}")
        certificate = verify_exact_certificate(metadata[pair_id], result)
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
                "logical_instruction_count": int(
                    certificate["trace"]["instruction_count"]
                ),
                "observed_candidate_count": int(
                    certificate["trace"]["observed_candidate_count"]
                ),
                "physical_slots": int(result["physical_slots"]),
                "certificate": result["certificate"],
                "certificate_sha256": result["certificate_sha256"],
                "global_mps_sha256": result["global_mps_sha256"],
                "global_scip_nodes": int(result["global_nodes"]),
                "resource_usage": read_resource_usage(pair_id, result),
            }
        )
    rows.sort(key=lambda row: [pair["id"] for pair in lock["pairs"]].index(row["pair_id"]))
    complete_ids = {row["pair_id"] for row in rows}
    trace_rows = []
    trace_replayed_ids = set(complete_ids)
    for pair in lock["pairs"]:
        pair_id = pair["id"]
        preparation_path = ARTIFACTS / pair_id / "trace-preparation.json"
        if not preparation_path.is_file():
            continue
        preparation = json.loads(preparation_path.read_text())
        historical = preparation.get("verification", {}).get(
            "historical_xdelta_decoder", {}
        )
        trace_path = Path(preparation.get("trace_path", ""))
        if not (
            preparation.get("format")
            == "vcdiff-legacy-pair-trace-preparation-v1"
            and preparation.get("status") == "stock_trace_byte_replayed"
            and preparation.get("pair_id") == pair_id
            and preparation.get("source_sha256") == pair["source"]["sha256"]
            and preparation.get("target_sha256") == pair["target"]["sha256"]
            and trace_path.is_file()
            and sha256(trace_path) == preparation.get("trace_sha256")
            and semantic_trace_sha256(trace_path)
            == preparation.get("trace_semantic_sha256")
            and preparation.get("verification", {}).get(
                "strict_python_decoder_round_trip"
            )
            is True
            and historical.get("returncode") == 0
            and historical.get("decoded_sha256") == pair["target"]["sha256"]
        ):
            raise ValueError(f"invalid trace-preparation evidence for {pair_id}")
        trace_replayed_ids.add(pair_id)
        if pair_id not in complete_ids:
            trace_rows.append(
                {
                    "pair_id": pair_id,
                    "category": pair["category"],
                    "project": pair["project"],
                    "baseline_bytes": int(preparation["baseline_bytes"]),
                    "logical_instruction_count": int(
                        preparation["logical_instruction_count"]
                    ),
                    "exact_status": state.get(pair_id, {}).get(
                        "status", "not_exactly_attempted"
                    ),
                    "trace_preparation": str(preparation_path.relative_to(ROOT)),
                    "trace_semantic_sha256": preparation[
                        "trace_semantic_sha256"
                    ],
                }
            )
    trace_rows.sort(
        key=lambda row: (row["logical_instruction_count"], row["pair_id"])
    )
    trace_complete = len(trace_replayed_ids) == len(lock["pairs"])
    exact_baseline = sum(row["baseline_bytes"] for row in rows)
    exact_oracle = sum(row["oracle_bytes"] for row in rows)
    exact_saving = exact_baseline - exact_oracle
    value = {
        "format": "vcdiff-frozen-corpus-exact-scip-partial-summary-v1",
        "status": (
            "trace_complete_exact_incomplete"
            if trace_complete and len(rows) < len(lock["pairs"])
            else "partial_nonconfirmatory"
        ),
        "frozen_pair_count": len(lock["pairs"]),
        "trace_replayed_pair_count": len(trace_replayed_ids),
        "trace_replay_schedule_complete": trace_complete,
        "exact_pair_count": len(rows),
        "without_exact_label_count": len(lock["pairs"]) - len(rows),
        "confirmatory_use": False,
        "reason": (
            "Every frozen stock trace is replayed, but the preregistered 48-pair "
            "exact-oracle distribution is incomplete."
        ),
        "rows": rows,
        "tractability_selected_exact_subset": {
            "pair_count": len(rows),
            "positive_pair_count": sum(row["saving_bytes"] > 0 for row in rows),
            "zero_gain_pair_count": sum(row["saving_bytes"] == 0 for row in rows),
            "baseline_bytes": exact_baseline,
            "oracle_bytes": exact_oracle,
            "saving_bytes": exact_saving,
            "saving_percent": 100.0 * exact_saving / exact_baseline,
            "confirmatory_use": False,
            "selection_boundary": (
                "Descriptive only: exact labels were selected by operational "
                "tractability, not by the frozen corpus analysis plan."
            ),
        },
        "without_exact_label": [
            pair["id"] for pair in lock["pairs"] if pair["id"] not in complete_ids
        ],
        "trace_frontier": trace_rows,
    }
    JSON_OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Frozen-corpus exact-SCIP partial status",
        "",
        "**Trace-complete but exact-incomplete and nonconfirmatory:** every frozen "
        f"stock trace has been independently replayed, while {len(rows)}/48 pairs "
        "have exact-SCIP certificates. The preregistered distribution, predictor, "
        "and table-bank gates have not been evaluated.",
        "",
        "| Pair | Category | Trace | Stock | Exact | Saving | q | Wall s | Peak MiB |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['pair_id']} | {row['category']} | "
            f"{row['logical_instruction_count']:,} | {row['baseline_bytes']:,} | "
            f"{row['oracle_bytes']:,} | {row['saving_bytes']:,} "
            f"({row['saving_percent']:.4f}%) | {row['physical_slots']} | "
            f"{row['resource_usage']['elapsed_wall_seconds']:,.2f} | "
            f"{row['resource_usage']['maximum_resident_kib'] / 1024:,.0f} |"
        )
    lines.extend(
        [
            "",
            "Every listed row has equal exact-SCIP primal/dual bounds, independent DP "
            "attainment, emitted-byte equality, and two successful decoder replays. "
            "Pairs without exact labels are not treated as zero-gain or excluded.",
            "",
            f"The tractability-selected exact subset totals {exact_baseline:,} to "
            f"{exact_oracle:,} bytes, saving {exact_saving:,} "
            f"({100.0 * exact_saving / exact_baseline:.4f}%). This aggregate is "
            "descriptive only and is not a frozen-corpus distribution estimate.",
            "",
            "## Unresolved exact frontier",
            "",
            "These rows have exact stock-trace byte replay and two decoder checks, but "
            "no exact custom-table label. Instruction count is an operational ranking "
            "aid, not an outcome or exclusion rule.",
            "",
            "| Pair | Category | Logical instructions | Stock bytes | Exact status |",
            "|---|---|---:|---:|---|",
        ]
    )
    for row in trace_rows:
        lines.append(
            f"| {row['pair_id']} | {row['category']} | "
            f"{row['logical_instruction_count']:,} | {row['baseline_bytes']:,} | "
            f"{row['exact_status']} |"
        )
    lines.extend(
        [
            "",
        ]
    )
    MD_OUTPUT.write_text("\n".join(lines))
    print(JSON_OUTPUT)
    print(MD_OUTPUT)


if __name__ == "__main__":
    main()
