#!/usr/bin/env python3
"""Freeze the exact confirmatory corpus before generating any VCDIFF trace."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import prepare_artifacts as acquisition


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "benchmark_work/acquisition-state.json"
DEVIATIONS = ROOT / "benchmark/deviations.jsonl"
RECIPES = ROOT / "benchmark/build-recipes-v1.json"
RECIPES_HASH = ROOT / "benchmark/build-recipes-v1.sha256"
LOCK = ROOT / "benchmark/artifact-lock-v1.json"
LOCK_HASH = ROOT / "benchmark/artifact-lock-v1.sha256"
TRACE_ROOT = ROOT / "benchmark_artifacts"


def read_deviations() -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in DEVIATIONS.read_text().splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError("at least one acquisition deviation was expected")
    if any(record.get("outcome_observed") is not False for record in records):
        raise ValueError("every pre-trace deviation must say outcome_observed=false")
    return records


def main() -> None:
    preregistration = acquisition.verify_locks()
    preregistration_sha256 = acquisition.sha256(acquisition.PREREGISTRATION)
    expected_recipes = RECIPES_HASH.read_text().split()[0]
    actual_recipes = acquisition.sha256(RECIPES)
    if actual_recipes != expected_recipes:
        raise ValueError(
            f"build recipe drift: {actual_recipes} != {expected_recipes}"
        )
    if TRACE_ROOT.exists() and any(TRACE_ROOT.iterdir()):
        raise ValueError("refusing to freeze after confirmatory output exists")

    deviations = read_deviations()
    pair_ids = {pair["id"] for pair in preregistration["pairs"]}
    excluded = acquisition.excluded_pair_ids()
    unknown = excluded - pair_ids
    if unknown:
        raise ValueError(f"deviations exclude unknown pairs: {sorted(unknown)}")
    effective_pairs = [
        pair for pair in preregistration["pairs"] if pair["id"] not in excluded
    ]
    if not 30 <= len(effective_pairs) <= 60:
        raise ValueError(f"effective pair count out of requested range: {len(effective_pairs)}")

    state = json.loads(STATE.read_text())
    locked_artifacts: dict[str, dict[str, Any]] = {}
    locked_pairs: list[dict[str, Any]] = []
    for pair in effective_pairs:
        locked_pair = {
            key: pair[key]
            for key in ("id", "project", "category", "distance", "split", "recipe")
        }
        for side in ("source", "target"):
            endpoint = pair[side]
            artifact_name = endpoint["artifact"]
            metadata = state["artifacts"].get(artifact_name)
            if metadata is None:
                raise FileNotFoundError(f"artifact absent from state: {artifact_name}")
            artifact = ROOT / artifact_name
            actual_size = artifact.stat().st_size
            actual_sha256 = acquisition.sha256(artifact)
            if actual_size != metadata["size"] or actual_sha256 != metadata["sha256"]:
                raise ValueError(f"artifact/state mismatch: {artifact_name}")
            if not 0 < actual_size <= acquisition.MAX_ARTIFACT_BYTES:
                raise ValueError(f"artifact violates size rule: {artifact_name}")
            if metadata["project"] != pair["project"]:
                raise ValueError(f"artifact project mismatch: {artifact_name}")
            if metadata["category"] != pair["category"]:
                raise ValueError(f"artifact category mismatch: {artifact_name}")
            locked_artifacts.setdefault(artifact_name, metadata)
            locked_pair[side] = {
                "artifact": artifact_name,
                "ref": endpoint["ref"],
                "size": actual_size,
                "sha256": actual_sha256,
            }
        locked_pairs.append(locked_pair)

    category_counts = Counter(pair["category"] for pair in effective_pairs)
    split_counts = Counter(pair["split"] for pair in effective_pairs)
    lock = {
        "format": "vcdiff-generality-artifact-lock-v1",
        "frozen_date": "2026-08-23",
        "outcome_state": "frozen before any confirmatory VCDIFF trace",
        "preregistration_sha256": preregistration_sha256,
        "optimizer": preregistration["frozen_oracle"],
        "build_recipes_sha256": actual_recipes,
        "deviations_sha256": acquisition.sha256(DEVIATIONS),
        "deviations": deviations,
        "excluded_pair_ids": sorted(excluded),
        "effective_pair_count": len(effective_pairs),
        "category_counts": dict(sorted(category_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "artifact_count": len(locked_artifacts),
        "artifacts": dict(sorted(locked_artifacts.items())),
        "pairs": locked_pairs,
    }
    encoded = json.dumps(lock, indent=2, sort_keys=True) + "\n"
    LOCK.write_text(encoded)
    digest = acquisition.sha256(LOCK)
    LOCK_HASH.write_text(f"{digest}  benchmark/{LOCK.name}\n")
    print(
        f"frozen {len(effective_pairs)} pairs / {len(locked_artifacts)} artifacts "
        f"sha256={digest}"
    )


if __name__ == "__main__":
    main()
