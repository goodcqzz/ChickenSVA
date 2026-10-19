#!/usr/bin/env bash
# Run the ChickenSVA miniature demo: SV query + Beagle imputation benchmark.
# Usage:  bash examples/run_demo.sh
# Needs:  python3 with pysam; java (Beagle is downloaded automatically if absent).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${CHICKENSV_PYTHON:-python3}"   # e.g. CHICKENSV_PYTHON=~/miniconda3/envs/gaoai/bin/python3.11

if ! "${PY}" -c "import pysam" 2>/dev/null; then
  echo "pysam 未安装。Install it first, e.g.:  conda env create -f environment.yml  (or)  pip install pysam" >&2
  exit 1
fi
if ! command -v java >/dev/null 2>&1; then
  echo "java 未安装 (Beagle 需要Java运行时 / Beagle needs a Java runtime)." >&2
  exit 1
fi

"${PY}" "${HERE}/run_demo.py"
