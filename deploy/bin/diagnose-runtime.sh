#!/usr/bin/env bash
# 安置机运行时诊断（systemd 启动失败时执行）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export CHICKENSV_ROOT="${ROOT}"
# shellcheck source=deploy/lib/runtime.sh
source "${ROOT}/deploy/lib/runtime.sh"

echo "CHICKENSV_ROOT=${CHICKENSV_ROOT}"
echo "config/chickensv.env: $([[ -f ${ROOT}/config/chickensv.env ]] && echo OK || echo MISSING)"
echo "PROJECT_PY=${PROJECT_PY} ($([[ -x ${PROJECT_PY} ]] && echo OK || echo MISSING))"
echo "UVICORN=${UVICORN} ($([[ -x ${UVICORN} ]] && echo OK || echo MISSING))"

if [[ -x "${PROJECT_PY}" ]]; then
  "${PROJECT_PY}" --version
  "${PROJECT_PY}" -c "import fastapi, flask" 2>/dev/null && echo "OK fastapi+flask" || echo "WARN: 缺 pip 依赖，运行 setup-env.sh"
else
  echo ""
  echo "修复: bash ${ROOT}/setup-env.sh"
  exit 1
fi

echo ""
echo "手动试跑 MCP（Ctrl+C 退出）:"
echo "  bash ${ROOT}/deploy/bin/run-mcp.sh"
echo "手动试跑 Backend:"
echo "  bash ${ROOT}/deploy/bin/run-backend.sh"
