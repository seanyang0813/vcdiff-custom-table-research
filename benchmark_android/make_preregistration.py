#!/usr/bin/env python3
"""Freeze the public Android DEX study before downloading candidate APKs."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "benchmark_android/preregistration-v1.json"
HASH_OUTPUT = ROOT / "benchmark_android/preregistration-v1.sha256"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked(path: str) -> dict[str, str]:
    return {"path": path, "sha256": sha256(ROOT / path)}


def main() -> None:
    value = {
        "format": "vcdiff-public-android-dex-preregistration-v1",
        "registered_date": str(date.today()),
        "status": "locked before any candidate APK was traced or optimized",
        "research_question": (
            "Do real public Android DEX release updates exhibit material exact "
            "custom-VCDIFF-code-table gains on the frozen xdelta trace?"
        ),
        "evidence_boundary": (
            "This is a public compiled-code surrogate study. It makes no claim about "
            "Meta-internal Superpack workloads, implementation, or performance."
        ),
        "locked_inputs": {
            "candidate_generator": locked("benchmark_android/make_candidate_manifest.py"),
            "candidate_manifest": locked("benchmark_android/candidate-manifest-v1.json"),
            "corpus_preparer": locked("benchmark_android/prepare_corpus.py"),
            "repo_index": locked("benchmark_android/index/repo-index-v2.json"),
            "repo_index_signature": locked("benchmark_android/index/repo-index-v2.json.asc"),
            "archive_index": locked("benchmark_android/index/archive-index-v2.json"),
            "archive_index_signature": locked("benchmark_android/index/archive-index-v2.json.asc"),
            "fdroid_public_key": locked("benchmark_android/index/fdroid-admin-public-key.asc"),
            "scip_amendment": locked("benchmark/scip-validity-amendment-v2.json"),
        },
        "index_authentication": {
            "entry_manifest_hashes_match": True,
            "detached_signatures_verified": True,
            "documented_primary_key_fingerprint": "37D2C98789D8311948394E3E41E7044E1DBA2E89",
            "signing_subkey_fingerprint": "802A9799016112346E1FEFF47A029E54DD5DCE7A",
            "documentation": "https://f-droid.org/docs/Verifying_Downloaded_APK/",
        },
        "selection": {
            "target_pairs": 40,
            "unit": "one old-to-new update from each distinct F-Droid package/project",
            "candidate_order": (
                "fixed candidate-manifest order; accept until 40 valid pairs; never "
                "replace or reorder based on a VCDIFF outcome"
            ),
            "apk_requirements": [
                "download SHA-256 and byte size equal the signed index",
                "valid ZIP with CRC-valid members",
                "one or more root classes.dex/classesN.dex members with standard DEX magic",
                "at most 8 DEX members per APK",
                "total raw DEX bytes per APK in [256 KiB, 12 MiB]",
            ],
            "failure_policy": (
                "record download, hash, ZIP, DEX, size, and count failures verbatim; "
                "continue in frozen rank order"
            ),
        },
        "dex_bundle_format": {
            "magic": "VCDIFF-DEX-BUNDLE-v1 followed by NUL",
            "member_order": "classes.dex, classes2.dex, ... by numeric suffix",
            "member_record": "u32 big-endian ASCII-name length, name, u64 big-endian data length, raw DEX",
            "pairing_rule": (
                "the complete old APK DEX bundle is the VCDIFF source and the complete "
                "new APK DEX bundle is the target; added/removed multidex members remain visible"
            ),
        },
        "oracle_protocol": {
            "baseline": "frozen instrumented xdelta trace and stock patch settings",
            "optimizer_scope": "frozen q=0..93 restricted table family",
            "proof": "locked exact-SCIP amendment v2",
            "required_checks": [
                "SCIP exact optimal status and equal integral primal/dual",
                "independent integral DP attainment",
                "emitted patch byte count equals bound",
                "strict Python decoder reconstructs target bundle",
                "unchanged historical xdelta decoder reconstructs target bundle",
            ],
            "limits": "the exact-SCIP amendment limits apply independently to every pair",
            "status_policy": "timeouts, OOMs, failures, and unsolved cases remain visible and receive no exact label",
        },
        "record_per_pair": [
            "stock and exact-oracle bytes",
            "absolute and percentage saving",
            "q and selected pattern count",
            "logical instruction count and DEX sizes/counts",
            "wall time, peak RSS, solver nodes/status, model and artifact hashes",
            "both decoder results",
        ],
        "decision_gates": {
            "minimum_exact_coverage": 30,
            "material_pair_threshold_percent": 1.0,
            "material_class_gate": (
                "proceed to predictor/table-bank analysis only if at least 30 pairs "
                "are exact and at least 25% of exact pairs save >=1.0%; otherwise "
                "report negative or insufficient evidence"
            ),
            "table_bank_gate": (
                "on project-held-out evaluation, a tiny bank must recover >=70% of "
                "aggregate exact-oracle saving and should target 80%"
            ),
            "production_gate": (
                "requires material DEX oracle signal, held-out bank recovery, monotonic "
                "fallback, and acceptable measured overhead"
            ),
        },
        "forbidden_before_corpus_freeze": [
            "VCDIFF trace generation",
            "stock patch measurement",
            "custom-table optimization",
            "outcome-dependent candidate replacement",
        ],
    }
    OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    HASH_OUTPUT.write_text(f"{sha256(OUTPUT)}  {OUTPUT.relative_to(ROOT)}\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
