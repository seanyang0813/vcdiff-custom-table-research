# Frozen-corpus exact-SCIP partial status

**Trace-complete but exact-incomplete and nonconfirmatory:** every frozen stock trace has been independently replayed, while 31/48 pairs have exact-SCIP certificates. The preregistered distribution, predictor, and table-bank gates have not been evaluated.

| Pair | Category | Trace | Stock | Exact | Saving | q | Wall s | Peak MiB |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| source-linux-v6.12-to-v6.13 | source_tree | 22,086 | 86,086 | 84,071 | 2,015 (2.3407%) | 93 | 175.22 | 2,271 |
| source-linux-v6.12-to-v6.14 | source_tree | 38,289 | 148,724 | 144,905 | 3,819 (2.5678%) | 93 | 432.15 | 3,619 |
| source-linux-v6.12-to-v6.15 | source_tree | 61,725 | 238,373 | 231,716 | 6,657 (2.7927%) | 93 | 1,070.11 | 5,689 |
| source-git-v2.48.0-to-v2.48.1 | source_tree | 472 | 1,952 | 1,952 | 0 (0.0000%) | 0 | 8.89 | 409 |
| source-git-v2.48.0-to-v2.49.0 | source_tree | 37,991 | 151,012 | 146,932 | 4,080 (2.7018%) | 93 | 331.77 | 3,560 |
| source-curl-8.11.0-to-8.11.1 | source_tree | 6,219 | 25,767 | 25,597 | 170 (0.6598%) | 85 | 124.84 | 792 |
| source-redis-7.4.0-to-7.4.1 | source_tree | 102 | 540 | 540 | 0 (0.0000%) | 0 | 3.32 | 203 |
| source-redis-7.4.0-to-7.4.2 | source_tree | 1,334 | 5,781 | 5,781 | 0 (0.0000%) | 0 | 4.89 | 276 |
| source-llvm-19.1.0-to-19.1.1 | source_tree | 51 | 252 | 252 | 0 (0.0000%) | 0 | 2.83 | 178 |
| source-llvm-19.1.0-to-19.1.2 | source_tree | 155 | 721 | 721 | 0 (0.0000%) | 0 | 2.91 | 188 |
| source-zstd-v1.5.4-to-v1.5.5 | source_tree | 14,566 | 277,841 | 276,705 | 1,136 (0.4089%) | 85 | 754.41 | 4,061 |
| source-xdelta-v3.0.9-to-v3.0.10 | source_tree | 1,124 | 4,276 | 4,276 | 0 (0.0000%) | 0 | 2.62 | 230 |
| source-xdelta-v3.0.9-to-v3.0.11 | source_tree | 2,485 | 9,569 | 9,569 | 0 (0.0000%) | 0 | 7.55 | 390 |
| source-xdelta-v3.0.9-to-v3.1.0 | source_tree | 25,311 | 81,325 | 78,862 | 2,463 (3.0286%) | 93 | 842.18 | 2,707 |
| source-open-vcdiff-0.8.1-to-0.8.2 | source_tree | 128 | 594 | 594 | 0 (0.0000%) | 0 | 0.91 | 121 |
| source-open-vcdiff-0.8.1-to-0.8.3 | source_tree | 228 | 1,022 | 1,022 | 0 (0.0000%) | 0 | 1.05 | 129 |
| source-open-vcdiff-0.8.1-to-0.8.4 | source_tree | 18,804 | 69,262 | 67,636 | 1,626 (2.3476%) | 93 | 149.26 | 2,025 |
| compiled-curl-8.11.0-to-8.11.1 | compiled | 49,094 | 169,800 | 160,563 | 9,237 (5.4399%) | 93 | 3,632.00 | 4,782 |
| compiled-xdelta-v3.0.9-to-v3.0.10 | compiled | 8,566 | 31,221 | 30,165 | 1,056 (3.3823%) | 93 | 218.01 | 1,045 |
| compiled-xdelta-v3.0.9-to-v3.0.11 | compiled | 11,846 | 45,935 | 44,672 | 1,263 (2.7495%) | 93 | 333.52 | 1,406 |
| structured-tzdb-2024a-to-2024b | structured | 5,904 | 21,782 | 21,647 | 135 (0.6198%) | 85 | 112.75 | 829 |
| structured-tzdb-2024a-to-2025a | structured | 7,437 | 27,594 | 27,312 | 282 (1.0220%) | 85 | 233.93 | 932 |
| structured-tzdb-2024a-to-2025b | structured | 7,980 | 29,865 | 29,532 | 333 (1.1150%) | 93 | 281.86 | 975 |
| compressed-zstd-tar-gz-v1.5.4-to-v1.5.5 | compressed | 4,915 | 2,227,930 | 2,227,631 | 299 (0.0134%) | 85 | 56.78 | 578 |
| compressed-zstd-tar-gz-v1.5.4-to-v1.5.6 | compressed | 2,915 | 2,296,915 | 2,296,915 | 0 (0.0000%) | 0 | 6.40 | 350 |
| compressed-zstd-tar-zst-v1.5.4-to-v1.5.5 | compressed | 1,268 | 1,458,102 | 1,458,102 | 0 (0.0000%) | 0 | 2.11 | 210 |
| compressed-zstd-tar-zst-v1.5.4-to-v1.5.6 | compressed | 1,420 | 1,486,089 | 1,486,089 | 0 (0.0000%) | 0 | 2.57 | 230 |
| compressed-curl-tar-gz-8.11.0-to-8.11.1 | compressed | 12,660 | 4,062,068 | 4,060,843 | 1,225 (0.0302%) | 93 | 38.38 | 1,192 |
| compressed-curl-tar-gz-8.11.0-to-8.12.0 | compressed | 9,716 | 4,163,190 | 4,162,659 | 531 (0.0128%) | 85 | 25.20 | 846 |
| compressed-curl-tar-xz-8.11.0-to-8.11.1 | compressed | 31 | 2,751,263 | 2,751,263 | 0 (0.0000%) | 0 | 0.58 | 127 |
| compressed-curl-tar-xz-8.11.0-to-8.12.0 | compressed | 29 | 2,777,590 | 2,777,590 | 0 (0.0000%) | 0 | 0.57 | 127 |

