from __future__ import annotations

import argparse
import json
from pathlib import Path

from .study import run_study
from .verify import verify_certificate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vcdiff-table-opt",
        description="Exact restricted RFC 3284 custom code-table experiments",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    study = subparsers.add_parser("study", help="trace and optimize one file pair")
    study.add_argument("--source", type=Path, required=True)
    study.add_argument("--target", type=Path, required=True)
    study.add_argument("--output", type=Path, required=True)
    study.add_argument("--trace-xdelta", type=Path, required=True)
    study.add_argument("--custom-table-decoder", type=Path, required=True)
    study.add_argument("--max-slots", type=int, default=8)
    study.add_argument("--global-max-slots", type=int, default=93)

    verify = subparsers.add_parser("verify", help="replay a certificate")
    verify.add_argument("--certificate", type=Path, required=True)
    verify.add_argument("--custom-table-decoder", type=Path)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.command == "study":
        certificate = run_study(
            arguments.source,
            arguments.target,
            arguments.output,
            trace_xdelta=arguments.trace_xdelta,
            custom_table_decoder=arguments.custom_table_decoder,
            max_slots=arguments.max_slots,
            global_max_slots=arguments.global_max_slots,
        )
        print(certificate)
    elif arguments.command == "verify":
        result = verify_certificate(
            arguments.certificate,
            custom_table_decoder=arguments.custom_table_decoder,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        raise AssertionError("unreachable command")


if __name__ == "__main__":
    main()
