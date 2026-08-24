#!/usr/bin/env python3
"""Exhaustively combine q=0..93 fixed-q proofs into one exact pair label."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import vcdiff_opt.optimizer as optimizer_module
from benchmark.integer_dual_adapter import IntegerDualReplayAdapter, _standardize
from vcdiff_opt.codec import build_custom_table, encode_file, encode_file_header
from vcdiff_opt.decoder import decode_file
from vcdiff_opt.default_table import table_to_bytes
from vcdiff_opt.model import ADD, Atom, Pattern, WindowTrace
from vcdiff_opt.optimizer import SelectionResult
from vcdiff_opt.varint import varint_size


ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmark_android/corpus-lock-v1.json"
PREREG = ROOT / "benchmark_android/preregistration-v1.json"
EXECUTION = ROOT / "benchmark_android/execution-lock-v1.json"
STATE = ROOT / "benchmark_android/work/oracle-state-v1.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def verify_external_decoder(
    decoder: Path, source: Path, patch: Path, target: bytes
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vcdiff-integer-dual-") as directory:
        decoded = Path(directory) / "decoded.bin"
        command = [
            str(decoder.resolve()),
            "-d",
            "-f",
            "-s",
            str(source.resolve()),
            str(patch.resolve()),
            str(decoded),
        ]
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"external decoder failed with {completed.returncode}: "
                f"{completed.stderr}"
            )
        value = decoded.read_bytes()
        if value != target:
            raise ValueError("external decoder output differs from the target")
        return {
            "command": [*command[:-1], "<temporary-output>"],
            "returncode": completed.returncode,
            "decoded_bytes": len(value),
            "decoded_sha256": sha256_bytes(value),
            "stderr": completed.stderr.strip(),
        }


def fixed_q_patch_lower_bound(
    window: WindowTrace,
    q: int,
    instruction_lower: int,
    data_bytes: int,
    address_bytes: int,
) -> tuple[int, int]:
    probe = Pattern((Atom(ADD, 255),))
    table = build_custom_table((probe,), q)
    header_bytes = len(encode_file_header(table, q)[0])
    delta_constant = (
        varint_size(window.target_length)
        + 1
        + varint_size(data_bytes)
        + varint_size(address_bytes)
        + data_bytes
        + address_bytes
    )
    window_prefix = 1
    if window.source_used:
        window_prefix += varint_size(window.source_length)
        window_prefix += varint_size(window.source_position)
    instruction_varint = varint_size(instruction_lower)
    delta_bytes = delta_constant + instruction_varint + instruction_lower
    full = (
        header_bytes
        + window_prefix
        + delta_constant
        + instruction_lower
        + instruction_varint
        + varint_size(delta_bytes)
    )
    return full, header_bytes


def capture_fixed_q_model_fingerprint(
    windows: tuple[WindowTrace, ...], q: int
) -> str:
    """Rebuild the canonical fixed-q model without asking any solver to run."""

    fingerprints: list[str] = []

    def capture(
        *,
        c: Any,
        integrality: Any,
        bounds: Any,
        constraints: Any,
        options: dict[str, Any] | None = None,
    ) -> Any:
        del options
        fingerprints.append(
            _standardize(
                c=c,
                integrality=integrality,
                bounds=bounds,
                constraints=constraints,
            ).fingerprint
        )
        return SimpleNamespace(
            success=False,
            status="fingerprint_only",
            message="captured fixed-q model fingerprint without solving",
            x=None,
            fun=None,
        )

    original_milp = optimizer_module.milp
    optimizer_module.milp = capture
    try:
        try:
            optimizer_module.solve_selection(windows, q)
        except RuntimeError as error:
            if "fingerprint_only" not in str(error):
                raise
        else:
            raise AssertionError("fingerprint capture unexpectedly solved the model")
    finally:
        optimizer_module.milp = original_milp
    if len(fingerprints) != 1:
        raise AssertionError("fingerprint capture did not see exactly one model")
    return fingerprints[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair-id", required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--fixed-q-root", type=Path, required=True)
    parser.add_argument("--fixed-q-bound-root", type=Path, required=True)
    parser.add_argument("--bound-replay-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--custom-table-decoder", type=Path, required=True)
    parser.add_argument("--update-state", action="store_true")
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    corpus = json.loads(CORPUS.read_text())
    pair = next(
        value for value in corpus["pairs"] if value["pair_id"] == arguments.pair_id
    )
    trace_document = json.loads(arguments.trace.read_text())
    windows = tuple(
        WindowTrace.from_dict(value) for value in trace_document["windows"]
    )
    if len(windows) != 1:
        raise ValueError("exact fixed-q aggregation requires one target window")
    source_path = Path(trace_document["source"]["path"])
    target_path = Path(trace_document["target"]["path"])
    source = source_path.read_bytes()
    target = target_path.read_bytes()
    if sha256_bytes(source) != pair["old"]["bundle"]["sha256"]:
        raise ValueError("source bundle does not match the frozen corpus")
    if sha256_bytes(target) != pair["new"]["bundle"]["sha256"]:
        raise ValueError("target bundle does not match the frozen corpus")

    default_encoding = encode_file(windows, source, target)
    baseline_path = Path(trace_document["baseline_patch"]["path"])
    if default_encoding.encoded != baseline_path.read_bytes():
        raise AssertionError("default-table replay differs from the stock patch")
    rows: list[dict[str, Any]] = [
        {
            "physical_slots": 0,
            "instruction_bytes": sum(
                value.instruction_length for value in default_encoding.windows
            ),
            "patch_bytes": len(default_encoding.encoded),
            "patch_sha256": sha256_bytes(default_encoding.encoded),
            "proof_kind": "exact default-table dynamic program",
        }
    ]
    trace_hash = sha256(arguments.trace)
    for q in range(80, 93):
        bound_path = (
            arguments.fixed_q_bound_root / f"{q:03d}" / "lower-bound.json"
        )
        if not bound_path.is_file():
            raise FileNotFoundError(
                f"missing fixed-q lower bound for q={q}: {bound_path}"
            )
        document = json.loads(bound_path.read_text())
        if (
            document.get("status") != "exact_lower_bound_only"
            or int(document.get("physical_slots", -1)) != q
            or document["trace"]["sha256"] != trace_hash
        ):
            raise ValueError(f"fixed-q lower-bound metadata mismatch at q={q}")
        bound = document["bound_calls"][0]
        proof_metadata = Path(bound["proof_metadata_path"])
        proof_vectors = Path(bound["proof_vectors_path"])
        if not proof_metadata.is_absolute():
            proof_metadata = ROOT / proof_metadata
        if not proof_vectors.is_absolute():
            proof_vectors = ROOT / proof_vectors
        metadata = json.loads(proof_metadata.read_text())
        if (
            sha256(proof_vectors) != bound["proof_vectors_sha256"]
            or metadata["vectors_sha256"] != bound["proof_vectors_sha256"]
            or metadata["model_fingerprint"] != bound["model_fingerprint"]
            or int(metadata["exact_dual_numerator"])
            != int(bound["exact_dual_numerator"])
            or int(metadata["exact_dual_denominator"])
            != int(bound["exact_dual_denominator"])
        ):
            raise ValueError(f"fixed-q rational-dual proof hash mismatch at q={q}")
        rows.append(
            {
                "physical_slots": q,
                "instruction_bytes_integer_lower_bound": int(
                    document["instruction_bytes_integer_lower_bound"]
                ),
                "patch_bytes_integer_lower_bound": int(
                    document["full_patch_bytes_integer_lower_bound"]
                ),
                "proof_kind": "exact rational LP dual lower bound",
                "exact_dual_numerator": int(bound["exact_dual_numerator"]),
                "exact_dual_denominator": int(bound["exact_dual_denominator"]),
                "model_fingerprint": bound["model_fingerprint"],
                "proof_metadata_path": str(proof_metadata),
                "proof_metadata_sha256": sha256(proof_metadata),
                "proof_vectors_path": str(proof_vectors),
                "proof_vectors_sha256": sha256(proof_vectors),
                "bound_path": str(bound_path),
                "bound_sha256": sha256(bound_path),
            }
        )

    anchor = next(row for row in rows if row["physical_slots"] == 80)
    anchor_instruction_lower = int(
        anchor["instruction_bytes_integer_lower_bound"]
    )
    data_bytes = sum(value.data_length for value in default_encoding.windows)
    address_bytes = sum(
        value.address_length for value in default_encoding.windows
    )
    for q in range(1, 80):
        patch_lower, header_bytes = fixed_q_patch_lower_bound(
            windows[0],
            q,
            anchor_instruction_lower,
            data_bytes,
            address_bytes,
        )
        rows.append(
            {
                "physical_slots": q,
                "instruction_bytes_integer_lower_bound": anchor_instruction_lower,
                "patch_bytes_integer_lower_bound": patch_lower,
                "file_header_bytes": header_bytes,
                "proof_kind": "monotonicity transfer from q=80 rational dual",
                "anchor_physical_slots": 80,
                "anchor_exact_dual_numerator": anchor["exact_dual_numerator"],
                "anchor_exact_dual_denominator": anchor[
                    "exact_dual_denominator"
                ],
                "anchor_model_fingerprint": anchor["model_fingerprint"],
                "monotonicity_argument": (
                    "Any q table can be represented at q+1 by retaining its selected "
                    "patterns and adding the one newly overwritten RFC pair pattern; "
                    "therefore optimal instruction bytes are nonincreasing in q."
                ),
            }
        )

    replay_ledger = json.loads(arguments.bound_replay_ledger.read_text())
    if not (
        replay_ledger.get("format")
        == "vcdiff-fixed-q-rational-dual-replay-ledger-v1"
        and replay_ledger.get("q_range") == [80, 92]
        and int(replay_ledger.get("replayed_exact_count", -1)) == 13
    ):
        raise ValueError("fixed-q bound replay ledger is incomplete")
    replay_by_q = {
        int(value["physical_slots"]): value for value in replay_ledger["rows"]
    }
    for row in rows:
        q = int(row["physical_slots"])
        if q < 80:
            continue
        replayed = replay_by_q[q]
        if not (
            int(replayed["exact_dual_numerator"])
            == int(row["exact_dual_numerator"])
            and int(replayed["exact_dual_denominator"])
            == int(row["exact_dual_denominator"])
            and replayed["model_fingerprint"] == row["model_fingerprint"]
            and int(replayed["full_patch_bytes_integer_lower_bound"])
            == int(row["patch_bytes_integer_lower_bound"])
        ):
            raise ValueError(f"independent replay ledger mismatch at q={q}")

    chosen_q = 93
    result_path = arguments.fixed_q_root / "093" / "result.json"
    document = json.loads(result_path.read_text())
    if (
        int(document.get("physical_slots", -1)) != chosen_q
        or document["trace"]["sha256"] != trace_hash
    ):
        raise ValueError("q=93 attained-result metadata mismatch")
    chosen_selection = SelectionResult.from_dict(document["selection"])
    chosen_proof: dict[str, Any]
    if document.get("format") == "vcdiff-android-fixed-q-integer-dual-result-v1":
        if document.get("status") != "exact_fixed_q_only":
            raise ValueError("q=93 integer-dual result is not exact")
        constructor = document["constructor_calls"][0]
        replay = document["replay_calls"][0]
        if not (
            chosen_selection.instruction_bytes
            == chosen_selection.solver_dual_bound
            == int(constructor["exact_dual_bound"])
            == int(replay["exact_dual_bound"])
        ):
            raise ValueError("q=93 dual/witness replay mismatch")
        independent_replay = IntegerDualReplayAdapter(result_path.parent / "proof")
        original_milp = optimizer_module.milp
        optimizer_module.milp = independent_replay
        try:
            independently_replayed_selection = optimizer_module.solve_selection(
                windows, chosen_q
            )
        finally:
            optimizer_module.milp = original_milp
        if independently_replayed_selection != chosen_selection:
            raise AssertionError("independent q=93 proof replay changed the selection")
        proof_metadata = Path(constructor["proof_metadata_path"])
        proof_vectors = Path(constructor["proof_vectors_path"])
        if not proof_metadata.is_absolute():
            proof_metadata = ROOT / proof_metadata
        if not proof_vectors.is_absolute():
            proof_vectors = ROOT / proof_vectors
        metadata = json.loads(proof_metadata.read_text())
        if (
            sha256(proof_vectors) != constructor["proof_vectors_sha256"]
            or metadata["vectors_sha256"] != constructor["proof_vectors_sha256"]
            or metadata["model_fingerprint"] != constructor["model_fingerprint"]
        ):
            raise ValueError("q=93 attained proof hash mismatch")
        chosen_proof = {
            "proof_kind": "exact rational LP dual plus binary witness",
            "model_fingerprint": constructor["model_fingerprint"],
            "proof_metadata_path": str(proof_metadata),
            "proof_metadata_sha256": sha256(proof_metadata),
            "proof_vectors_path": str(proof_vectors),
            "proof_vectors_sha256": sha256(proof_vectors),
        }
    elif document.get("format") == "vcdiff-android-fixed-q-strengthened-scip-v1":
        if document.get("status") != "exact_fixed_q":
            raise ValueError("q=93 strengthened-SCIP result is not exact")
        calls = document.get("solver_calls", [])
        fingerprints = document.get("model_fingerprints", [])
        if len(calls) != 1 or len(fingerprints) != 1:
            raise ValueError("q=93 strengthened-SCIP proof metadata is incomplete")
        call = calls[0]
        reconstructed_fingerprint = capture_fixed_q_model_fingerprint(
            windows, chosen_q
        )
        if not (
            call.get("exact_mode") is True
            and call.get("returned_solution_source") == "exact_scip"
            and int(call["objective"])
            == int(call["best_bound"])
            == chosen_selection.instruction_bytes
            == chosen_selection.solver_dual_bound
            and fingerprints[0] == reconstructed_fingerprint
        ):
            raise ValueError("q=93 exact-SCIP/model-fingerprint replay mismatch")
        chosen_proof = {
            "proof_kind": "exact aggregate-free SCIP plus integral DP witness",
            "model_fingerprint": reconstructed_fingerprint,
            "mps_sha256": call["mps_sha256"],
            "scip_version": call["scip_version"],
            "exact_mode": True,
            "solver_nodes": int(call["nodes"]),
            "solver_objective": int(call["objective"]),
            "solver_best_bound": int(call["best_bound"]),
        }
    else:
        raise ValueError("unsupported q=93 attained-result format")
    chosen_table = build_custom_table(chosen_selection.selected, chosen_q)
    chosen_encoding = encode_file(
        windows, source, target, table=chosen_table, physical_slots=chosen_q
    )
    if decode_file(chosen_encoding.encoded, source) != target:
        raise AssertionError("Python decoder rejected q=93 attained patch")
    chosen_instruction_bytes = sum(
        value.instruction_length for value in chosen_encoding.windows
    )
    if (
        chosen_instruction_bytes != chosen_selection.instruction_bytes
        or len(chosen_encoding.encoded) != int(document["attained_patch"]["bytes"])
        or sha256_bytes(chosen_encoding.encoded)
        != document["attained_patch"]["sha256"]
    ):
        raise AssertionError("q=93 attained-patch replay mismatch")
    chosen_row = {
        "physical_slots": chosen_q,
        "instruction_bytes": chosen_instruction_bytes,
        "patch_bytes": len(chosen_encoding.encoded),
        "patch_sha256": sha256_bytes(chosen_encoding.encoded),
        "selected_pattern_count": len(chosen_selection.selected),
        **chosen_proof,
        "result_path": str(result_path),
        "result_sha256": sha256(result_path),
    }
    rows.append(chosen_row)
    incumbent = len(chosen_encoding.encoded)
    for row in rows:
        q = int(row["physical_slots"])
        if q == chosen_q:
            continue
        lower = int(
            row.get("patch_bytes_integer_lower_bound", row.get("patch_bytes", 0))
        )
        if lower < incumbent:
            raise ValueError(
                f"q={q} lower bound {lower} does not eliminate incumbent {incumbent}"
            )
    rows.sort(key=lambda value: int(value["physical_slots"]))

    patch_path = arguments.output / "restricted-optimal.vcdiff"
    patch_path.write_bytes(chosen_encoding.encoded)
    table_path = arguments.output / "restricted-code-table.bin"
    table_path.write_bytes(table_to_bytes(chosen_table))
    parse_path = arguments.output / "restricted-parse.json"
    parse_document = {
        "format": "vcdiff-restricted-parse-v1",
        "windows": [
            {
                "index": trace_window.index,
                "logical_instruction_count": len(trace_window.instructions),
                "instruction_bytes": encoded_window.instruction_length,
                "tokens": [token.to_dict() for token in encoded_window.parse.tokens],
            }
            for trace_window, encoded_window in zip(
                windows, chosen_encoding.windows, strict=True
            )
        ],
    }
    parse_path.write_text(json.dumps(parse_document, indent=2, sort_keys=True) + "\n")
    external = verify_external_decoder(
        arguments.custom_table_decoder, source_path, patch_path, target
    )
    baseline_bytes = len(default_encoding.encoded)
    oracle_bytes = len(chosen_encoding.encoded)
    saving_bytes = baseline_bytes - oracle_bytes
    saving_percent = 100.0 * saving_bytes / baseline_bytes
    certificate_format = (
        "vcdiff-public-android-dex-certificate-v2-integer-dual"
        if document.get("format")
        == "vcdiff-android-fixed-q-integer-dual-result-v1"
        else "vcdiff-public-android-dex-certificate-v3-composite-exact"
    )
    proof_backend = (
        "q=80..92 replayed rational LP lower bounds; q=80 monotonicity "
        f"transfer to q=1..79; q=93 {chosen_proof['proof_kind']}; "
        "q=0 exact DP"
    )
    proof_of_exhaustion = (
        "q=0 exact default-table DP; q=80..92 replayed rational LP lower "
        "bounds; q=80 monotonicity transfers its instruction lower bound "
        "to q=1..79; every resulting full-patch lower bound is at or above "
        "the q=93 exact rational-dual plus binary-witness incumbent"
        if document.get("format")
        == "vcdiff-android-fixed-q-integer-dual-result-v1"
        else (
            "q=0 exact default-table DP; q=80..92 replayed rational LP lower "
            "bounds; q=80 monotonicity transfers its instruction lower bound "
            "to q=1..79; every resulting full-patch lower bound is at or above "
            f"the q=93 incumbent attained by {chosen_proof['proof_kind']}"
        )
    )
    certificate = {
        "format": certificate_format,
        "status": "exact_global_q_0_through_93",
        "evidence_boundary": (
            "Exact for the frozen public F-Droid DEX-bundle surrogate and restricted "
            "canonical table family only; no Meta or Superpack claim."
        ),
        "android_study": {
            "pair_id": pair["pair_id"],
            "package_id": pair["package_id"],
            "project_name": pair.get("project_name"),
            "source_code": pair["source_code"],
            "candidate_rank": pair["candidate_rank"],
            "old_release": pair["old"]["release"],
            "new_release": pair["new"]["release"],
            "preregistration_sha256": sha256(PREREG),
            "corpus_lock_sha256": sha256(CORPUS),
            "execution_lock_sha256": sha256(EXECUTION),
        },
        "restriction": {
            "trace": "fixed logical xdelta3 trace before opcode pairing",
            "table_family": (
                "replace opcodes 163..(163+q-1), q in every integer 0..93"
            ),
            "proof_of_exhaustion": proof_of_exhaustion,
        },
        "source": {
            "path": str(source_path),
            "bytes": len(source),
            "sha256": sha256_bytes(source),
        },
        "target": {
            "path": str(target_path),
            "bytes": len(target),
            "sha256": sha256_bytes(target),
        },
        "trace": {
            "path": str(arguments.trace),
            "sha256": trace_hash,
            "logical_instruction_count": sum(
                len(window.instructions) for window in windows
            ),
        },
        "baseline": {
            "path": str(baseline_path),
            "bytes": baseline_bytes,
            "sha256": sha256_bytes(default_encoding.encoded),
        },
        "fixed_q_exhaustive_rows": rows,
        "global_optimum": {
            "physical_slots": chosen_q,
            "instruction_bytes": chosen_row["instruction_bytes"],
            "file_bytes": oracle_bytes,
            "file_sha256": sha256_bytes(chosen_encoding.encoded),
            "patch_path": str(patch_path),
            "table_path": None if table_path is None else str(table_path),
            "table_sha256": None if table_path is None else sha256(table_path),
            "parse_path": str(parse_path),
            "parse_sha256": sha256(parse_path),
            "parse_token_count": sum(
                len(window.parse.tokens) for window in chosen_encoding.windows
            ),
        },
        "result": {
            "saving_bytes_vs_stock": saving_bytes,
            "saving_percent_vs_stock": saving_percent,
            "passes_preregistered_one_percent_pair_threshold": saving_percent >= 1.0,
        },
        "verification": {
            "fixed_q_row_count": len(rows),
            "expected_fixed_q_row_count": 94,
            "direct_rational_lower_bound_rows": 13,
            "monotonicity_derived_lower_bound_rows": 79,
            "attained_custom_rows": 1,
            "all_nonincumbent_lower_bounds_eliminate_incumbent": True,
            "independent_bound_replay_ledger": {
                "path": str(arguments.bound_replay_ledger),
                "sha256": sha256(arguments.bound_replay_ledger),
                "replayed_exact_count": replay_ledger["replayed_exact_count"],
            },
            "chosen_patch_python_decoder": {
                "decoded_bytes": len(target),
                "decoded_sha256": sha256_bytes(target),
            },
            "chosen_patch_unchanged_xdelta_decoder": external,
        },
    }
    certificate_path = arguments.output / "certificate.json"
    certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    report = "\n".join(
        [
            "# Exact composite fixed-q Android result",
            "",
            f"Stock patch: {baseline_bytes:,} bytes. Exact q=0..93 optimum: "
            f"{oracle_bytes:,} bytes at q={chosen_q}. Saving: {saving_bytes:,} bytes "
            f"({saving_percent:.4f}%).",
            "",
            "All 94 physical-slot counts were covered. q=80..92 have replayed exact "
            "rational-dual lower bounds; q=80 transfers monotonically to q=1..79; "
            f"q=93 uses {chosen_proof['proof_kind']}, integral DP attainment, and "
            "decoded bytes.",
            "",
            "This is one public F-Droid DEX-bundle pair, not a corpus conclusion or "
            "a claim about Meta/Superpack data.",
            "",
        ]
    )
    (arguments.output / "report.md").write_text(report)

    if arguments.update_state:
        state = json.loads(STATE.read_text())
        state_row = {
            "status": "complete",
            "proof_backend": proof_backend,
            "certificate": str(certificate_path.resolve().relative_to(ROOT)),
            "certificate_sha256": sha256(certificate_path),
            "logical_instructions": sum(len(window.instructions) for window in windows),
            "baseline_bytes": baseline_bytes,
            "oracle_bytes": oracle_bytes,
            "saving_bytes": saving_bytes,
            "saving_percent": saving_percent,
            "physical_slots": chosen_q,
            "fixed_q_direct_exact_lower_bound_count": 13,
            "fixed_q_monotonicity_derived_bound_count": 79,
            "fixed_q_attained_exact_count": 1,
            "fixed_q_total_with_default": 94,
            "finished_utc": datetime.now(timezone.utc).isoformat(),
        }
        if pair["pair_id"] == "fdroid-com.jstappdev.e6bflightcomputer-19-to-20":
            state_row["prior_scip_scaling_stop_retained"] = (
                "results/android/continuous-relaxation-stop-v1.json"
            )
        state["pairs"][pair["pair_id"]] = state_row
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    print(certificate_path)


if __name__ == "__main__":
    main()
