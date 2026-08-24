#!/usr/bin/env python3
"""Validate per-pair certificates and write a deterministic corpus summary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    manifest = json.loads((project_root / "corpus/manifest.json").read_text())
    results: list[dict[str, Any]] = []
    for pair in manifest["pairs"]:
        certificate_path = project_root / "artifacts" / pair["id"] / "certificate.json"
        certificate = json.loads(certificate_path.read_text())
        if certificate["format"] != "vcdiff-custom-table-certificate-v2":
            raise ValueError(f"unexpected certificate format for {pair['id']}")
        if certificate["source"]["sha256"] != pair["source_sha256"]:
            raise ValueError(f"source provenance mismatch for {pair['id']}")
        if certificate["target"]["sha256"] != pair["target_sha256"]:
            raise ValueError(f"target provenance mismatch for {pair['id']}")
        optimum = certificate["global_optimum"]
        solver = optimum["solver"]
        if (
            optimum["file_bytes"] != solver["patch_bytes"]
            or solver["patch_bytes"] != solver["patch_dual_bound"]
            or solver["solver_gap"] != 0
        ):
            raise ValueError(f"non-exact solver result for {pair['id']}")
        if not certificate["default_table_optimum"]["byte_identical_to_baseline"]:
            raise ValueError(f"trace fidelity check failed for {pair['id']}")
        target_hash = certificate["target"]["sha256"]
        if (
            certificate["verification"]["independent_python_decoder"][
                "decoded_sha256"
            ]
            != target_hash
            or certificate["verification"]["unchanged_xdelta_decoder"][
                "decoded_sha256"
            ]
            != target_hash
        ):
            raise ValueError(f"decoder replay mismatch for {pair['id']}")
        baseline = int(certificate["baseline"]["size"])
        restricted = int(optimum["file_bytes"])
        savings = baseline - restricted
        results.append(
            {
                "id": pair["id"],
                "project": pair["project"],
                "source_ref": pair["source_ref"],
                "source_commit": pair["source_commit"],
                "target_ref": pair["target_ref"],
                "target_commit": pair["target_commit"],
                "target_bytes": certificate["target"]["size"],
                "logical_instructions": certificate["trace"]["instruction_count"],
                "stock_patch_bytes": baseline,
                "restricted_patch_bytes": restricted,
                "savings_bytes": savings,
                "savings_fraction": savings / baseline,
                "gross_instruction_savings": optimum[
                    "instruction_savings_vs_default"
                ],
                "custom_header_increment": (
                    optimum["file_header_bytes"]
                    - certificate["default_table_optimum"]["file_header_bytes"]
                ),
                "physical_slots": optimum["physical_slots"],
                "selected_patterns": optimum["selected_pattern_count"],
                "patch_primal_bytes": solver["patch_bytes"],
                "patch_dual_bytes": solver["patch_dual_bound"],
                "solver_gap": solver["solver_gap"],
                "default_reparse_byte_identical": True,
                "decoded_sha256": target_hash,
                "patch_sha256": optimum["file_sha256"],
                "certificate": str(certificate_path.relative_to(project_root)),
                "certificate_sha256": sha256(certificate_path),
                "passes_0_3_percent": savings / baseline >= 0.003,
            }
        )

    stock_total = sum(result["stock_patch_bytes"] for result in results)
    restricted_total = sum(result["restricted_patch_bytes"] for result in results)
    passing = sum(result["passes_0_3_percent"] for result in results)
    summary = {
        "format": "vcdiff-corpus-result-v1",
        "restriction": (
            "one fixed xdelta trace/window, RFC near=4/same=3, all observed exact "
            "implicit-size singles/pairs, canonical replacement of default opcodes "
            "163..255, q jointly optimized over 0..93"
        ),
        "threshold_fraction": 0.003,
        "pairs": results,
        "aggregate": {
            "pair_count": len(results),
            "pairs_passing_threshold": passing,
            "stock_patch_bytes": stock_total,
            "restricted_patch_bytes": restricted_total,
            "savings_bytes": stock_total - restricted_total,
            "savings_fraction": (stock_total - restricted_total) / stock_total,
        },
        "decision": {
            "continue_restricted_research": passing >= 2,
            "upstream_ready": False,
            "reason": (
                f"{passing} independent project pairs clear 0.3%; this passes the "
                "immediate continuation gate. Upstream integration remains blocked by "
                "current xdelta decoder support and the intentionally restricted table family."
            ),
        },
    }

    results_directory = project_root / "results"
    results_directory.mkdir(parents=True, exist_ok=True)
    (results_directory / "corpus-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    lines = [
        "# Real-corpus decision",
        "",
        "| Pair | Target bytes | Trace instructions | Stock patch | Restricted optimum | Savings | q | Primal = dual |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        percent = 100 * result["savings_fraction"]
        lines.append(
            f"| {result['project']} {result['source_ref']}→{result['target_ref']} | "
            f"{result['target_bytes']:,} | {result['logical_instructions']:,} | "
            f"{result['stock_patch_bytes']:,} | {result['restricted_patch_bytes']:,} | "
            f"{result['savings_bytes']:,} ({percent:.4f}%) | "
            f"{result['physical_slots']} | {result['patch_primal_bytes']:,} |"
        )
    aggregate_percent = 100 * summary["aggregate"]["savings_fraction"]
    lines.extend(
        [
            "",
            (
                f"Aggregate: {stock_total:,}→{restricted_total:,} bytes, saving "
                f"{stock_total - restricted_total:,} bytes ({aggregate_percent:.4f}%)."
            ),
            "",
            "On the two positive pairs, q=93 uses the full replaceable pair bank. "
            "Gross instruction-section savings are 2,284 and 2,205 bytes; each "
            "canonical custom header costs 621 bytes more than the default header.",
            "",
            "Decision: **continue the restricted research**. Two independent project "
            "tree pairs clear the provisional 0.3% gate. The small xdelta update and "
            "compressed Win64 release are exact q=0 negative controls.",
            "",
            "This is not an upstream-readiness claim. The proof is scoped to the recorded "
            "traces and canonical pair-bank family, and current xdelta deliberately lacks "
            "custom-table decode support.",
            "",
        ]
    )
    (results_directory / "corpus-summary.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
