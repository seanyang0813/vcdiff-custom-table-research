#!/usr/bin/env python3
"""Generate the explicit, outcome-blind generality preregistration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

PROJECT_SPLITS = {
    "linux": "train",
    "git": "train",
    "sqlite": "test",
    "curl": "train",
    "redis": "train",
    "llvm": "validation",
    "zstd": "train",
    "xdelta": "test",
    "open-vcdiff": "test",
    "unicode": "validation",
    "tzdb": "train",
}

GIT_PROJECTS: dict[str, dict[str, Any]] = {
    "linux": {
        "name": "Linux kernel subtree",
        "repository": "https://github.com/torvalds/linux.git",
        "scope": "kernel",
        "releases": [
            ("v6.12", "adc218676eef25575469234709c2d87185ca223a"),
            ("v6.13", "ffd294d346d185b70e28b1a28abe367bbfe53c04"),
            ("v6.14", "38fec10eb60d687e30c8c6b5420d86e8149f7557"),
            ("v6.15", "0ff41df1cb268fc69e703a08a57ee14ae967d0ca"),
        ],
    },
    "git": {
        "name": "Git",
        "repository": "https://github.com/git/git.git",
        "scope": None,
        "releases": [
            ("v2.48.0", "fbe8d3079d4a96aeb4e4529cc93cc0043b759a05"),
            ("v2.48.1", "f93ff170b93a1782659637824b25923245ac9dd1"),
            ("v2.49.0", "683c54c999c301c2cd6f715c411407c413b1d84e"),
            ("v2.50.0", "16bd9f20a403117f2e0d9bcda6c6e621d3763e77"),
        ],
    },
    "sqlite": {
        "name": "SQLite",
        "repository": "https://github.com/sqlite/sqlite.git",
        "scope": None,
        "releases": [
            ("version-3.47.0", "f5fb820c0f4781337faf02ed871be68d13a83d94"),
            ("version-3.47.1", "0592ffed8244e2a8de0a2ab083fbf14335033922"),
            ("version-3.48.0", "942c9587698715734715242737dba07ef296b0ef"),
            ("version-3.49.0", "659bafd05dee789298074283ce857e27e65ef675"),
        ],
    },
    "curl": {
        "name": "curl",
        "repository": "https://github.com/curl/curl.git",
        "scope": None,
        "releases": [
            ("curl-8_11_0", "b1ef0e1a01c0bb6ee5367bd9c186a603bde3615a"),
            ("curl-8_11_1", "75a2079d5c28debb2eaa848ca9430f1fe0d7844c"),
            ("curl-8_12_0", "34cf9d54a46598c44938aa7598820484d7af7133"),
            ("curl-8_13_0", "1c3149881769e7bd79b072e48374e4c2b3678b2f"),
        ],
    },
    "redis": {
        "name": "Redis",
        "repository": "https://github.com/redis/redis.git",
        "scope": None,
        "releases": [
            ("7.4.0", "c9d29f6a918c335bc1778d9f68e521c1bbb36a0f"),
            ("7.4.1", "74b289a0e12f9f65a6daeec6a66cadc76792f644"),
            ("7.4.2", "a0a6f23d997b024689ba157916837f493a593a34"),
            ("8.0.0", "e91a340e241cf0abe3c6a0c254214fbe4aa1d95f"),
        ],
    },
    "llvm": {
        "name": "LLVM Transforms subtree",
        "repository": "https://github.com/llvm/llvm-project.git",
        "scope": "llvm/lib/Transforms",
        "releases": [
            ("llvmorg-19.1.0", "a4bf6cd7cfb1a1421ba92bca9d017b49936c55e4"),
            ("llvmorg-19.1.1", "d401987fe349a87c53fe25829215b080b70c0c1a"),
            ("llvmorg-19.1.2", "7ba7d8e2f7b6445b60679da826210cdde29eaf8b"),
            ("llvmorg-20.1.0", "24a30daaa559829ad079f2ff7f73eb4e18095f88"),
        ],
    },
    "zstd": {
        "name": "Zstandard",
        "repository": "https://github.com/facebook/zstd.git",
        "scope": None,
        "releases": [
            ("v1.5.4", "945f27758c0fd67b636103a38dbf050266c6b90a"),
            ("v1.5.5", "63779c798237346c2b245c546c40b72a5a5913fe"),
            ("v1.5.6", "794ea1b0afca0f020f4e57b6732332231fb23c70"),
            ("v1.5.7", "f8745da6ff1ad1e7bab384bd1f9d742439278e99"),
        ],
    },
    "xdelta": {
        "name": "xdelta",
        "repository": "https://github.com/jmacd/xdelta-gpl.git",
        "scope": None,
        "releases": [
            ("v3.0.9", "63c9404c28dbcde26a730f1c62b70e0994b240cc"),
            ("v3.0.10", "c6493c5a57e1edc95fa27123e86fe14c3695f284"),
            ("v3.0.11", "81aebf78ae67c29f528088d65743643e5355e3d3"),
            ("v3.1.0", "4b4aed71a959fe11852e45242bb6524be85d3709"),
        ],
    },
    "open-vcdiff": {
        "name": "Open-VCDIFF",
        "repository": "https://github.com/google/open-vcdiff.git",
        "scope": None,
        "releases": [
            ("open-vcdiff-0.8.1", "0ec2259e3dc0e17698ac4bc586740f4a4c928ef1"),
            ("openvcdiff-0.8.2", "a1c5dad47485a8b117bd0852b3ead340dac37a8f"),
            ("openvcdiff-0.8.3", "af81c060f9948a9e91d3364f2ddc53c1f56c4447"),
            ("openvcdiff-0.8.4", "9af10d36e691c15dceff04419b9e3a71ec5d8bec"),
        ],
    },
}

COMPILED_PROJECTS = ("zstd", "curl", "redis", "sqlite", "xdelta")

STRUCTURED_PROJECTS: dict[str, dict[str, Any]] = {
    "unicode": {
        "name": "Unicode Character Database",
        "releases": [
            ("15.0.0", "https://www.unicode.org/Public/zipped/15.0.0/UCD.zip"),
            ("15.1.0", "https://www.unicode.org/Public/zipped/15.1.0/UCD.zip"),
            ("16.0.0", "https://www.unicode.org/Public/zipped/16.0.0/UCD.zip"),
            ("17.0.0", "https://www.unicode.org/Public/zipped/17.0.0/UCD.zip"),
        ],
        "archive_kind": "zip",
    },
    "tzdb": {
        "name": "IANA time-zone data",
        "releases": [
            ("2024a", "https://data.iana.org/time-zones/releases/tzdata2024a.tar.gz"),
            ("2024b", "https://data.iana.org/time-zones/releases/tzdata2024b.tar.gz"),
            ("2025a", "https://data.iana.org/time-zones/releases/tzdata2025a.tar.gz"),
            ("2025b", "https://data.iana.org/time-zones/releases/tzdata2025b.tar.gz"),
        ],
        "archive_kind": "tar.gz",
    },
}

COMPRESSED_SERIES = [
    {
        "project": "zstd",
        "format": "tar.gz",
        "releases": [
            ("v1.5.4", "https://github.com/facebook/zstd/releases/download/v1.5.4/zstd-1.5.4.tar.gz"),
            ("v1.5.5", "https://github.com/facebook/zstd/releases/download/v1.5.5/zstd-1.5.5.tar.gz"),
            ("v1.5.6", "https://github.com/facebook/zstd/releases/download/v1.5.6/zstd-1.5.6.tar.gz"),
        ],
    },
    {
        "project": "zstd",
        "format": "tar.zst",
        "releases": [
            ("v1.5.4", "https://github.com/facebook/zstd/releases/download/v1.5.4/zstd-1.5.4.tar.zst"),
            ("v1.5.5", "https://github.com/facebook/zstd/releases/download/v1.5.5/zstd-1.5.5.tar.zst"),
            ("v1.5.6", "https://github.com/facebook/zstd/releases/download/v1.5.6/zstd-1.5.6.tar.zst"),
        ],
    },
    {
        "project": "curl",
        "format": "tar.gz",
        "releases": [
            ("8.11.0", "https://curl.se/download/curl-8.11.0.tar.gz"),
            ("8.11.1", "https://curl.se/download/curl-8.11.1.tar.gz"),
            ("8.12.0", "https://curl.se/download/curl-8.12.0.tar.gz"),
        ],
    },
    {
        "project": "curl",
        "format": "tar.xz",
        "releases": [
            ("8.11.0", "https://curl.se/download/curl-8.11.0.tar.xz"),
            ("8.11.1", "https://curl.se/download/curl-8.11.1.tar.xz"),
            ("8.12.0", "https://curl.se/download/curl-8.12.0.tar.xz"),
        ],
    },
]


def slug(value: str) -> str:
    return (
        value.lower()
        .replace("open-vcdiff-", "")
        .replace("openvcdiff-", "")
        .replace("version-", "")
        .replace("llvmorg-", "")
        .replace("curl-", "")
        .replace("_", ".")
        .replace(" ", "-")
    )


def artifact_path(category: str, project: str, release: str, suffix: str) -> str:
    return f"benchmark_data/{category}/{project}-{slug(release)}.{suffix}"


def endpoint(ref: str, locator: str, artifact: str, **extra: Any) -> dict[str, Any]:
    result = {"ref": ref, "locator": locator, "artifact": artifact}
    result.update(extra)
    return result


def make_pair(
    *,
    pair_id: str,
    project: str,
    category: str,
    distance: str,
    source: dict[str, Any],
    target: dict[str, Any],
    recipe: str,
) -> dict[str, Any]:
    return {
        "id": pair_id,
        "project": project,
        "split": PROJECT_SPLITS[project],
        "category": category,
        "distance": distance,
        "source": source,
        "target": target,
        "recipe": recipe,
    }


def generate_pairs() -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    distances = ("near", "medium", "far")
    for project, definition in GIT_PROJECTS.items():
        releases = definition["releases"]
        source_ref, source_commit = releases[0]
        scope = definition["scope"]
        suffix = "treeblob"
        source = endpoint(
            source_ref,
            source_commit,
            artifact_path("source", project, source_ref, suffix),
            repository=definition["repository"],
            scope=scope,
        )
        for distance, (target_ref, target_commit) in zip(distances, releases[1:]):
            target = endpoint(
                target_ref,
                target_commit,
                artifact_path("source", project, target_ref, suffix),
                repository=definition["repository"],
                scope=scope,
            )
            pairs.append(
                make_pair(
                    pair_id=(
                        f"source-{project}-{slug(source_ref)}-to-{slug(target_ref)}"
                    ),
                    project=project,
                    category="source_tree",
                    distance=distance,
                    source=source,
                    target=target,
                    recipe="git_tree_blob_v1",
                )
            )

    for project in COMPILED_PROJECTS:
        definition = GIT_PROJECTS[project]
        source_ref, source_commit = definition["releases"][0]
        source = endpoint(
            source_ref,
            source_commit,
            artifact_path("compiled", project, source_ref, "bundle"),
            repository=definition["repository"],
            build_recipe=f"compiled_{project}_v1",
        )
        for distance, (target_ref, target_commit) in zip(
            ("near", "medium"), definition["releases"][1:3]
        ):
            target = endpoint(
                target_ref,
                target_commit,
                artifact_path("compiled", project, target_ref, "bundle"),
                repository=definition["repository"],
                build_recipe=f"compiled_{project}_v1",
            )
            pairs.append(
                make_pair(
                    pair_id=(
                        f"compiled-{project}-{slug(source_ref)}-to-{slug(target_ref)}"
                    ),
                    project=project,
                    category="compiled",
                    distance=distance,
                    source=source,
                    target=target,
                    recipe=f"compiled_{project}_v1",
                )
            )

    for project, definition in STRUCTURED_PROJECTS.items():
        releases = definition["releases"]
        source_ref, source_url = releases[0]
        source = endpoint(
            source_ref,
            source_url,
            artifact_path("structured", project, source_ref, "bundle"),
            archive_kind=definition["archive_kind"],
        )
        for distance, (target_ref, target_url) in zip(distances, releases[1:]):
            target = endpoint(
                target_ref,
                target_url,
                artifact_path("structured", project, target_ref, "bundle"),
                archive_kind=definition["archive_kind"],
            )
            pairs.append(
                make_pair(
                    pair_id=f"structured-{project}-{slug(source_ref)}-to-{slug(target_ref)}",
                    project=project,
                    category="structured",
                    distance=distance,
                    source=source,
                    target=target,
                    recipe="unpack_and_directory_bundle_v1",
                )
            )

    for series in COMPRESSED_SERIES:
        project = series["project"]
        format_name = series["format"]
        source_ref, source_url = series["releases"][0]
        source = endpoint(
            source_ref,
            source_url,
            artifact_path("compressed", project, source_ref, format_name),
            format=format_name,
        )
        for distance, (target_ref, target_url) in zip(
            ("near", "medium"), series["releases"][1:]
        ):
            target = endpoint(
                target_ref,
                target_url,
                artifact_path("compressed", project, target_ref, format_name),
                format=format_name,
            )
            pairs.append(
                make_pair(
                    pair_id=(
                        f"compressed-{project}-{format_name.replace('.', '-')}-"
                        f"{slug(source_ref)}-to-{slug(target_ref)}"
                    ),
                    project=project,
                    category="compressed",
                    distance=distance,
                    source=source,
                    target=target,
                    recipe="exact_upstream_release_bytes_v1",
                )
            )
    return pairs


def main() -> None:
    pairs = generate_pairs()
    category_counts: dict[str, int] = {}
    for pair in pairs:
        category_counts[pair["category"]] = category_counts.get(pair["category"], 0) + 1
    expected = {"source_tree": 27, "compiled": 10, "structured": 6, "compressed": 8}
    if category_counts != expected or len(pairs) != 51:
        raise AssertionError((category_counts, len(pairs)))
    if len({pair["id"] for pair in pairs}) != len(pairs):
        raise AssertionError("duplicate pair identifiers")

    document = {
        "format": "vcdiff-generality-preregistration-v1",
        "registered_date": "2026-08-23",
        "status": "locked before any confirmatory pair was traced",
        "objective": (
            "Estimate the distribution and structural predictors of exact restricted "
            "VCDIFF custom-table savings, then conditionally test a reusable table bank."
        ),
        "known_exploratory_pairs_excluded_from_confirmatory_metrics": [
            "zstd-v1.5.6-to-v1.5.7-tree",
            "open-vcdiff-0.8.3-to-0.8.4-tree",
            "xdelta-v3.0.10-to-v3.0.11-tree",
            "zstd-v1.5.6-to-v1.5.7-win64-zip",
        ],
        "frozen_oracle": {
            "optimizer_path": "src/vcdiff_opt/optimizer.py",
            "optimizer_sha256": "aac3d7906c7b7f6e26a98f95691f34b599057fc477bef9b2675500a302c32b51",
            "rule": "Do not modify the optimizer during the generality experiment.",
            "table_family": "canonical q=0..93 prefix replacement of RFC opcodes 163..255",
            "window_limit_bytes": 67108864,
        },
        "sampling": {
            "pair_count": len(pairs),
            "category_counts": category_counts,
            "selection_rule": (
                "Releases, scopes, formats, and build recipes were selected before tracing; "
                "no confirmatory pair was chosen or dropped based on trace or oracle outcome."
            ),
            "replacement_rule": (
                "If an endpoint is unavailable or cannot be built, replace only with the "
                "chronologically next release from the same project/category using the same "
                "recipe, before tracing it, and append the reason to deviations.jsonl. "
                "Never replace based on compression outcome."
            ),
            "size_rule": (
                "Artifacts must be nonempty and at most 64 MiB. Fixed Linux and LLVM "
                "subtrees are used to satisfy the one-window limit without outcome selection."
            ),
        },
        "project_splits": PROJECT_SPLITS,
        "primary_endpoints": {
            "distribution": [
                "median and quartiles of exact savings fraction",
                "fraction of pairs saving at least 0.3%, 1%, and 2%",
                "project- and category-balanced means",
                "change-distance trends within project",
            ],
            "favorable_label": "exact oracle saving fraction >= 0.01",
            "core_hypothesis": (
                "Savings increase with stock instruction-byte fraction, instruction density, "
                "and concentrated reusable single/pair patterns, provided repetitions amortize "
                "the transmitted custom table."
            ),
        },
        "required_stock_trace_features": [
            "instruction_bytes / stock_patch_bytes",
            "logical instruction count and instructions per output MiB",
            "ADD/COPY/RUN counts and fractions",
            "COPY mode histogram",
            "instruction-size histogram and quantiles",
            "top adjacent-pair frequencies",
            "maximum nonoverlapping instruction coverage by top k pairs for k=1,4,8,16,32,64,93",
            "Shannon entropy, normalized entropy, Herfindahl index, and top-k mass for singles and pairs",
            "custom-table transmission cost",
            "exact oracle bytes and savings",
        ],
        "predictive_analysis": {
            "inputs": "stock-trace features only; oracle fields are labels and never predictors",
            "grouping": "all cross-validation and final splits group by project",
            "prespecified_models": [
                "instruction-fraction-only linear baseline",
                "standardized ridge regression on cheap features",
                "depth-3 decision tree on cheap features",
                "logistic counterparts for the >=1% favorable label",
            ],
            "metrics": [
                "MAE and Spearman correlation for savings fraction",
                "ROC AUC, average precision, precision, recall, and Brier score for favorable label",
                "selector byte regret and false-positive size regressions before monotonic fallback",
            ],
            "threshold_tuning": "training projects fit models; validation projects choose threshold; test projects are touched once",
        },
        "generality_gate_for_table_bank": {
            "all_required": [
                "at least three confirmatory projects have one or more pairs saving >=1%",
                "at least two compiled or structured pairs save >=1%",
                "the project-held-out favorable classifier reaches ROC AUC >=0.75",
                "a validation-tuned selector reaches precision >=0.70 at recall >=0.40",
            ],
            "failure_action": (
                "Do not build a deployment prototype; report the kill result and retain the "
                "oracle/benchmark as the research artifact."
            ),
        },
        "conditional_table_bank_protocol": {
            "run_only_if_generality_gate_passes": True,
            "training": "derive candidates only from training-project oracle tables/traces",
            "validation": "choose bank size and selector threshold on validation projects",
            "test": "evaluate once on test projects with no refitting",
            "bank_sizes": [1, 2, 4, 8],
            "primary_metric": "aggregate held-out bank savings / aggregate held-out oracle savings",
            "target_capture": [0.70, 0.80],
            "monotonicity": (
                "encode/evaluate stock and selected fixed table and emit the smaller; no patch "
                "may grow when selection is enabled"
            ),
        },
        "pairs": pairs,
    }
    output = ROOT / "benchmark/preregistration-v1.json"
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (ROOT / "benchmark/preregistration-v1.sha256").write_text(
        f"{digest}  benchmark/preregistration-v1.json\n"
    )
    print(json.dumps({"path": str(output), "sha256": digest, "counts": category_counts}))


if __name__ == "__main__":
    main()
