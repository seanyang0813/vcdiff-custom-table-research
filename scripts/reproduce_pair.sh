#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 5 ]]; then
  echo "usage: $0 SOURCE TARGET OUTPUT_DIR [DIAGNOSTIC_MAX_SLOTS] [GLOBAL_MAX_SLOTS]" >&2
  exit 2
fi

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_file=$1
target_file=$2
output_dir=$3
max_slots=${4:-8}
global_max_slots=${5:-93}

"$project_root/scripts/bootstrap_tools.sh"
PYTHONPATH="$project_root/src" python3 -m pytest "$project_root/tests"
PYTHONPATH="$project_root/src" python3 -m vcdiff_opt.cli study \
  --source "$source_file" \
  --target "$target_file" \
  --output "$output_dir" \
  --trace-xdelta "$project_root/build/xdelta/xdelta3-trace" \
  --custom-table-decoder "$project_root/build/xdelta/xdelta3-rfc-custom-decoder" \
  --max-slots "$max_slots" \
  --global-max-slots "$global_max_slots"
PYTHONPATH="$project_root/src" python3 -m vcdiff_opt.cli verify \
  --certificate "$output_dir/certificate.json" \
  --custom-table-decoder "$project_root/build/xdelta/xdelta3-rfc-custom-decoder"
