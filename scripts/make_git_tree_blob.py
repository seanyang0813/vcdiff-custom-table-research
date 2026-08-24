#!/usr/bin/env python3
"""Pack a Git tree into a deterministic metadata-light binary workload."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tarfile
from pathlib import Path

MAGIC = b"git-tree-blob-v1\n"


def pack_tree(repository: Path, revision: str, output: Path) -> tuple[int, int, str]:
    command = ["git", "-C", str(repository), "archive", "--format=tar", revision]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    if process.stdout is None:
        raise AssertionError("git archive stdout pipe missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    payload_bytes = 0
    digest = hashlib.sha256()
    with output.open("wb") as destination:
        destination.write(MAGIC)
        digest.update(MAGIC)
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise RuntimeError(f"cannot read archive member {member.name}")
                    payload = extracted.read()
                    kind = b"F"
                elif member.issym():
                    payload = member.linkname.encode("utf-8", "surrogateescape")
                    kind = b"L"
                else:
                    continue
                name = member.name.encode("utf-8", "surrogateescape")
                record_header = (
                    kind
                    + len(name).to_bytes(4, "big")
                    + len(payload).to_bytes(8, "big")
                    + name
                )
                destination.write(record_header)
                destination.write(payload)
                digest.update(record_header)
                digest.update(payload)
                count += 1
                payload_bytes += len(payload)
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)
    return count, payload_bytes, digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("revision")
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    count, payload_bytes, digest = pack_tree(
        arguments.repository.resolve(), arguments.revision, arguments.output.resolve()
    )
    print(
        f"{arguments.output}: files={count} payload={payload_bytes} "
        f"bytes={os.path.getsize(arguments.output)} sha256={digest}"
    )


if __name__ == "__main__":
    main()

