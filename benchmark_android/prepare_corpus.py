#!/usr/bin/env python3
"""Download and freeze the first 40 valid public DEX update candidates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "benchmark_android/candidate-manifest-v1.json"
PREREG = ROOT / "benchmark_android/preregistration-v1.json"
PREREG_HASH = ROOT / "benchmark_android/preregistration-v1.sha256"
OUTPUT = ROOT / "benchmark_android/corpus-lock-v1.json"
OUTPUT_HASH = ROOT / "benchmark_android/corpus-lock-v1.sha256"
DATA = ROOT / "benchmark_android/data"
TARGET_PAIRS = 40
DEX_PATTERN = re.compile(r"^classes(?:([2-9]|[1-9][0-9]+))?\.dex$")
MIN_DEX_BYTES = 256 * 1024
MAX_DEX_BYTES = 12 * 1024 * 1024
MAX_DEX_FILES = 8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_locks() -> dict[str, Any]:
    if PREREG_HASH.read_text().split()[0] != sha256(PREREG):
        raise ValueError("Android preregistration hash drift")
    prereg = json.loads(PREREG.read_text())
    for item in prereg["locked_inputs"].values():
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"locked input drift: {item['path']}")
    return prereg


def download(release: dict[str, Any], destination: Path) -> dict[str, Any]:
    if destination.is_file() and sha256(destination) == release["sha256"]:
        return {"path": str(destination.relative_to(ROOT)), "reused": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    urls = [
        f"https://f-droid.org/{release['section']}/{release['filename']}",
        f"https://ftp.fau.de/fdroid/{release['section']}/{release['filename']}",
    ]
    errors: list[str] = []
    temporary = destination.with_suffix(".apk.partial")
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "vcdiff-dex-study/1"})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            actual = sha256(temporary)
            if actual != release["sha256"]:
                errors.append(f"{url}: sha256 {actual}")
                continue
            os.replace(temporary, destination)
            return {
                "path": str(destination.relative_to(ROOT)),
                "url": url,
                "reused": False,
            }
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            errors.append(f"{url}: {error!r}")
    if temporary.exists():
        temporary.unlink()
    raise RuntimeError("; ".join(errors))


def dex_sort_key(name: str) -> int:
    match = DEX_PATTERN.fullmatch(name)
    if match is None:
        raise ValueError(name)
    return 1 if match.group(1) is None else int(match.group(1))


def build_bundle(apk: Path, destination: Path) -> dict[str, Any]:
    with zipfile.ZipFile(apk) as archive:
        names = [name for name in archive.namelist() if DEX_PATTERN.fullmatch(name)]
        if len(names) != len(set(names)):
            raise ValueError("duplicate classes*.dex member")
        names.sort(key=dex_sort_key)
        if not names:
            raise ValueError("no standard classes*.dex member")
        if len(names) > MAX_DEX_FILES:
            raise ValueError(f"dex file count {len(names)} exceeds {MAX_DEX_FILES}")
        members: list[tuple[str, bytes]] = []
        for name in names:
            data = archive.read(name)  # reading verifies the member CRC
            if len(data) < 8 or not data.startswith(b"dex\n") or data[7] != 0:
                raise ValueError(f"nonstandard DEX magic in {name}")
            members.append((name, data))
    total = sum(len(data) for _, data in members)
    if not MIN_DEX_BYTES <= total <= MAX_DEX_BYTES:
        raise ValueError(
            f"total DEX bytes {total} outside [{MIN_DEX_BYTES},{MAX_DEX_BYTES}]"
        )
    encoded = bytearray(b"VCDIFF-DEX-BUNDLE-v1\0")
    for name, data in members:
        name_bytes = name.encode("ascii")
        encoded.extend(struct.pack(">I", len(name_bytes)))
        encoded.extend(name_bytes)
        encoded.extend(struct.pack(">Q", len(data)))
        encoded.extend(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    return {
        "path": str(destination.relative_to(ROOT)),
        "sha256": sha256(destination),
        "size": destination.stat().st_size,
        "dex_total_bytes": total,
        "dex_files": [
            {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in members
        ],
    }


def main() -> None:
    prereg = verify_locks()
    candidates = json.loads(CANDIDATES.read_text())
    accepted: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    DATA.mkdir(parents=True, exist_ok=True)
    for candidate in candidates["candidates"]:
        if len(accepted) >= TARGET_PAIRS:
            break
        package_id = candidate["package_id"]
        directory = DATA / package_id
        try:
            sides: dict[str, Any] = {}
            for side in ("old", "new"):
                release = candidate[side]
                apk = directory / f"{side}-{release['version_code']}.apk"
                acquired = download(release, apk)
                if sha256(apk) != release["sha256"] or apk.stat().st_size != release["size"]:
                    raise ValueError(f"{side} APK differs from signed index")
                bundle = directory / f"{side}-{release['version_code']}.dexbundle"
                sides[side] = {
                    "release": release,
                    "apk": {
                        **acquired,
                        "sha256": sha256(apk),
                        "size": apk.stat().st_size,
                    },
                    "bundle": build_bundle(apk, bundle),
                }
            accepted.append(
                {
                    "pair_id": f"fdroid-{package_id}-{candidate['old']['version_code']}-to-{candidate['new']['version_code']}",
                    "candidate_rank": len(accepted) + len(exclusions),
                    "package_id": package_id,
                    "project_name": candidate.get("project_name"),
                    "source_code": candidate["source_code"],
                    **sides,
                }
            )
            print(f"accepted {len(accepted):02d}/{TARGET_PAIRS} {package_id}", flush=True)
        except Exception as error:
            exclusions.append(
                {
                    "candidate_rank": len(accepted) + len(exclusions),
                    "package_id": package_id,
                    "reason": repr(error),
                }
            )
            print(f"excluded {package_id}: {error}", flush=True)
    status = "frozen_complete" if len(accepted) == TARGET_PAIRS else "insufficient_candidates"
    result = {
        "format": "vcdiff-public-android-dex-corpus-lock-v1",
        "status": status,
        "preregistration_sha256": sha256(PREREG),
        "candidate_manifest_sha256": sha256(CANDIDATES),
        "target_pair_count": TARGET_PAIRS,
        "accepted_pair_count": len(accepted),
        "exclusion_count": len(exclusions),
        "pairs": accepted,
        "exclusions": exclusions,
        "outcome_blinding": (
            "No VCDIFF trace, patch, feature, or custom-table optimization was run "
            "while selecting and freezing this corpus."
        ),
        "bundle_format": prereg["dex_bundle_format"],
    }
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    OUTPUT_HASH.write_text(f"{sha256(OUTPUT)}  {OUTPUT.relative_to(ROOT)}\n")
    print(f"{status}: accepted={len(accepted)} excluded={len(exclusions)}")
    print(OUTPUT)


if __name__ == "__main__":
    main()
