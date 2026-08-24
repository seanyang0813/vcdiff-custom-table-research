#!/usr/bin/env bash
set -euo pipefail

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
current_commit=9822b17313263d458b80511b08124971fc0e04fa
decoder_commit=98bc4523a0c5d1a0743da4261e41a431a66acf2d
current_dir="$project_root/third_party/xdelta"
decoder_dir="$project_root/third_party/xdelta-code-table"
build_dir="$project_root/build/xdelta"

mkdir -p "$project_root/third_party" "$build_dir"

if ! git -C "$current_dir" rev-parse --git-dir >/dev/null 2>&1; then
  git clone https://github.com/jmacd/xdelta.git "$current_dir"
  git -C "$current_dir" checkout --detach "$current_commit"
fi
if [[ $(git -C "$current_dir" rev-parse HEAD) != "$current_commit" ]]; then
  echo "unexpected current xdelta commit in $current_dir" >&2
  exit 1
fi
if ! rg -q 'XD3_TRACE_INSTRUCTIONS' "$current_dir/xdelta3/xdelta3.c"; then
  git -C "$current_dir" apply "$project_root/patches/xdelta3-trace.patch"
fi
if ! cmp -s \
  "$project_root/patches/xdelta3-trace.patch" \
  <(git -C "$current_dir" diff -- xdelta3/xdelta3.c); then
  echo "xdelta trace worktree differs from the pinned instrumentation patch" >&2
  exit 1
fi

if ! git -C "$decoder_dir" rev-parse --git-dir >/dev/null 2>&1; then
  git clone https://github.com/jmacd/xdelta-gpl.git "$decoder_dir"
  git -C "$decoder_dir" checkout --detach "$decoder_commit"
fi
if [[ $(git -C "$decoder_dir" rev-parse HEAD) != "$decoder_commit" ]]; then
  echo "unexpected historical xdelta commit in $decoder_dir" >&2
  exit 1
fi
if [[ -n $(git -C "$decoder_dir" status --porcelain --untracked-files=no) ]]; then
  echo "historical decoder worktree has source modifications" >&2
  exit 1
fi

common_current=(
  -O2 -std=c99 -I"$current_dir/xdelta3"
  -DSIZEOF_SIZE_T=8 -DSIZEOF_UNSIGNED_INT=4
  -DSIZEOF_UNSIGNED_LONG=8 -DSIZEOF_UNSIGNED_LONG_LONG=8
  -DREGRESSION_TEST=0 -DSECONDARY_DJW=1 -DSECONDARY_FGK=0
  -DSECONDARY_LZMA=0 -DXD3_MAIN=1 -DXD3_DEBUG=0
  -DXD3_USE_LARGESIZET=1 -DXD3_POSIX=1 -DXD3_STDIO=0
  -DEXTERNAL_COMPRESSION=0 -DSHELL_TESTS=0 -DXD3_ARMOR=0
  -Wno-format-truncation -Wno-switch-unreachable
)

gcc "${common_current[@]}" \
  "$current_dir/xdelta3/xdelta3.c" -lm -o "$build_dir/xdelta3-current"
gcc "${common_current[@]}" -DXD3_TRACE_INSTRUCTIONS=1 \
  "$current_dir/xdelta3/xdelta3.c" -lm -o "$build_dir/xdelta3-trace"

gcc -O2 -std=c99 -I"$decoder_dir/xdelta3" \
  -DSIZEOF_SIZE_T=8 -DGENERIC_ENCODE_TABLES=1 \
  -DGENERIC_ENCODE_TABLES_COMPUTE=0 -DREGRESSION_TEST=0 \
  -DSECONDARY_DJW=0 -DSECONDARY_FGK=0 -DSECONDARY_LZMA=0 \
  -DXD3_POSIX=1 -DXD3_USE_LARGEFILE64=1 -DXD3_MAIN=1 \
  -DXD3_ENCODER=1 -DXD3_STDIO=0 -DEXTERNAL_COMPRESSION=0 \
  -DVCDIFF_TOOLS=1 -DXD3_DEBUG=0 -DXD3_HARDMAXWINSIZE='(1U<<26)' \
  -Wno-format-truncation -Wno-switch-unreachable \
  "$decoder_dir/xdelta3/xdelta3.c" -lm \
  -o "$build_dir/xdelta3-rfc-custom-decoder"

"$build_dir/xdelta3-current" -V
"$build_dir/xdelta3-rfc-custom-decoder" -V
