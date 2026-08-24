#!/usr/bin/env bash
set -euo pipefail

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

"$project_root/scripts/prepare_corpus.sh"
PYTHONPATH="$project_root/src" python3 -m pytest "$project_root/tests"

run_pair() {
  local pair_id=$1
  local source_file=$2
  local target_file=$3
  local output_dir="$project_root/artifacts/$pair_id"
  PYTHONPATH="$project_root/src" python3 -m vcdiff_opt.cli study \
    --source "$project_root/$source_file" \
    --target "$project_root/$target_file" \
    --output "$output_dir" \
    --trace-xdelta "$project_root/build/xdelta/xdelta3-trace" \
    --custom-table-decoder "$project_root/build/xdelta/xdelta3-rfc-custom-decoder" \
    --max-slots 4 \
    --global-max-slots 93
  PYTHONPATH="$project_root/src" python3 -m vcdiff_opt.cli verify \
    --certificate "$output_dir/certificate.json" \
    --custom-table-decoder "$project_root/build/xdelta/xdelta3-rfc-custom-decoder"
}

run_pair \
  zstd-v1.5.6-to-v1.5.7 \
  data/zstd-v1.5.6.treeblob \
  data/zstd-v1.5.7.treeblob
run_pair \
  open-vcdiff-0.8.3-to-0.8.4 \
  data/open-vcdiff-0.8.3.treeblob \
  data/open-vcdiff-0.8.4.treeblob
run_pair \
  xdelta-v3.0.10-to-v3.0.11 \
  data/xdelta-v3.0.10.treeblob \
  data/xdelta-v3.0.11.treeblob
run_pair \
  zstd-win64-v1.5.6-to-v1.5.7 \
  data/zstd-v1.5.6-win64.zip \
  data/zstd-v1.5.7-win64.zip

python3 "$project_root/scripts/summarize_corpus.py"
