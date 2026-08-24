from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import scipy

from .codec import FileEncoding, build_custom_table, encode_file, encode_file_header
from .decoder import decode_file
from .default_table import DEFAULT_TABLE, PAIR_BANK_CAPACITY, table_to_bytes
from .model import ADD, Atom, Pattern, observed_patterns
from .optimizer import (
    GlobalSelectionResult,
    SelectionResult,
    solve_global_selection,
    solve_selection,
)
from .trace import run_xdelta_trace, sha256_file, trace_document, write_json

XDELTA_CURRENT_COMMIT = "9822b17313263d458b80511b08124971fc0e04fa"
XDELTA_CUSTOM_DECODER_COMMIT = "98bc4523a0c5d1a0743da4261e41a431a66acf2d"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Evaluation:
    physical_slots: int
    selected: tuple[Pattern, ...]
    file_encoding: FileEncoding
    solver: SelectionResult | GlobalSelectionResult | None

    @property
    def file_size(self) -> int:
        return len(self.file_encoding.encoded)

    @property
    def instruction_bytes(self) -> int:
        return sum(window.instruction_length for window in self.file_encoding.windows)

    @property
    def data_bytes(self) -> int:
        return sum(window.data_length for window in self.file_encoding.windows)

    @property
    def address_bytes(self) -> int:
        return sum(window.address_length for window in self.file_encoding.windows)

    def to_dict(self, default: Evaluation) -> dict[str, Any]:
        result: dict[str, Any] = {
            "physical_slots": self.physical_slots,
            "selected_pattern_count": len(self.selected),
            "selected_patterns": [pattern.to_dict() for pattern in self.selected],
            "file_bytes": self.file_size,
            "file_sha256": _sha256_bytes(self.file_encoding.encoded),
            "file_header_bytes": self.file_encoding.file_header_length,
            "nested_table_delta_bytes": self.file_encoding.table_delta_length,
            "instruction_bytes": self.instruction_bytes,
            "data_bytes": self.data_bytes,
            "address_bytes": self.address_bytes,
            "instruction_savings_vs_default": default.instruction_bytes
            - self.instruction_bytes,
            "net_savings_vs_default": default.file_size - self.file_size,
        }
        if self.solver is not None:
            result["solver"] = self.solver.to_dict()
        return result


