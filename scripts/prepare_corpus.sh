#!/usr/bin/env bash
set -euo pipefail

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

ensure_repository() {
  local url=$1
  local directory=$2
  if ! git -C "$directory" rev-parse --git-dir >/dev/null 2>&1; then
    git clone "$url" "$directory"
  fi
  git -C "$directory" fetch --tags origin
}

"$project_root/scripts/bootstrap_tools.sh"
ensure_repository \
  https://github.com/facebook/zstd.git \
  "$project_root/third_party/zstd-upstream"
ensure_repository \
  https://github.com/google/open-vcdiff.git \
  "$project_root/third_party/open-vcdiff"
git -C "$project_root/third_party/xdelta-code-table" fetch --tags origin

python3 "$project_root/scripts/make_git_tree_blob.py" \
  "$project_root/third_party/zstd-upstream" \
  794ea1b0afca0f020f4e57b6732332231fb23c70 \
  "$project_root/data/zstd-v1.5.6.treeblob"
python3 "$project_root/scripts/make_git_tree_blob.py" \
  "$project_root/third_party/zstd-upstream" \
  f8745da6ff1ad1e7bab384bd1f9d742439278e99 \
  "$project_root/data/zstd-v1.5.7.treeblob"
python3 "$project_root/scripts/make_git_tree_blob.py" \
  "$project_root/third_party/open-vcdiff" \
  af81c060f9948a9e91d3364f2ddc53c1f56c4447 \
  "$project_root/data/open-vcdiff-0.8.3.treeblob"
python3 "$project_root/scripts/make_git_tree_blob.py" \
  "$project_root/third_party/open-vcdiff" \
  9af10d36e691c15dceff04419b9e3a71ec5d8bec \
  "$project_root/data/open-vcdiff-0.8.4.treeblob"
python3 "$project_root/scripts/make_git_tree_blob.py" \
  "$project_root/third_party/xdelta-code-table" \
  c6493c5a57e1edc95fa27123e86fe14c3695f284 \
  "$project_root/data/xdelta-v3.0.10.treeblob"
python3 "$project_root/scripts/make_git_tree_blob.py" \
  "$project_root/third_party/xdelta-code-table" \
  81aebf78ae67c29f528088d65743643e5355e3d3 \
  "$project_root/data/xdelta-v3.0.11.treeblob"
curl -fL --retry 3 \
  --output "$project_root/data/zstd-v1.5.6-win64.zip" \
  https://github.com/facebook/zstd/releases/download/v1.5.6/zstd-v1.5.6-win64.zip
curl -fL --retry 3 \
  --output "$project_root/data/zstd-v1.5.7-win64.zip" \
  https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-v1.5.7-win64.zip

cd "$project_root"
sha256sum --check corpus/data.sha256
