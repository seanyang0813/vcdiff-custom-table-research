from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .codec import build_custom_table, encode_file, encode_file_header
from .decoder import decode_file
from .default_table import DEFAULT_TABLE, table_to_bytes
from .model import ADD, Atom, Pattern, WindowTrace, observed_patterns
from .optimizer import solve_global_selection, solve_selection
from .study import _verify_with_decoder
from .trace import sha256_file


def verify_certificate(
    certificate_path: Path,
    *,
    custom_table_decoder: Path | None = None,
) -> dict[str, Any]:
    certificate_path = certificate_path.resolve()
    certificate = json.loads(certificate_path.read_text())
    certificate_format = certificate.get("format")
    if certificate_format not in {
        "vcdiff-custom-table-certificate-v1",
        "vcdiff-custom-table-certificate-v2",
    }:
        raise ValueError("unsupported certificate format")

    chosen_key = (
        "global_optimum"
        if certificate_format == "vcdiff-custom-table-certificate-v2"
        else "chosen_custom"
    )
    chosen = certificate[chosen_key]

    source_path = Path(certificate["source"]["path"])
    target_path = Path(certificate["target"]["path"])
    trace_path = Path(certificate["trace"]["path"])
    baseline_path = Path(certificate["baseline"]["path"])
    default_patch_path = Path(certificate["default_table_optimum"]["path"])
    patch_path = Path(chosen["patch_path"])
    table_path = None if chosen["table_path"] is None else Path(chosen["table_path"])
    required_paths = [
        source_path,
        target_path,
        trace_path,
        baseline_path,
        default_patch_path,
        patch_path,
    ]
    parse_path = None
    if certificate_format == "vcdiff-custom-table-certificate-v2":
        parse_path = Path(chosen["parse_path"])
        required_paths.append(parse_path)
    if table_path is not None:
        required_paths.append(table_path)
    for path in required_paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    checks = [
        (source_path, certificate["source"]["sha256"]),
        (target_path, certificate["target"]["sha256"]),
        (trace_path, certificate["trace"]["sha256"]),
        (baseline_path, certificate["baseline"]["sha256"]),
        (
            default_patch_path,
            certificate["default_table_optimum"]["file_sha256"],
        ),
        (patch_path, chosen["file_sha256"]),
    ]
    if table_path is not None:
        checks.append((table_path, chosen["table_sha256"]))
    if parse_path is not None:
        checks.append((parse_path, chosen["parse_sha256"]))
    for path, expected in checks:
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")

    source = source_path.read_bytes()
    target = target_path.read_bytes()
    patch = patch_path.read_bytes()
    if len(source) != int(certificate["source"]["size"]):
        raise ValueError("source byte count differs from certificate")
    if len(target) != int(certificate["target"]["size"]):
        raise ValueError("target byte count differs from certificate")
    if len(patch) != int(chosen["file_bytes"]):
        raise ValueError("patch byte count differs from certificate")
    if decode_file(patch, source, expected_target_size=len(target)) != target:
        raise ValueError("independent decoder output mismatch")

    trace_document = json.loads(trace_path.read_text())
    if (
        trace_document["source"]["sha256"] != certificate["source"]["sha256"]
        or trace_document["target"]["sha256"]
        != certificate["target"]["sha256"]
        or trace_document["baseline_patch"]["sha256"]
        != certificate["baseline"]["sha256"]
    ):
        raise ValueError("trace provenance differs from certificate")
    windows = tuple(WindowTrace.from_dict(value) for value in trace_document["windows"])
    default_encoding = encode_file(windows, source, target)
    if default_encoding.encoded != default_patch_path.read_bytes():
        raise ValueError("default-table artifact is not the canonical trace reparse")
    if default_encoding.encoded != baseline_path.read_bytes():
        raise ValueError("default-table reparse is not byte-identical to stock xdelta3")
    physical_slots = int(chosen["physical_slots"])
    selected = tuple(Pattern.from_dict(value) for value in chosen["selected_patterns"])
    if physical_slots == 0:
        if selected or table_path is not None:
            raise ValueError("default-table optimum has unexpected table data")
        table = DEFAULT_TABLE
    else:
        if table_path is None:
            raise ValueError("custom-table optimum is missing its table artifact")
        table = build_custom_table(selected, physical_slots)
        if table_path.read_bytes() != table_to_bytes(table):
            raise ValueError("code-table artifact does not match selected patterns")
    regenerated = encode_file(
        windows,
        source,
        target,
        table=table,
        physical_slots=physical_slots,
    )
    if regenerated.encoded != patch:
        raise ValueError("patch is not the canonical encoding claimed by the certificate")
    if parse_path is not None:
        claimed_parse = json.loads(parse_path.read_text())
        expected_parse = {
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
                    windows, regenerated.windows, strict=True
                )
            ],
        }
        if claimed_parse != expected_parse:
            raise ValueError("parse ledger does not match the canonical DP parse")
        if sum(
            len(window["tokens"]) for window in claimed_parse["windows"]
        ) != int(chosen["parse_token_count"]):
            raise ValueError("parse-token count differs from certificate")

    claimed_instruction_bytes = int(chosen["solver"]["instruction_bytes"])
    if (
        sum(window.instruction_length for window in regenerated.windows)
        != claimed_instruction_bytes
    ):
        raise ValueError("fixed-table DP does not attain certified lower bound")

    if certificate_format == "vcdiff-custom-table-certificate-v2":
        max_slots = int(chosen["solver"]["max_physical_slots"])
        probe_pattern = Pattern((Atom(ADD, 255),))
        file_header_lengths = [len(encode_file_header()[0])]
        for q in range(1, max_slots + 1):
            probe_table = build_custom_table((probe_pattern,), q)
            header, _ = encode_file_header(probe_table, q)
            file_header_lengths.append(len(header))
        solver = solve_global_selection(
            windows[0],
            max_slots,
            file_header_lengths=file_header_lengths,
            data_bytes=sum(w.data_length for w in default_encoding.windows),
            address_bytes=sum(w.address_length for w in default_encoding.windows),
            candidates=observed_patterns(windows),
        )
        claimed_primal = int(chosen["solver"]["patch_bytes"])
        claimed_dual = int(chosen["solver"]["patch_dual_bound"])
        if solver.patch_bytes != claimed_primal or solver.patch_dual_bound != claimed_dual:
            raise ValueError("replayed global patch bound differs from certificate")
        if len(patch) != claimed_primal:
            raise ValueError("claimed global lower bound differs from patch length")
        result_fields = {
            "patch_primal": claimed_primal,
            "patch_dual": solver.patch_dual_bound,
            "instruction_bytes": claimed_instruction_bytes,
            "solver_gap": solver.solver_gap,
        }
    else:
        solver = solve_selection(
            windows,
            physical_slots,
            candidates=observed_patterns(windows),
        )
        if solver.instruction_bytes != claimed_instruction_bytes:
            raise ValueError("replayed solver optimum differs from certificate")
        result_fields = {
            "instruction_primal": claimed_instruction_bytes,
            "instruction_dual": solver.solver_dual_bound,
            "solver_gap": solver.solver_gap,
        }

    decoder_result = None
    if custom_table_decoder is not None:
        decoder_result = _verify_with_decoder(
            custom_table_decoder.resolve(), source_path, patch_path, target
        )
    return {
        "status": "verified",
        "certificate": str(certificate_path),
        "patch_bytes": len(patch),
        "decoded_sha256": certificate["target"]["sha256"],
        **result_fields,
        "unchanged_decoder": decoder_result,
    }