def _verify_with_decoder(
    decoder: Path, source: Path, patch: Path, expected_target: bytes
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vcdiff-table-opt-") as directory:
        decoded = Path(directory) / "decoded.bin"
        command = [
            str(decoder),
            "-d",
            "-f",
            "-s",
            str(source),
            str(patch),
            str(decoded),
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(
                f"independent decoder failed with {completed.returncode}:\n"
                f"{completed.stderr}"
            )
        decoded_bytes = decoded.read_bytes()
        if decoded_bytes != expected_target:
            raise ValueError("independent decoder output differs from target")
        return {
            "command": [*command[:-1], "<temporary-output>"],
            "returncode": completed.returncode,
            "decoded_size": len(decoded_bytes),
            "decoded_sha256": _sha256_bytes(decoded_bytes),
            "stderr": completed.stderr.strip(),
        }


def _render_report(certificate: dict[str, Any]) -> str:
    baseline = certificate["baseline"]
    default = certificate["default_table_optimum"]
    evaluations = certificate["custom_evaluations"]
    chosen = certificate["global_optimum"]
    target_size = certificate["target"]["size"]
    stock_size = baseline["size"]
    savings = stock_size - chosen["file_bytes"]
    percent = 100.0 * savings / stock_size if stock_size else 0.0
    global_solver = chosen["solver"]
    if chosen["physical_slots"] == 0:
        result_sentence = (
            "The RFC default table is the exact optimum of the restricted family. "
            f"Its patch is {chosen['file_bytes']:,} bytes."
        )
        instruction_sentence = (
            f"The target is {target_size:,} bytes, and the exact default-table reparse is "
            f"{default['file_bytes']:,} bytes. No custom-table header is emitted."
        )
        compatibility_sentence = (
            "The emitted patch uses the RFC default table and was decoded byte-for-byte "
            "by both independent decoders."
        )
    else:
        result_sentence = (
            f"The exact restricted optimum uses {chosen['physical_slots']} physical "
            f"replacement slots and {chosen['selected_pattern_count']} distinct observed "
            f"patterns. Its patch is {chosen['file_bytes']:,} bytes, saving "
            f"{savings:,} bytes ({percent:.4f}%) relative to the stock xdelta3 "
            f"patch of {stock_size:,} bytes."
        )
        instruction_sentence = (
            f"The target is {target_size:,} bytes. The exact default-table reparse is "
            f"{default['file_bytes']:,} bytes. The chosen custom table saves "
            f"{chosen['instruction_savings_vs_default']:,} instruction-section bytes "
            "before paying the table/header cost."
        )
        compatibility_sentence = (
            "The emitted patch follows RFC 3284, including the custom-table length field. "
            "It was decoded byte-for-byte by an untouched historical xdelta3 decoder from "
            "the last commit before generic table support was removed. Current xdelta3 "
            "3.2.x deliberately returns XD3_UNIMPLEMENTED for VCD_CODETABLE, so "
            "compatibility with that particular current decoder is not claimed."
        )

    lines = [
        "# VCDIFF custom code-table fixed-trace result",
        "",
        "## Result",
        "",
        result_sentence,
        "",
        instruction_sentence,
        "",
        "## Global restricted certificate",
        "",
        (
            f"One MILP jointly chose q in 0..{global_solver['max_physical_slots']}, "
            "the installed patterns, and the fixed-trace parse. Its total-patch primal "
            f"and dual bounds are both {global_solver['patch_bytes']:,} bytes with "
            f"reported gap {global_solver['solver_gap']}."
        ),
        "",
        "The bound includes the exact canonical nested table delta, file header, both "
        "length-varint step functions, data and address sections, and window framing.",
        "",
        "## Diagnostic fixed-q sweep",
        "",
        "| Physical slots | Distinct selected | Instruction bytes | Table delta bytes | Patch bytes | Net vs default |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| 0 | 0 | {default['instruction_bytes']} | 0 | "
            f"{default['file_bytes']} | 0 |"
        ),
    ]
    for evaluation in evaluations:
        lines.append(
            f"| {evaluation['physical_slots']} | {evaluation['selected_pattern_count']} | "
            f"{evaluation['instruction_bytes']} | {evaluation['nested_table_delta_bytes']} | "
            f"{evaluation['file_bytes']} | {evaluation['net_savings_vs_default']:+d} |"
        )
    lines.extend(
        [
            "",
            "Every fixed-q row above has equal integer primal and dual instruction-byte "
            "objectives and zero reported MIP gap. The certificate verifier independently "
            "reruns the global MILP and the fixed-table dynamic program.",
            "",
            "## Scope and evidence boundary",
            "",
            "This is an exact result only for the recorded xdelta instruction trace, fixed "
            "RFC default address caches (near=4, same=3), observed implicit-size single/pair "
            "patterns, and the canonical prefix-replacement table family certified here. It is "
            "not a global optimum over all legal 256-entry tables, address-cache dimensions, "
            "string-matcher traces, or table-delta encoders.",
            "",
            compatibility_sentence,
            "",
            "## Pair-local decision",
            "",
            certificate["decision"]["explanation"],
            "",
        ]
    )
    return "\n".join(lines)


def run_study(
    source: Path,
    target: Path,
    output_directory: Path,
    *,
    trace_xdelta: Path,
    custom_table_decoder: Path,
    max_slots: int = 8,
    global_max_slots: int = PAIR_BANK_CAPACITY,
) -> Path:
    source = source.resolve()
    target = target.resolve()
    output_directory = output_directory.resolve()
    trace_xdelta = trace_xdelta.resolve()
    custom_table_decoder = custom_table_decoder.resolve()
    if not source.is_file() or not target.is_file():
        raise FileNotFoundError("source and target must be regular files")
    if not trace_xdelta.is_file() or not custom_table_decoder.is_file():
        raise FileNotFoundError("required xdelta executables are missing")
    if not 1 <= max_slots <= PAIR_BANK_CAPACITY:
        raise ValueError(f"max_slots must be in [1, {PAIR_BANK_CAPACITY}]")
    if not max_slots <= global_max_slots <= PAIR_BANK_CAPACITY:
        raise ValueError(
            "global_max_slots must be between max_slots and "
            f"{PAIR_BANK_CAPACITY}"
        )
    if target.stat().st_size == 0:
        raise ValueError("the restricted study excludes empty targets")
    if target.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("the one-window restricted study is capped at 64 MiB")

    output_directory.mkdir(parents=True, exist_ok=True)
    certificate_path = output_directory / "certificate.json"
    baseline_patch = output_directory / "baseline-xdelta3.vcdiff"
    window_size = max(16 * 1024, target.stat().st_size)
    windows, _ = run_xdelta_trace(
        trace_xdelta,
        source,
        target,
        baseline_patch,
        window_size=window_size,
    )
    if len(windows) != 1:
        raise ValueError(
            f"exact full-patch comparison requires one target window; got {len(windows)}"
        )

    trace_path = output_directory / "trace.json"
    write_json(trace_path, trace_document(source, target, baseline_patch, windows))
    source_bytes = source.read_bytes()
    target_bytes = target.read_bytes()

    default_encoding = encode_file(windows, source_bytes, target_bytes)
    if decode_file(default_encoding.encoded, source_bytes) != target_bytes:
        raise AssertionError("independent decoder rejected default-table reparse")
    if default_encoding.encoded != baseline_patch.read_bytes():
        raise AssertionError(
            "recorded trace does not reproduce the stock xdelta3 patch byte-for-byte"
        )
    default_evaluation = Evaluation(0, tuple(), default_encoding, None)
    default_patch = output_directory / "default-table-optimal.vcdiff"
    default_patch.write_bytes(default_encoding.encoded)

    candidates = observed_patterns(windows)
    cached: dict[int, Evaluation] = {}
    if certificate_path.is_file():
        previous = json.loads(certificate_path.read_text())
        compatible = (
            previous.get("format")
            in {
                "vcdiff-custom-table-certificate-v1",
                "vcdiff-custom-table-certificate-v2",
            }
            and previous.get("source", {}).get("sha256") == _sha256_bytes(source_bytes)
            and previous.get("target", {}).get("sha256") == _sha256_bytes(target_bytes)
            and previous.get("trace", {}).get("sha256") == sha256_file(trace_path)
        )
        if compatible:
            for value in previous.get("custom_evaluations", []):
                solver = SelectionResult.from_dict(value["solver"])
                physical_slots = solver.physical_slots
                table = build_custom_table(solver.selected, physical_slots)
                encoding = encode_file(
                    windows,
                    source_bytes,
                    target_bytes,
                    table=table,
                    physical_slots=physical_slots,
                )
                if (
                    sum(window.instruction_length for window in encoding.windows)
                    != solver.instruction_bytes
                    or _sha256_bytes(encoding.encoded) != value["file_sha256"]
                ):
                    raise ValueError("cached sweep entry failed deterministic replay")
                cached[physical_slots] = Evaluation(
                    physical_slots, solver.selected, encoding, solver
                )

    evaluations: list[Evaluation] = []
    diagnostic_slot_range = range(1, max_slots + 1) if candidates else ()
    for physical_slots in diagnostic_slot_range:
        if physical_slots in cached:
            evaluation = cached[physical_slots]
        else:
            solver = solve_selection(
                windows, physical_slots, candidates=candidates
            )
            table = build_custom_table(solver.selected, physical_slots)
            encoding = encode_file(
                windows,
                source_bytes,
                target_bytes,
                table=table,
                physical_slots=physical_slots,
            )
            if (
                sum(window.instruction_length for window in encoding.windows)
                != solver.instruction_bytes
            ):
                raise AssertionError(
                    "independent fixed-table dynamic program disagrees with MILP optimum"
                )
            if decode_file(encoding.encoded, source_bytes) != target_bytes:
                raise AssertionError("independent decoder rejected custom patch")
            evaluation = Evaluation(
                physical_slots, solver.selected, encoding, solver
            )
        evaluations.append(evaluation)

    # The canonical nested delta has a content-independent length for fixed q.
    # Use a pattern absent from the RFC table to obtain all header lengths
    # without reparsing the (potentially large) target 93 times.
    probe_pattern = Pattern((Atom(ADD, 255),))
    file_header_lengths = [len(encode_file_header()[0])]
    for physical_slots in range(1, global_max_slots + 1):
        probe_table = build_custom_table((probe_pattern,), physical_slots)
        header, _ = encode_file_header(probe_table, physical_slots)
        file_header_lengths.append(len(header))

    global_solver = solve_global_selection(
        windows[0],
        global_max_slots,
        file_header_lengths=file_header_lengths,
        data_bytes=default_evaluation.data_bytes,
        address_bytes=default_evaluation.address_bytes,
        candidates=candidates,
    )
    if global_solver.physical_slots == 0:
        chosen_table = DEFAULT_TABLE
        chosen_encoding = default_encoding
    else:
        chosen_table = build_custom_table(
            global_solver.selected, global_solver.physical_slots
        )
        chosen_encoding = encode_file(
            windows,
            source_bytes,
            target_bytes,
            table=chosen_table,
            physical_slots=global_solver.physical_slots,
        )
    chosen = Evaluation(
        global_solver.physical_slots,
        global_solver.selected,
        chosen_encoding,
        global_solver,
    )
    if chosen.instruction_bytes != global_solver.instruction_bytes:
        raise AssertionError(
            "fixed-table dynamic program does not attain the global MILP bound"
        )
    if chosen.file_size != global_solver.patch_bytes:
        raise AssertionError(
            "emitted patch length does not equal the certified total-patch bound"
        )
    if decode_file(chosen.file_encoding.encoded, source_bytes) != target_bytes:
        raise AssertionError("independent decoder rejected globally optimal patch")

    custom_patch = output_directory / "restricted-optimal.vcdiff"
    table_path = output_directory / "restricted-code-table.bin"
    parse_path = output_directory / "restricted-parse.json"
    custom_patch.write_bytes(chosen.file_encoding.encoded)
    if chosen.physical_slots == 0:
        if table_path.exists():
            table_path.unlink()
    else:
        table_path.write_bytes(table_to_bytes(chosen_table))
    parse_document = {
        "format": "vcdiff-restricted-parse-v1",
        "windows": [
            {
                "index": trace_window.index,
                "logical_instruction_count": len(trace_window.instructions),
                "instruction_bytes": encoded_window.instruction_length,
                "tokens": [
                    token.to_dict() for token in encoded_window.parse.tokens
                ],
            }
            for trace_window, encoded_window in zip(
                windows, chosen.file_encoding.windows, strict=True
            )
        ],
    }
    write_json(parse_path, parse_document)
    decoder_verification = _verify_with_decoder(
        custom_table_decoder, source, custom_patch, target_bytes
    )

    baseline_size = baseline_patch.stat().st_size
    savings = baseline_size - chosen.file_size
    savings_fraction = savings / baseline_size if baseline_size else 0.0
    threshold = 0.003
    decision = {
        "threshold_fraction": threshold,
        "savings_bytes_vs_stock": savings,
        "savings_fraction_vs_stock": savings_fraction,
        "passes_pair_threshold": savings_fraction >= threshold,
        "explanation": (
            "This pair clears the provisional 0.3% continuation threshold. A corpus-level "
            "decision still requires repeated gains on independent real workloads."
            if savings_fraction >= threshold
            else "This pair does not clear the provisional 0.3% continuation threshold. "
            "It is one data point, not by itself a corpus-level stop result."
        ),
    }

    default_dict = default_evaluation.to_dict(default_evaluation)
    custom_dicts = [evaluation.to_dict(default_evaluation) for evaluation in evaluations]
    chosen_dict = chosen.to_dict(default_evaluation)
    table_artifact = (
        {"table_path": None, "table_sha256": None}
        if chosen.physical_slots == 0
        else {
            "table_path": str(table_path),
            "table_sha256": sha256_file(table_path),
        }
    )
    certificate: dict[str, Any] = {
        "format": "vcdiff-custom-table-certificate-v2",
        "restriction": {
            "trace": "fixed logical xdelta3 trace before opcode pairing",
            "target_windows": 1,
            "candidate_patterns": (
                "all observed exact singles/pairs with implicit sizes <=255; "
                "dominated candidates removed only by exact presolve"
            ),
            "table_family": (
                "replace opcodes 163..(163+q-1), duplicate a selected pattern in unused "
                "physical slots, preserve all other RFC default entries"
            ),
            "physical_slots_globally_certified": [0, global_max_slots],
            "physical_slots_diagnostic_sweep": [1, max_slots],
            "near_cache": 4,
            "same_cache": 3,
            "table_delta": "canonical six-block ADD/COPY encoding against the RFC default table",
        },
        "tools": {
            "optimizer": {
                "api": "scipy.optimize.milp (HiGHS)",
                "scipy_version": scipy.__version__,
                "requested_mip_relative_gap": 0.0,
            },
            "trace_xdelta": {
                "path": str(trace_xdelta),
                "binary_sha256": sha256_file(trace_xdelta),
                "upstream_commit": XDELTA_CURRENT_COMMIT,
                "instrumentation": "patches/xdelta3-trace.patch",
            },
            "unchanged_custom_table_decoder": {
                "path": str(custom_table_decoder),
                "binary_sha256": sha256_file(custom_table_decoder),
                "upstream_commit": XDELTA_CUSTOM_DECODER_COMMIT,
            },
        },
        "source": {
            "path": str(source),
            "size": len(source_bytes),
            "sha256": _sha256_bytes(source_bytes),
        },
        "target": {
            "path": str(target),
            "size": len(target_bytes),
            "sha256": _sha256_bytes(target_bytes),
        },
        "trace": {
            "path": str(trace_path),
            "sha256": sha256_file(trace_path),
            "instruction_count": sum(len(window.instructions) for window in windows),
            "observed_candidate_count": len(candidates),
        },
        "baseline": {
            "path": str(baseline_patch),
            "size": baseline_size,
            "sha256": sha256_file(baseline_patch),
        },
        "default_table_optimum": {
            **default_dict,
            "path": str(default_patch),
            "byte_identical_to_baseline": True,
        },
        "custom_evaluations": custom_dicts,
        "global_optimum": {
            **chosen_dict,
            "patch_path": str(custom_patch),
            "parse_path": str(parse_path),
            "parse_sha256": sha256_file(parse_path),
            "parse_token_count": sum(
                len(window.parse.tokens) for window in chosen.file_encoding.windows
            ),
            **table_artifact,
        },
        "verification": {
            "independent_python_decoder": {
                "decoded_size": len(target_bytes),
                "decoded_sha256": _sha256_bytes(target_bytes),
            },
            "unchanged_xdelta_decoder": decoder_verification,
        },
        "decision": decision,
    }
    write_json(certificate_path, certificate)
    (output_directory / "report.md").write_text(_render_report(certificate))
    return certificate_path
