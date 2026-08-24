#!/usr/bin/env bash
set -euo pipefail

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

./scripts/bootstrap_tools.sh
python3 benchmark/prepare_artifacts.py
python3 benchmark/prepare_compiled.py
sha256sum -c benchmark/preregistration-v1.sha256
sha256sum -c benchmark/build-recipes-v1.sha256
sha256sum -c benchmark/artifact-lock-v1.sha256
sha256sum -c benchmark/analysis-spec-v1.sha256
PYTHONPATH=src:. python3 -m pytest -q
if jq -e '.status == "STOP"' results/generality/validity-decision-v1.json >/dev/null; then
  ./scripts/reproduce_validity_stop.sh
  exit 0
fi
python3 benchmark/run_corpus.py --workers 1
python3 benchmark/extract_features.py
python3 benchmark/verify_corpus.py
python3 benchmark/analyze_corpus.py

if jq -e '.passes == true' results/generality/gate-decision-v1.json >/dev/null; then
  python3 benchmark/run_table_bank.py
fi