Every listed row has equal exact-SCIP primal/dual bounds, independent DP attainment, emitted-byte equality, and two successful decoder replays. Pairs without exact labels are not treated as zero-gain or excluded.

The tractability-selected exact subset totals 22,652,441 to 22,616,114 bytes, saving 36,327 (0.1604%). This aggregate is descriptive only and is not a frozen-corpus distribution estimate.

## Unresolved exact frontier

These rows have exact stock-trace byte replay and two decoder checks, but no exact custom-table label. Instruction count is an operational ranking aid, not an outcome or exclusion rule.

| Pair | Category | Logical instructions | Stock bytes | Exact status |
|---|---|---:|---:|---|
| source-zstd-v1.5.4-to-v1.5.6 | source_tree | 39,453 | 370,248 | not_exactly_attempted |
| source-curl-8.11.0-to-8.12.0 | source_tree | 50,826 | 194,029 | not_exactly_attempted |
| source-zstd-v1.5.4-to-v1.5.7 | source_tree | 55,902 | 430,916 | not_exactly_attempted |
| compiled-curl-8.11.0-to-8.12.0 | compiled | 81,370 | 287,322 | not_exactly_attempted |
| compiled-zstd-v1.5.4-to-v1.5.5 | compiled | 89,322 | 324,052 | not_exactly_attempted |
| structured-unicode-15.0.0-to-15.1.0 | structured | 95,788 | 3,728,197 | not_exactly_attempted |
| source-curl-8.11.0-to-8.13.0 | source_tree | 103,470 | 390,234 | not_exactly_attempted |
| source-llvm-19.1.0-to-20.1.0 | source_tree | 106,901 | 414,599 | not_exactly_attempted |
| compiled-redis-7.4.0-to-7.4.1 | compiled | 111,408 | 388,353 | not_exactly_attempted |
| compiled-zstd-v1.5.4-to-v1.5.6 | compiled | 115,224 | 421,726 | not_exactly_attempted |
| source-redis-7.4.0-to-8.0.0 | source_tree | 116,123 | 429,894 | not_exactly_attempted |
| compiled-sqlite-3.47.0-to-3.47.1 | compiled | 133,903 | 477,981 | not_exactly_attempted |
| source-git-v2.48.0-to-v2.50.0 | source_tree | 138,690 | 525,522 | not_exactly_attempted |
| compiled-redis-7.4.0-to-7.4.2 | compiled | 155,782 | 566,144 | not_exactly_attempted |
| compiled-sqlite-3.47.0-to-3.48.0 | compiled | 188,347 | 696,026 | not_exactly_attempted |
| structured-unicode-15.0.0-to-16.0.0 | structured | 420,930 | 4,907,878 | not_exactly_attempted |
| structured-unicode-15.0.0-to-17.0.0 | structured | 486,093 | 5,114,107 | not_exactly_attempted |
