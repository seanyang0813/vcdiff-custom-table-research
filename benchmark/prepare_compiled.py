#!/usr/bin/env python3
"""Build the preregistered uncompressed compiled-code endpoints."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import prepare_artifacts as acquisition


ROOT = acquisition.ROOT
WORK = acquisition.WORK
CURRENT = WORK / "compile/current"
LOGS = WORK / "build-logs"
RECIPES = ROOT / "benchmark/build-recipes-v1.json"
RECIPES_HASH = ROOT / "benchmark/build-recipes-v1.sha256"

CURL_URLS = {
    "curl-8_11_0": "https://curl.se/download/curl-8.11.0.tar.gz",
    "curl-8_11_1": "https://curl.se/download/curl-8.11.1.tar.gz",
    "curl-8_12_0": "https://curl.se/download/curl-8.12.0.tar.gz",
}

SQLITE_URLS = {
    "version-3.47.0": "https://www.sqlite.org/2024/sqlite-autoconf-3470000.tar.gz",
    "version-3.47.1": "https://www.sqlite.org/2024/sqlite-autoconf-3470100.tar.gz",
    "version-3.48.0": "https://www.sqlite.org/2025/sqlite-autoconf-3480000.tar.gz",
}

COMMANDS = {
    "zstd": [["make", "-j2", "CC=gcc", "V=0", "lib-release", "zstd-release"]],
    "redis": [
        [
            "make",
            "-j2",
            "MALLOC=libc",
            "BUILD_TLS=no",
            "OPTIMIZATION=-O2",
            "CFLAGS=-g0",
        ]
    ],
    "curl": [
        [
            "./configure",
            "--without-ssl",
            "--without-libpsl",
            "--without-zstd",
            "--without-brotli",
            "--without-libidn2",
            "--disable-static",
            "--enable-shared",
            "--disable-manual",
            "--disable-docs",
        ],
        ["make", "-j2"],
    ],
    "sqlite": [
        [
            "./configure",
            "--disable-readline",
            "--disable-static",
            "--enable-shared",
        ],
        ["make", "-j2"],
    ],
    "xdelta": [
        [
            "gcc",
            "-Wall",
            "-Wshadow",
            "-fno-builtin",
            "-O3",
            "xdelta3/xdelta3.c",
            "-lm",
            "-o",
            "xdelta3/xdelta3",
            "-DSIZEOF_SIZE_T=8",
            "-DREGRESSION_TEST=1",
            "-DSECONDARY_DJW=1",
            "-DSECONDARY_FGK=1",
            "-DXD3_DEBUG=0",
            "-DXD3_MAIN=1",
            "-DXD3_POSIX=1",
            "-DXD3_USE_LARGEFILE64=1",
        ]
    ],
}


def verify_recipe_lock() -> str:
    expected = RECIPES_HASH.read_text().split()[0]
    actual = acquisition.sha256(RECIPES)
    if actual != expected:
        raise ValueError(f"build recipe drift: {actual} != {expected}")
    return actual


def reset_current() -> Path:
    resolved = CURRENT.resolve()
    expected_parent = (WORK / "compile").resolve()
    if resolved.parent != expected_parent or resolved.name != "current":
        raise ValueError(f"refusing to reset unexpected build directory: {resolved}")
    if CURRENT.exists():
        shutil.rmtree(CURRENT)
    source = CURRENT / "src"
    source.mkdir(parents=True)
    return source


def extract_git(project: str, endpoint: dict[str, Any], source: Path) -> None:
    repository = acquisition.ensure_repository(
        project, endpoint["repository"], endpoint["locator"]
    )
    archive = CURRENT / "source.tar"
    acquisition.run(
        [
            "git",
            "-C",
            str(repository),
            "archive",
            "--format=tar",
            "--output",
            str(archive),
            endpoint["locator"],
        ]
    )
    acquisition.extract_tar(archive, source)


def normalize_archive_root(unpack: Path, source: Path) -> None:
    entries = list(unpack.iterdir())
    root = entries[0] if len(entries) == 1 and entries[0].is_dir() else unpack
    for item in list(root.iterdir()):
        os.replace(item, source / item.name)


def extract_release(url: str, source: Path) -> dict[str, Any]:
    archive = acquisition.download(url)
    unpack = CURRENT / "unpack"
    unpack.mkdir()
    acquisition.extract_tar(archive, unpack)
    normalize_archive_root(unpack, source)
    return {
        "build_source_url": url,
        "build_source_size": archive.stat().st_size,
        "build_source_sha256": acquisition.sha256(archive),
    }


def prepare_source(project: str, endpoint: dict[str, Any], source: Path) -> dict[str, Any]:
    if project == "curl":
        return extract_release(CURL_URLS[endpoint["ref"]], source)
    if project == "sqlite":
        return extract_release(SQLITE_URLS[endpoint["ref"]], source)
    extract_git(project, endpoint, source)
    return {
        "build_source_repository": endpoint["repository"],
        "build_source_commit": endpoint["locator"],
    }


def run_build(project: str, source: Path, ref: str) -> Path:
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{project}-{ref.replace('/', '_')}.log"
    environment = dict(os.environ)
    environment.update({"LC_ALL": "C", "SOURCE_DATE_EPOCH": "0", "TZ": "UTC"})
    with log_path.open("w") as log:
        for command in COMMANDS[project]:
            log.write("$ " + " ".join(command) + "\n")
            log.flush()
            completed = subprocess.run(
                command,
                cwd=source,
                env=environment,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"build failed for {project} {ref}; see {log_path}"
                )
    return log_path


def copy_regular(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source.resolve(), destination)
    shutil.copymode(source.resolve(), destination)


def copy_library_glob(pattern: str, destination: Path) -> None:
    matches = sorted(Path(path) for path in glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(pattern)
    destination.mkdir(parents=True, exist_ok=True)
    for source in matches:
        target = destination / source.name
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif source.is_file():
            copy_regular(source, target)


def collect_outputs(project: str, source: Path) -> Path:
    staging = CURRENT / "staging"
    staging.mkdir()
    if project == "zstd":
        copy_regular(source / "zstd", staging / "bin/zstd")
        copy_library_glob(str(source / "lib/libzstd.so*"), staging / "lib")
    elif project == "redis":
        for name in ("redis-server", "redis-cli", "redis-benchmark"):
            copy_regular(source / f"src/{name}", staging / f"bin/{name}")
    elif project == "curl":
        copy_regular(source / "src/.libs/curl", staging / "bin/curl")
        copy_library_glob(str(source / "lib/.libs/libcurl.so*"), staging / "lib")
    elif project == "sqlite":
        copy_regular(source / "sqlite3", staging / "bin/sqlite3")
        copy_library_glob(str(source / ".libs/libsqlite3.so*"), staging / "lib")
    elif project == "xdelta":
        copy_regular(source / "xdelta3/xdelta3", staging / "bin/xdelta3")
    else:
        raise ValueError(project)
    for path in sorted(staging.rglob("*")):
        if path.is_file() and not path.is_symlink():
            subprocess.run(
                ["strip", "--strip-debug", str(path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    return staging


def tool_output(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, text=True, capture_output=True
    ).stdout.splitlines()[0]


def toolchain() -> dict[str, str]:
    return {
        "gcc": tool_output(["gcc", "--version"]),
        "make": tool_output(["make", "--version"]),
        "strip": tool_output(["strip", "--version"]),
        "libc": tool_output(["ldd", "--version"]),
    }


def build_all() -> None:
    document = acquisition.verify_locks()
    recipe_hash = verify_recipe_lock()
    state = acquisition.read_state()
    endpoints = acquisition.unique_endpoints(document, {"compiled"}, set())
    fingerprint = toolchain()
    for number, (project, category, endpoint) in enumerate(endpoints, 1):
        artifact = ROOT / endpoint["artifact"]
        print(f"[{number}/{len(endpoints)}] compiled {project} {endpoint['ref']}", flush=True)
        existing = state["artifacts"].get(endpoint["artifact"])
        if (
            existing is not None
            and artifact.is_file()
            and existing.get("locator") == endpoint["locator"]
            and existing.get("build_recipes_sha256") == recipe_hash
            and existing.get("toolchain") == fingerprint
            and existing.get("size") == artifact.stat().st_size
            and existing.get("sha256") == acquisition.sha256(artifact)
        ):
            print("  reuse verified artifact", flush=True)
            continue
        source = reset_current()
        source_record = prepare_source(project, endpoint, source)
        log_path = run_build(project, source, endpoint["ref"])
        staging = collect_outputs(project, source)
        acquisition.run(
            [
                "python3",
                str(ROOT / "scripts/make_directory_blob.py"),
                str(staging),
                str(artifact),
            ]
        )
        size = artifact.stat().st_size
        if not 0 < size <= acquisition.MAX_ARTIFACT_BYTES:
            raise ValueError(f"compiled artifact violates size rule: {artifact} ({size})")
        state["artifacts"][endpoint["artifact"]] = {
            "project": project,
            "category": category,
            "ref": endpoint["ref"],
            "locator": endpoint["locator"],
            "size": size,
            "sha256": acquisition.sha256(artifact),
            "build_recipe": endpoint["build_recipe"],
            "build_recipes_sha256": recipe_hash,
            "build_log": str(log_path.relative_to(ROOT)),
            "build_log_sha256": acquisition.sha256(log_path),
            "toolchain": fingerprint,
            **source_record,
        }
        acquisition.write_state(state)


if __name__ == "__main__":
    build_all()
