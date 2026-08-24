#!/usr/bin/env bash
set -euo pipefail

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

pair_id=compressed-zstd-tar-gz-v1.5.4-to-v1.5.5
if python3 benchmark/run_corpus.py \
  --pair "$pair_id" \
  --state-path benchmark_work/oracle-state-validity-replay.json; then
  echo "expected the frozen optimizer invariant check to fail" >&2
  exit 1
fi

PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python3 benchmark/capture_optimizer_counterexample.py \
  --pair-id "$pair_id" --physical-slots 1
python3 benchmark/write_validity_kill_report.py
