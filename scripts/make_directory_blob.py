#!/usr/bin/env python3
"""Pack a directory into a deterministic metadata-light binary workload."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

MAGIC = b"directory-blob-v1\n"


def pack_directory(directory: Path, output: Path) -> tuple[int, int, str]:
    directory = directory.resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() or path.is_symlink()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    payload_bytes = 0
    with output.open("wb") as destination:
        destination.write(MAGIC)
        digest.update(MAGIC)
        for path in paths:
            relative = path.relative_to(directory).as_posix().encode(
                "utf-8", "surrogateescape"
            )
            if path.is_symlink():
                kind = b"L"
                payload = os.readlink(path).encode("utf-8", "surrogateescape")
            else:
                kind = b"F"
                payload = path.read_bytes()
            header = (
                kind
                + len(relative).to_bytes(4, "big")
                + len(payload).to_bytes(8, "big")
                + relative
            )
            destination.write(header)
            destination.write(payload)
            digest.update(header)
            digest.update(payload)
            count += 1
            payload_bytes += len(payload)
    return count, payload_bytes, digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    count, payload_bytes, digest = pack_directory(
        arguments.directory, arguments.output.resolve()
    )
    print(
        f"{arguments.output}: files={count} payload={payload_bytes} "
        f"bytes={arguments.output.stat().st_size} sha256={digest}"
    )


if __name__ == "__main__":
    main()
