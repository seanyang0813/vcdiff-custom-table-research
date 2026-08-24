#!/usr/bin/env python3
"""Publish a compact tracked summary of the large-pair integer-dual result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PAIR_ID = "fdroid-com.jstappdev.e6bflightcomputer-19-to-20"
CERTIFICATE = ROOT / f"benchmark_android/artifacts/{PAIR_ID}/certificate.json"
REPLAY = ROOT / "results/android/e6b-fixed-q-bound-replay-v1.json"
JSON_OUTPUT = ROOT / "results/android/e6b-integer-dual-summary-v1.json"
MD_OUTPUT = ROOT / "results/android/e6b-integer-dual-summary-v1.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    certificate = json.loads(CERTIFICATE.read_text())
    replay = json.loads(REPLAY.read_text())
    optimum = certificate["global_optimum"]
    result = certificate["result"]
    verification = certificate["verification"]
    value = {
        "format": "vcdiff-android-integer-dual-summary-v1",
        "status": certificate["status"],
        "evidence_boundary": certificate["evidence_boundary"],
        "pair_id": certificate["android_study"]["pair_id"],
        "logical_instruction_count": certificate["trace"][
            "logical_instruction_count"
        ],
        "baseline_bytes": certificate["baseline"]["bytes"],
        "oracle_bytes": optimum["file_bytes"],
        "physical_slots": optimum["physical_slots"],
        "instruction_bytes": optimum["instruction_bytes"],
        "saving_bytes": result["saving_bytes_vs_stock"],
        "saving_percent": result["saving_percent_vs_stock"],
        "passes_preregistered_one_percent_pair_threshold": result[
            "passes_preregistered_one_percent_pair_threshold"
        ],
        "proof_of_exhaustion": {
            "q_domain": [0, 93],
            "covered_q_count": verification["fixed_q_row_count"],
            "direct_rational_lower_bound_rows": verification[
                "direct_rational_lower_bound_rows"
            ],
            "monotonicity_derived_lower_bound_rows": verification[
                "monotonicity_derived_lower_bound_rows"
            ],
            "attained_custom_rows": verification["attained_custom_rows"],
            "all_nonincumbent_bounds_eliminate_incumbent": verification[
                "all_nonincumbent_lower_bounds_eliminate_incumbent"
            ],
            "method": certificate["restriction"]["proof_of_exhaustion"],
        },
        "independent_bound_replay": {
            "path": str(REPLAY.relative_to(ROOT)),
            "sha256": sha256(REPLAY),
            "q_range": replay["q_range"],
            "replayed_exact_count": replay["replayed_exact_count"],
        },
        "chosen_patch": {
            "sha256": optimum["file_sha256"],
            "python_decoder_sha256": verification["chosen_patch_python_decoder"][
                "decoded_sha256"
            ],
            "unchanged_xdelta_decoder_sha256": verification[
                "chosen_patch_unchanged_xdelta_decoder"
            ]["decoded_sha256"],
        },
        "full_certificate": {
            "path": str(CERTIFICATE.relative_to(ROOT)),
            "sha256": sha256(CERTIFICATE),
            "note": "local certificate references frozen APK-derived artifacts excluded from Git",
        },
        "retained_operational_stops": [
            "results/android/continuous-relaxation-stop-v1.json",
            "results/android/strengthened-root-lp-global-presolve-v1.json",
        ],
        "corpus_gate": {
            "exact_pairs_after_this_result": 2,
            "minimum_required_exact_pairs": 30,
            "predictor_or_table_bank_authorized": False,
        },
    }
    JSON_OUTPUT.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    MD_OUTPUT.write_text(
        "\n".join(
            [
                "# Integer-dual scaling result on public Android DEX",
                "",
                f"Stock patch: {value['baseline_bytes']:,} bytes. Exact restricted "
                f"q=0..93 optimum: {value['oracle_bytes']:,} bytes at "
                f"q={value['physical_slots']}. Saving: {value['saving_bytes']:,} "
                f"bytes ({value['saving_percent']:.4f}%).",
                "",
                "The exact proof combines q=0 dynamic programming, independently "
                "replayed rational LP duals for q=80..92, monotonic transfer from "
                "q=80 to q=1..79, and a binary q=93 witness attained by the integral "
                "parser and decoded by both decoders.",
                "",
                "This is the second exact pair in a frozen 40-project public F-Droid "
                "surrogate. The preregistered minimum is 30 exact pairs, so the result "
                "does not authorize predictors, a reusable table bank, deployment "
                "claims, or any claim about Meta/Superpack data.",
                "",
            ]
        )
    )
    print(JSON_OUTPUT)
    print(MD_OUTPUT)


if __name__ == "__main__":
    main()
