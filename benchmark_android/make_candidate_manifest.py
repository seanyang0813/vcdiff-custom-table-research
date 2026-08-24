#!/usr/bin/env python3
"""Build an outcome-blind ordered F-Droid Android candidate manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
REPO_INDEX = ROOT / "benchmark_android/index/repo-index-v2.json"
ARCHIVE_INDEX = ROOT / "benchmark_android/index/archive-index-v2.json"
OUTPUT = ROOT / "benchmark_android/candidate-manifest-v1.json"
SEED = "vcdiff-public-dex-preregistered-v1"
MAX_CANDIDATES = 80


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release(value: dict[str, Any], section: str) -> dict[str, Any] | None:
    manifest = value.get("manifest", {})
    file = value.get("file", {})
    name = file.get("name")
    code = manifest.get("versionCode")
    version_name = manifest.get("versionName")
    signers = tuple(manifest.get("signer", {}).get("sha256", []))
    native = tuple(manifest.get("nativecode", []))
    size = file.get("size")
    if not (
        isinstance(name, str)
        and name.endswith(".apk")
        and isinstance(code, int)
        and isinstance(version_name, str)
        and version_name
        and isinstance(size, int)
        and 1_000_000 <= size <= 25_000_000
        and isinstance(file.get("sha256"), str)
        and len(file["sha256"]) == 64
        and signers
        and not native
        and not value.get("releaseChannels")
    ):
        return None
    return {
        "section": section,
        "filename": name.lstrip("/"),
        "sha256": file["sha256"],
        "size": size,
        "version_code": code,
        "version_name": version_name,
        "added": value.get("added"),
        "signers_sha256": list(signers),
    }


def main() -> None:
    indices = {
        "repo": json.loads(REPO_INDEX.read_text()),
        "archive": json.loads(ARCHIVE_INDEX.read_text()),
    }
    packages: dict[str, dict[str, Any]] = {}
    for section, index in indices.items():
        for package_id, package in index["packages"].items():
            collected = packages.setdefault(
                package_id,
                {"metadata": package.get("metadata", {}), "versions": {}},
            )
            if not collected["metadata"] and package.get("metadata"):
                collected["metadata"] = package["metadata"]
            for digest, value in package.get("versions", {}).items():
                collected["versions"].setdefault(digest, (value, section))

    eligible: list[dict[str, Any]] = []
    exclusion_counts: dict[str, int] = {}
    for package_id, package in packages.items():
        source_code = package["metadata"].get("sourceCode")
        if not isinstance(source_code, str) or not source_code.startswith("https://"):
            exclusion_counts["no_https_source_code"] = (
                exclusion_counts.get("no_https_source_code", 0) + 1
            )
            continue
        releases = [
            result
            for value, section in package["versions"].values()
            if (result := release(value, section)) is not None
        ]
        by_code: dict[int, list[dict[str, Any]]] = {}
        for value in releases:
            by_code.setdefault(value["version_code"], []).append(value)
        # Ambiguous universal APKs at one versionCode are not resolved by
        # filename or size.  Exclude that code before choosing adjacent
        # eligible universal releases.
        unique = [values[0] for _, values in sorted(by_code.items()) if len(values) == 1]
        if len(unique) < 2:
            exclusion_counts["fewer_than_two_unambiguous_releases"] = (
                exclusion_counts.get("fewer_than_two_unambiguous_releases", 0) + 1
            )
            continue
        old, new = unique[-2:]
        if old["signers_sha256"] != new["signers_sha256"]:
            exclusion_counts["signer_changed"] = exclusion_counts.get("signer_changed", 0) + 1
            continue
        rank = hashlib.sha256(f"{SEED}\0{package_id}".encode()).hexdigest()
        eligible.append(
            {
                "rank_sha256": rank,
                "package_id": package_id,
                "project_name": package["metadata"].get("name", {}).get("en-US"),
                "source_code": source_code,
                "old": old,
                "new": new,
            }
        )
    eligible.sort(key=lambda value: (value["rank_sha256"], value["package_id"]))
    output = {
        "format": "vcdiff-public-android-candidate-manifest-v1",
        "sampling_seed": SEED,
        "selection_status": (
            "ordered candidates only; no APK was traced or optimized before this manifest"
        ),
        "index_inputs": {
            "repo": {
                "url": "https://f-droid.org/repo/index-v2.json",
                "sha256": sha256(REPO_INDEX),
            },
            "archive": {
                "url": "https://f-droid.org/archive/index-v2.json",
                "sha256": sha256(ARCHIVE_INDEX),
            },
        },
        "metadata_eligibility": [
            "package has an HTTPS public sourceCode URL",
            "APK filename ends .apk and index SHA-256 is present",
            "APK size is between 1,000,000 and 25,000,000 bytes inclusive",
            "manifest nativecode is absent or empty (universal managed-code APK)",
            "releaseChannels is absent or empty",
            "versionName and integer versionCode are present",
            "exactly one eligible APK exists for each retained versionCode",
            "old/new are the latest two retained versionCodes",
            "old/new signer fingerprint lists are identical",
        ],
        "ordering": (
            "ascending SHA256(sampling_seed + NUL + package_id), then package_id"
        ),
        "eligible_project_count": len(eligible),
        "recorded_candidate_count": min(MAX_CANDIDATES, len(eligible)),
        "exclusion_counts": exclusion_counts,
        "candidates": eligible[:MAX_CANDIDATES],
    }
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(OUTPUT)
    print(f"eligible={len(eligible)} recorded={len(output['candidates'])}")


if __name__ == "__main__":
    main()
