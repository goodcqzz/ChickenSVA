#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="${ROOT}/deploy"
# shellcheck source=deploy/lib/common.sh
source "${DEPLOY}/lib/common.sh"
BE="${BE_DIR}"; RP="${REFPANEL_DIR}"; ERR=0

echo "PROJECT_AI3_ROOT=${CHICKENSV_ROOT}"
check_f() { [[ -f "$2" ]] && echo "OK  $1" || { echo "MISSING $1 ($2)" >&2; ERR=1; }; }
check_d() { [[ -d "$2" ]] && echo "OK  $1" || { echo "MISSING $1 ($2)" >&2; ERR=1; }; }

java -version 2>&1 | head -1 || ERR=1
check_f beagle.jar "${RP}/beagle.jar"
check_f "参考 VCF" "${RP}/2063.10.14.imiss0.2.panel.plink_ph.AN_AC.reiid.vcf.gz"
check_d agent_framework "${AF_ROOT}"
check_d mcp "${MCP_DIR}"
[[ -f "${CHICKENSV_ROOT}/config/chickensv.env" ]] && echo "OK  config/chickensv.env" || { echo "MISSING config/chickensv.env" >&2; ERR=1; }
[[ $ERR -eq 0 ]] && echo "全部关键项已就绪。" || exit 1
