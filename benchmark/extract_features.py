#!/usr/bin/env python3
"""Extract preregistered stock-trace features and exact-oracle labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
LOCK_HASH = ROOT / "benchmark/artifact-lock-v1.sha256"
ANALYSIS = ROOT / "benchmark/analysis-spec-v1.json"
ANALYSIS_HASH = ROOT / "benchmark/analysis-spec-v1.sha256"
AMENDMENT = ROOT / "benchmark/validity-amendment-v1.json"
AMENDMENT_HASH = ROOT / "benchmark/validity-amendment-v1.sha256"
EXECUTION_DEVIATIONS = ROOT / "benchmark/execution-deviations.jsonl"
CERTIFICATES = ROOT / "benchmark_artifacts_cpsat"
OUTPUT = ROOT / "results/generality"
TOP_K = (1, 4, 8, 16, 32, 64, 93)
SIZE_BINS = (
    ("1", 1, 1),
    ("2", 2, 2),
    ("3", 3, 3),
    ("4", 4, 4),
    ("5_8", 5, 8),
    ("9_16", 9, 16),
    ("17_32", 17, 32),
    ("33_64", 33, 64),
    ("65_127", 65, 127),
    ("128_255", 128, 255),
    ("256_plus", 256, None),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash(hash_path: Path, value_path: Path) -> str:
    expected = hash_path.read_text().split()[0]
    actual = sha256(value_path)
    if actual != expected:
        raise ValueError(f"lock mismatch: {value_path}")
    return actual


def signature(instruction: dict[str, Any]) -> str:
    return f"{instruction['type']}:{int(instruction['size'])}:{int(instruction.get('mode', 0))}"


def ranked(counter: Counter[str]) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def distribution_fields(prefix: str, counter: Counter[str]) -> dict[str, float]:
    counts = sorted(counter.values(), reverse=True)
    total = sum(counts)
    result: dict[str, float] = {}
    if total == 0:
        entropy = normalized = herfindahl = 0.0
    else:
        probabilities = [count / total for count in counts]
        entropy = -sum(p * math.log2(p) for p in probabilities)
        normalized = entropy / math.log2(len(counts)) if len(counts) > 1 else 0.0
        herfindahl = sum(p * p for p in probabilities)
    result[f"{prefix}_unique"] = len(counts)
    result[f"{prefix}_entropy"] = entropy
    result[f"{prefix}_normalized_entropy"] = normalized
    result[f"{prefix}_herfindahl"] = herfindahl
    for k in TOP_K:
        result[f"{prefix}_top{k}_mass"] = sum(counts[:k]) / total if total else 0.0
    return result


def nonoverlap_coverage(
    windows: list[list[str]], allowed_pairs: set[str], instruction_count: int
) -> float:
    covered = 0
    for values in windows:
        best = [0] * (len(values) + 2)
        for index in range(len(values) - 1, -1, -1):
            best[index] = best[index + 1]
            if index + 1 < len(values):
                pair = values[index] + "+" + values[index + 1]
                if pair in allowed_pairs:
                    best[index] = max(best[index], 2 + best[index + 2])
        covered += best[0]
    return covered / instruction_count if instruction_count else 0.0


def quantile(values: list[int], probability: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.int64), probability, method="linear"))


def extract_pair(pair: dict[str, Any]) -> tuple[dict[str, Any], str]:
    directory = CERTIFICATES / pair["id"]
    certificate_path = directory / "certificate.json"
    trace_path = directory / "trace.json"
    certificate = json.loads(certificate_path.read_text())
    trace = json.loads(trace_path.read_text())
    if certificate.get("format") != "vcdiff-custom-table-certificate-v3-cpsat":
        raise ValueError(f"non-CP-SAT certificate for {pair['id']}")
    if certificate["validity_amendment"]["sha256"] != sha256(AMENDMENT):
        raise ValueError(f"validity amendment mismatch for {pair['id']}")
    proof = certificate["tools"]["independent_integer_proof"]
    if proof["status_required"] != "OPTIMAL" or any(
        int(call["objective"]) != int(call["best_bound"])
        for call in proof["calls"]
    ):
        raise ValueError(f"invalid CP-SAT proof record for {pair['id']}")
    if sha256(trace_path) != certificate["trace"]["sha256"]:
        raise ValueError(f"trace hash mismatch for {pair['id']}")
    for side in ("source", "target"):
        if certificate[side]["sha256"] != pair[side]["sha256"]:
            raise ValueError(f"certificate {side} mismatch for {pair['id']}")
        if trace[side]["sha256"] != pair[side]["sha256"]:
            raise ValueError(f"trace {side} mismatch for {pair['id']}")

    instructions_by_window: list[list[dict[str, Any]]] = [
        window["instructions"] for window in trace["windows"]
    ]
    instructions = [item for window in instructions_by_window for item in window]
    signatures_by_window = [
        [signature(item) for item in window] for window in instructions_by_window
    ]
    single_counts = Counter(value for window in signatures_by_window for value in window)
    pair_counts: Counter[str] = Counter()
    for window in signatures_by_window:
        pair_counts.update(
            window[index] + "+" + window[index + 1]
            for index in range(len(window) - 1)
        )
    ranked_singles = ranked(single_counts)
    ranked_pairs = ranked(pair_counts)
    instruction_count = len(instructions)
    pair_occurrences = sum(pair_counts.values())
    sizes = [int(item["size"]) for item in instructions]

    baseline = certificate["baseline"]
    default = certificate["default_table_optimum"]
    oracle = certificate["global_optimum"]
    solver = oracle["solver"]
    stock_bytes = int(baseline["size"])
    oracle_bytes = int(oracle["file_bytes"])
    if not (
        oracle_bytes
        == int(solver["patch_bytes"])
        == int(solver["patch_dual_bound"])
        and float(solver["solver_gap"]) == 0.0
    ):
        raise ValueError(f"non-exact oracle certificate for {pair['id']}")
    savings_bytes = stock_bytes - oracle_bytes
    savings_fraction = savings_bytes / stock_bytes if stock_bytes else 0.0
    target_size = int(certificate["target"]["size"])
    result: dict[str, Any] = {
        "pair_id": pair["id"],
        "project": pair["project"],
        "category": pair["category"],
        "distance": pair["distance"],
        "split": pair["split"],
        "source_ref": pair["source"]["ref"],
        "target_ref": pair["target"]["ref"],
        "source_bytes": int(pair["source"]["size"]),
        "target_bytes": target_size,
        "stock_patch_bytes": stock_bytes,
        "stock_patch_fraction_of_target": stock_bytes / target_size,
        "stock_instruction_bytes": int(default["instruction_bytes"]),
        "stock_data_bytes": int(default["data_bytes"]),
        "stock_address_bytes": int(default["address_bytes"]),
        "stock_file_header_bytes": int(default["file_header_bytes"]),
        "r_i": int(default["instruction_bytes"]) / stock_bytes,
        "logical_instruction_count": instruction_count,
        "instructions_per_output_mib": instruction_count / (target_size / 1048576.0),
        "adjacent_pair_occurrences": pair_occurrences,
    }
    type_counts = Counter(item["type"] for item in instructions)
    for name in ("ADD", "COPY", "RUN"):
        count = type_counts[name]
        result[f"type_{name.lower()}_count"] = count
        result[f"type_{name.lower()}_fraction"] = count / instruction_count
    copy_count = type_counts["COPY"]
    copy_modes = Counter(int(item.get("mode", 0)) for item in instructions if item["type"] == "COPY")
    for mode in range(9):
        count = copy_modes[mode]
        result[f"copy_mode_{mode}_count"] = count
        result[f"copy_mode_{mode}_fraction"] = count / copy_count if copy_count else 0.0
    source_copy_count = sum(
        1 for item in instructions if item["type"] == "COPY" and item.get("source_copy") is True
    )
    result["source_copy_count"] = source_copy_count
    result["source_copy_fraction_of_copy"] = source_copy_count / copy_count if copy_count else 0.0

    for label, lower, upper in SIZE_BINS:
        count = sum(size >= lower and (upper is None or size <= upper) for size in sizes)
        result[f"size_bin_{label}_count"] = count
        result[f"size_bin_{label}_fraction"] = count / instruction_count
    for label, probability in (
        ("min", 0.0), ("q25", 0.25), ("median", 0.5), ("q75", 0.75),
        ("q90", 0.9), ("q99", 0.99), ("max", 1.0),
    ):
        result[f"instruction_size_{label}"] = quantile(sizes, probability)

    result.update(distribution_fields("single", single_counts))
    result.update(distribution_fields("pair", pair_counts))
    for k in TOP_K:
        allowed = {name for name, _ in ranked_pairs[:k]}
        result[f"pair_top{k}_nonoverlap_instruction_coverage"] = nonoverlap_coverage(
            signatures_by_window, allowed, instruction_count
        )
    result["top_singles"] = [
        {"signature": name, "count": count, "mass": count / instruction_count}
        for name, count in ranked_singles[:93]
    ]
    result["top_pairs"] = [
        {"signature": name, "count": count, "mass": count / pair_occurrences}
        for name, count in ranked_pairs[:93]
    ]

    result.update(
        {
            "oracle_patch_bytes": oracle_bytes,
            "oracle_savings_bytes": savings_bytes,
            "oracle_savings_fraction": savings_fraction,
            "oracle_saves_0_3pct": savings_fraction >= 0.003,
            "oracle_saves_1pct": savings_fraction >= 0.01,
            "oracle_saves_2pct": savings_fraction >= 0.02,
            "oracle_physical_slots": int(oracle["physical_slots"]),
            "oracle_selected_pattern_count": int(oracle["selected_pattern_count"]),
            "oracle_instruction_bytes": int(oracle["instruction_bytes"]),
            "oracle_instruction_savings_vs_default": int(oracle["instruction_savings_vs_default"]),
            "oracle_file_header_bytes": int(oracle["file_header_bytes"]),
            "oracle_nested_table_delta_bytes": int(oracle["nested_table_delta_bytes"]),
            "oracle_table_transmission_cost_bytes": int(oracle["file_header_bytes"]) - int(default["file_header_bytes"]),
            "oracle_table_sha256": oracle["table_sha256"],
            "oracle_selected_patterns": oracle["selected_patterns"],
            "solver_gap": float(solver["solver_gap"]),
            "solver_patch_dual_bound": int(solver["patch_dual_bound"]),
            "solver_nodes": (
                None if solver["solver_nodes"] is None else int(solver["solver_nodes"])
            ),
            "solver_variables": int(solver["model_variables"]),
            "solver_constraints": int(solver["model_constraints"]),
            "observed_candidate_count": int(solver["observed_candidate_count"]),
        }
    )
    return result, sha256(certificate_path)


def csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-partial", action="store_true")
    arguments = parser.parse_args()
    lock_sha256 = verify_hash(LOCK_HASH, LOCK)
    analysis_sha256 = verify_hash(ANALYSIS_HASH, ANALYSIS)
    amendment_sha256 = verify_hash(AMENDMENT_HASH, AMENDMENT)
    lock = json.loads(LOCK.read_text())
    rows: list[dict[str, Any]] = []
    certificate_hashes: dict[str, str] = {}
    missing: list[str] = []
    for pair in lock["pairs"]:
        certificate = CERTIFICATES / pair["id"] / "certificate.json"
        if not certificate.is_file():
            missing.append(pair["id"])
            continue
        row, certificate_hash = extract_pair(pair)
        rows.append(row)
        certificate_hashes[pair["id"]] = certificate_hash
    if missing and not arguments.allow_partial:
        raise ValueError(f"missing {len(missing)} certificates; use --allow-partial while running")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    jsonl = OUTPUT / "features-v1.jsonl"
    csv_path = OUTPUT / "features-v1.csv"
    jsonl.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    fieldnames: list[str] = []
    for row in rows:
        for name in row:
            if name not in fieldnames:
                fieldnames.append(name)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: csv_value(value) for key, value in row.items()} for row in rows)
    manifest = {
        "format": "vcdiff-generality-feature-manifest-v1",
        "artifact_lock_sha256": lock_sha256,
        "analysis_spec_sha256": analysis_sha256,
        "validity_amendment_sha256": amendment_sha256,
        "certificate_root": str(CERTIFICATES.relative_to(ROOT)),
        "certificate_format": "vcdiff-custom-table-certificate-v3-cpsat",
        "proof_backend": "OR-Tools CP-SAT 9.15.6755",
        "execution_deviations_sha256": sha256(EXECUTION_DEVIATIONS),
        "complete": not missing,
        "row_count": len(rows),
        "missing_pair_ids": missing,
        "features_jsonl_sha256": sha256(jsonl),
        "features_csv_sha256": sha256(csv_path),
        "certificate_sha256": certificate_hashes,
    }
    counterexamples = sorted(
        str(path.relative_to(ROOT))
        for path in (OUTPUT / "optimizer-counterexamples").glob("*.json")
    )
    manifest["oracle_validity"] = True
    manifest["confirmatory_use"] = not missing
    manifest["optimizer_counterexamples"] = counterexamples
    manifest["historical_optimizer_counterexamples_status"] = (
        "retained evidence for the superseded HiGHS execution; not reused by amended run"
    )
    manifest_path = OUTPUT / "feature-manifest-v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (OUTPUT / "features-v1.sha256").write_text(
        f"{sha256(jsonl)}  results/generality/{jsonl.name}\n"
        f"{sha256(csv_path)}  results/generality/{csv_path.name}\n"
        f"{sha256(manifest_path)}  results/generality/{manifest_path.name}\n"
    )
    print(f"extracted {len(rows)} pairs; missing={len(missing)}")


if __name__ == "__main__":
    main()
