#!/usr/bin/env bash
# 无 sudo 时在 CHICKENSV_PUBLIC_PORT（默认 9800）提供静态 dist + API/WS 反代
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/runtime.sh
source "${SCRIPT_DIR}/../lib/runtime.sh"

LOGS_DIR="${AF_ROOT}/logs"
PID_FILE="${AF_ROOT}/proxy.pid"
DIST="${FE_DIR}/dist/index.html"

mkdir -p "${LOGS_DIR}"

if systemctl is-active nginx >/dev/null 2>&1; then
  if ss -tln | grep -q ":${CHICKENSV_PUBLIC_PORT} "; then
    echo "系统 Nginx 已在 :${CHICKENSV_PUBLIC_PORT} 监听，跳过 serve-proxy"
    exit 0
  fi
fi

pkill -f 'deploy/bin/serve-proxy.py' 2>/dev/null || true
sleep 1

if ss -tln | grep -q ":${CHICKENSV_PUBLIC_PORT} "; then
  echo "错误: 端口 ${CHICKENSV_PUBLIC_PORT} 仍被占用，请先 bash stop.sh 或 sudo systemctl stop nginx" >&2
  ss -tlnp | grep ":${CHICKENSV_PUBLIC_PORT} " || true
  exit 1
fi

[[ -f "${DIST}" ]] || {
  echo "错误: 缺少 ${DIST}，请先构建前端: cd agent_framework/frontend && npm run build" >&2
  exit 1
}

require_backend_venv || exit 1
nohup "${PROJECT_PY}" "${SCRIPT_DIR}/serve-proxy.py" >"${LOGS_DIR}/proxy.log" 2>&1 &
echo $! >"${PID_FILE}"
sleep 2

if curl -sf "http://127.0.0.1:${CHICKENSV_PUBLIC_PORT}/api/v1/health" >/dev/null; then
  echo "serve-proxy 已启动: http://127.0.0.1:${CHICKENSV_PUBLIC_PORT}"
else
  echo "WARN: serve-proxy 可能未就绪，查看 ${LOGS_DIR}/proxy.log" >&2
  tail -10 "${LOGS_DIR}/proxy.log" 2>/dev/null || true
  exit 1
fi
