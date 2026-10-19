#!/usr/bin/env bash
# 停止 ChickenSV 应用进程（MCP / 后端 / Vite / serve-proxy）
# 永不停止系统 Nginx（80/443）——学校反代入口必须保持。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AF="${ROOT}/agent_framework"
# shellcheck source=deploy/lib/ports.sh
source "${ROOT}/deploy/lib/ports.sh"

port_pids() {
  local port="$1" pids=""
  pids="$(lsof -ti:"${port}" 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    pids="$(ss -tlnp "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ' || true)"
  fi
  echo "${pids}"
}

stop_port() {
  local port="$1"
  if [[ "${port}" == "80" || "${port}" == "443" ]]; then
    echo "跳过端口 ${port}（系统 Nginx / 学校反代）"
    return 0
  fi
  local pids
  pids="$(port_pids "${port}")"
  [[ -z "${pids}" ]] && return 0
  echo "${pids}" | tr ' ' '\n' | grep -E '^[0-9]+$' | xargs -r kill -TERM 2>/dev/null || true
  local i
  for ((i = 1; i <= 8; i++)); do
    [[ -z "$(port_pids "${port}")" ]] && return 0
    sleep 0.5
  done
  pids="$(port_pids "${port}")"
  [[ -n "${pids}" ]] && echo "${pids}" | tr ' ' '\n' | grep -E '^[0-9]+$' | xargs -r kill -KILL 2>/dev/null || true
}

# 若当前就是 systemd 在跑，尝试无密码停 unit；失败则只杀进程（unit 可能被 Restart= 拉起）
if systemctl is-active chickensv-mcp >/dev/null 2>&1 || systemctl is-active chickensv-backend >/dev/null 2>&1; then
  if sudo -n true >/dev/null 2>&1; then
    sudo -n systemctl stop chickensv-mcp chickensv-backend || true
  else
    echo "systemd 正在托管 chickensv-*，无密码 sudo 无法 systemctl stop。"
    echo "若停完又被拉起，请在终端执行: sudo systemctl stop chickensv-mcp chickensv-backend"
  fi
fi

stop_port "${MCP_PORT}"
stop_port "${BACKEND_PORT}"

# 9800：仅停 serve-proxy / Vite，不杀系统 Nginx
pkill -TERM -f 'deploy/bin/serve-proxy.py' 2>/dev/null || true
pkill -TERM -f "vite.*--port ${FRONTEND_PORT}" 2>/dev/null || true
if ! systemctl is-active nginx >/dev/null 2>&1; then
  stop_port "${FRONTEND_PORT}"
fi

pkill -TERM -f 'mcp_http_server.py' 2>/dev/null || true
pkill -TERM -f 'uvicorn app.main:app' 2>/dev/null || true
sleep 1
pkill -KILL -f 'mcp_http_server.py' 2>/dev/null || true
pkill -KILL -f 'uvicorn app.main:app' 2>/dev/null || true

rm -f "${AF}/backend.pid" "${AF}/frontend.pid" "${AF}/mcp.pid" "${AF}/proxy.pid"

echo "已停止 MCP / 后端 / 前端代理。系统 Nginx 未动（学校反代仍指向 :80）。"
echo "启动: bash ${ROOT}/start.sh --backend   状态: bash ${ROOT}/start.sh --status"
