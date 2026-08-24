#!/usr/bin/env python3
"""Acquire preregistered endpoints without inspecting any VCDIFF trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
PREREGISTRATION = ROOT / "benchmark/preregistration-v1.json"
PREREGISTRATION_HASH = ROOT / "benchmark/preregistration-v1.sha256"
WORK = ROOT / "benchmark_work"
DOWNLOADS = ROOT / "benchmark_downloads"
STATE = WORK / "acquisition-state.json"
DEVIATIONS = ROOT / "benchmark/deviations.jsonl"
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


def run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_locks() -> dict[str, Any]:
    expected = PREREGISTRATION_HASH.read_text().split()[0]
    actual = sha256(PREREGISTRATION)
    if actual != expected:
        raise ValueError(f"preregistration hash drift: {actual} != {expected}")
    document = json.loads(PREREGISTRATION.read_text())
    optimizer = ROOT / document["frozen_oracle"]["optimizer_path"]
    optimizer_actual = sha256(optimizer)
    optimizer_expected = document["frozen_oracle"]["optimizer_sha256"]
    if optimizer_actual != optimizer_expected:
        raise ValueError(
            f"frozen optimizer drift: {optimizer_actual} != {optimizer_expected}"
        )
    return document


def unique_endpoints(
    document: dict[str, Any], categories: set[str], excluded_pairs: set[str]
) -> list[tuple[str, str, dict[str, Any]]]:
    by_artifact: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for pair in document["pairs"]:
        if pair["id"] in excluded_pairs:
            continue
        if pair["category"] not in categories:
            continue
        for side in ("source", "target"):
            endpoint = pair[side]
            artifact = endpoint["artifact"]
            candidate = (pair["project"], pair["category"], endpoint)
            previous = by_artifact.get(artifact)
            if previous is not None and previous != candidate:
                raise ValueError(f"conflicting endpoint definition: {artifact}")
            by_artifact[artifact] = candidate
    return [by_artifact[key] for key in sorted(by_artifact)]


def excluded_pair_ids() -> set[str]:
    result: set[str] = set()
    if not DEVIATIONS.is_file():
        return result
    for line in DEVIATIONS.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        result.update(record.get("affected_pair_ids", []))
    return result


def locator_overrides() -> dict[str, str]:
    result: dict[str, str] = {}
    if not DEVIATIONS.is_file():
        return result
    for line in DEVIATIONS.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("action") == "correct_locator":
            result[record["affected_artifact"]] = record["new_locator"]
    return result


def ensure_repository(project: str, repository: str, commit: str) -> Path:
    directory = WORK / "repos" / project
    if not (directory / ".git").is_dir():
        directory.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--no-tags",
                repository,
                str(directory),
            ]
        )
    remote = subprocess.run(
        ["git", "-C", str(directory), "remote", "get-url", "origin"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if remote != repository:
        raise ValueError(f"repository origin drift for {project}: {remote}")
    present = subprocess.run(
        ["git", "-C", str(directory), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
    ).returncode == 0
    if not present:
        run(
            [
                "git",
                "-C",
                str(directory),
                "fetch",
                "--depth=1",
                "origin",
                commit,
            ]
        )
    actual_type = subprocess.run(
        ["git", "-C", str(directory), "cat-file", "-t", commit],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if actual_type != "commit":
        raise ValueError(f"locator is not a commit: {commit}")
    return directory


def prepare_git_tree(project: str, endpoint: dict[str, Any], artifact: Path) -> None:
    repository = ensure_repository(project, endpoint["repository"], endpoint["locator"])
    revision = endpoint["locator"]
    if endpoint.get("scope"):
        revision = f"{revision}:{endpoint['scope']}"
    run(
        [
            "python3",
            str(ROOT / "scripts/make_git_tree_blob.py"),
            str(repository),
            revision,
            str(artifact),
        ]
    )


def download(url: str) -> Path:
    basename = Path(urlparse(url).path).name or "download.bin"
    name = f"{hashlib.sha256(url.encode()).hexdigest()[:16]}-{basename}"
    destination = DOWNLOADS / name
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    run(
        [
            "curl",
            "-fL",
            "--retry",
            "3",
            "--output",
            str(partial),
            url,
        ]
    )
    os.replace(partial, destination)
    return destination


def safe_relative(name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"unsafe archive member: {name}")
    return Path(*pure.parts)


def extract_zip(archive: Path, directory: Path) -> None:
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            if member.is_dir():
                continue
            relative = safe_relative(member.filename)
            destination = directory / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with handle.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)


def extract_tar(archive: Path, directory: Path) -> None:
    with tarfile.open(archive, "r:*") as handle:
        for member in handle:
            relative = safe_relative(member.name)
            destination = directory / relative
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                os.chmod(destination, member.mode & 0o777)
                continue
            if member.isfile():
                source = handle.extractfile(member)
                if source is None:
                    raise ValueError(f"cannot extract {member.name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                os.chmod(destination, member.mode & 0o777)
                os.utime(destination, (member.mtime, member.mtime))
                continue
            if member.issym():
                try:
                    target = safe_relative(member.linkname)
                except ValueError:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(target)


def prepare_structured(endpoint: dict[str, Any], artifact: Path) -> dict[str, Any]:
    archive = download(endpoint["locator"])
    with tempfile.TemporaryDirectory(prefix="vcdiff-structured-", dir=WORK) as temp:
        directory = Path(temp)
        if endpoint["archive_kind"] == "zip":
            extract_zip(archive, directory)
        elif endpoint["archive_kind"] == "tar.gz":
            extract_tar(archive, directory)
        else:
            raise ValueError(f"unknown archive kind: {endpoint['archive_kind']}")
        run(
            [
                "python3",
                str(ROOT / "scripts/make_directory_blob.py"),
                str(directory),
                str(artifact),
            ]
        )
    return {
        "download_path": str(archive.relative_to(ROOT)),
        "download_size": archive.stat().st_size,
        "download_sha256": sha256(archive),
    }


def prepare_compressed(endpoint: dict[str, Any], artifact: Path) -> dict[str, Any]:
    archive = download(endpoint["locator"])
    artifact.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, artifact)
    return {
        "download_path": str(archive.relative_to(ROOT)),
        "download_size": archive.stat().st_size,
        "download_sha256": sha256(archive),
    }


def read_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {"format": "vcdiff-acquisition-state-v1", "artifacts": {}}
    return json.loads(STATE.read_text())


def write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def prepare(categories: set[str]) -> None:
    document = verify_locks()
    WORK.mkdir(parents=True, exist_ok=True)
    state = read_state()
    endpoints = unique_endpoints(document, categories, excluded_pair_ids())
    overrides = locator_overrides()
    for number, (project, category, endpoint) in enumerate(endpoints, 1):
        endpoint = dict(endpoint)
        if endpoint["artifact"] in overrides:
            endpoint["locator"] = overrides[endpoint["artifact"]]
        artifact = ROOT / endpoint["artifact"]
        print(
            f"[{number}/{len(endpoints)}] {category} {project} {endpoint['ref']}",
            flush=True,
        )
        existing = state["artifacts"].get(endpoint["artifact"])
        if (
            existing is not None
            and artifact.is_file()
            and existing.get("locator") == endpoint["locator"]
            and existing.get("size") == artifact.stat().st_size
            and existing.get("sha256") == sha256(artifact)
        ):
            print("  reuse verified artifact", flush=True)
            continue
        extra: dict[str, Any] = {}
        if category == "source_tree":
            prepare_git_tree(project, endpoint, artifact)
        elif category == "structured":
            extra = prepare_structured(endpoint, artifact)
        elif category == "compressed":
            extra = prepare_compressed(endpoint, artifact)
        else:
            raise ValueError(f"unsupported acquisition category: {category}")
        size = artifact.stat().st_size
        if not 0 < size <= MAX_ARTIFACT_BYTES:
            raise ValueError(f"artifact violates preregistered size rule: {artifact} ({size})")
        state["artifacts"][endpoint["artifact"]] = {
            "project": project,
            "category": category,
            "ref": endpoint["ref"],
            "locator": endpoint["locator"],
            "size": size,
            "sha256": sha256(artifact),
            **extra,
        }
        write_state(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=("source_tree", "structured", "compressed"),
        default=("source_tree", "structured", "compressed"),
    )
    arguments = parser.parse_args()
    prepare(set(arguments.categories))


if __name__ == "__main__":
    main()
