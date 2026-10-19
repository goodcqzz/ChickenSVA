#!/usr/bin/env bash
# ChickenSV 一键启动 / 安全重启
#
# 用法:
#   bash start.sh              # 智能默认：Nginx 已对外则只重启 MCP+后端；否则开发模式
#   bash start.sh --dev        # 强制开发：MCP + 后端(热重载) + Vite
#   bash start.sh --prod       # 生产：MCP + 后端；保留系统 Nginx，不启 Vite
#   bash start.sh --backend    # 仅 MCP + 后端（学校反代安全重启，不碰 Nginx）
#   bash start.sh --status     # 只看状态，不重启
#   bash start.sh --help
#
# 红线：永不停止 / reload / 占用 80 端口上的系统 Nginx。
# 学校外网反代指向本机 80 时，请用 --backend（或无参数时的智能默认）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${ROOT}/deploy"
# shellcheck source=deploy/lib/runtime.sh
source "${DEPLOY_DIR}/lib/runtime.sh"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

MODE=""
for arg in "$@"; do
  case "$arg" in
    --dev|--development) MODE=dev ;;
    --prod|--production) MODE=prod ;;
    --backend|--safe) MODE=backend ;;
    --status) MODE=status ;;
    -h|--help)
      sed -n '2,13p' "$0"
      exit 0
      ;;
    *)
      echo -e "${RED}未知参数: $arg${NC}" >&2
      echo "用法: bash start.sh [--dev|--prod|--backend|--status|--help]" >&2
      exit 1
      ;;
  esac
done

MCP_WAIT="${MCP_STARTUP_WAIT:-30}"
LOGS_DIR="${AF_ROOT}/logs"
mkdir -p "$LOGS_DIR"

# ---------- 工具函数 ----------

port_listening() {
  local port="$1"
  ss -tln | grep -qE ":${port}[[:space:]]"
}

nginx_active() {
  systemctl is-active nginx >/dev/null 2>&1
}

# 系统 Nginx 已在对外端口上提供入口（80 或 CHICKENSV_PUBLIC_PORT）
public_nginx_ready() {
  nginx_active || return 1
  port_listening 80 || port_listening "${CHICKENSV_PUBLIC_PORT}"
}

# 取占用某端口的 PID（可能多个）
port_pids() {
  local port="$1" pids=""
  pids="$(lsof -ti:"${port}" 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    pids="$(ss -tlnp "sport = :${port}" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u | tr '\n' ' ' || true)"
  fi
  echo "${pids}"
}

# 优雅停端口上的进程；永远不杀 80（系统 Nginx / 学校反代入口）
stop_port() {
  local port="$1"
  if [[ "${port}" == "80" || "${port}" == "443" ]]; then
    echo -e "${YELLOW}  跳过端口 ${port}（系统 Nginx / 学校反代，本脚本永不停止）${NC}"
    return 0
  fi
  local pids
  pids="$(port_pids "${port}")"
  [[ -z "${pids}" ]] && return 0
  echo "${pids}" | tr ' ' '\n' | grep -E '^[0-9]+$' | xargs -r kill -TERM 2>/dev/null || true
  local i
  for ((i = 1; i <= 8; i++)); do
    pids="$(port_pids "${port}")"
    [[ -z "${pids}" ]] && return 0
    sleep 0.5
  done
  pids="$(port_pids "${port}")"
  if [[ -n "${pids}" ]]; then
    echo "${pids}" | tr ' ' '\n' | grep -E '^[0-9]+$' | xargs -r kill -KILL 2>/dev/null || true
    sleep 0.5
  fi
}

stop_pattern() {
  pkill -TERM -f "$1" 2>/dev/null || true
}

# 停 MCP / 后端 / Vite / serve-proxy；不动 Nginx
stop_app_processes() {
  stop_port "${BACKEND_PORT}"
  stop_port "${MCP_PORT}"
  stop_pattern "mcp_http_server.py"
  stop_pattern "uvicorn app.main:app"
  stop_pattern "vite.*--port ${FRONTEND_PORT}"
  stop_pattern "deploy/bin/serve-proxy.py"
  # 开发模式才清 9800；生产 9800 若被 Nginx 占用则跳过（本机实际对外是 80）
  if [[ "${MODE}" == "dev" ]]; then
    if nginx_active && port_listening "${FRONTEND_PORT}"; then
      echo -e "${YELLOW}  端口 ${FRONTEND_PORT} 由 Nginx 占用，开发模式不杀该口${NC}"
    else
      stop_port "${FRONTEND_PORT}"
    fi
  fi
  rm -f "${AF_ROOT}/backend.pid" "${AF_ROOT}/frontend.pid" "${AF_ROOT}/mcp.pid" "${AF_ROOT}/proxy.pid"
}

write_listen_pid() {
  local port="$1" dest="$2"
  local pids
  pids="$(port_pids "${port}" | awk '{print $1}')"
  [[ -n "${pids}" ]] && echo "${pids}" > "${dest}" || true
}

try_systemd() {
  # 无密码 sudo 才能接管；否则继续用 nohup，避免卡在密码提示
  sudo -n true >/dev/null 2>&1
}

systemd_unit_exists() {
  [[ -f "/etc/systemd/system/${1}.service" ]] || systemctl cat "${1}.service" >/dev/null 2>&1
}

print_status() {
  echo -e "${CYAN}ChickenSV 运行状态${NC}  根目录: ${CHICKENSV_ROOT}"
  echo -e "  端口约定: 对外入口 80(学校反代) / ${CHICKENSV_PUBLIC_PORT}(备用) | 后端 ${CHICKENSV_BACKEND_PORT} | MCP ${CHICKENSV_MCP_PORT}"
  echo

  local item port url
  for item in \
    "MCP|${MCP_PORT}|http://127.0.0.1:${MCP_PORT}/health" \
    "Backend|${BACKEND_PORT}|http://127.0.0.1:${BACKEND_PORT}/api/v1/health"
  do
    IFS='|' read -r name port url <<<"${item}"
    if curl -sf "${url}" >/dev/null 2>&1; then
      echo -e "  ${GREEN}✓ ${name}${NC}  :${port}  healthy"
    elif port_listening "${port}"; then
      echo -e "  ${YELLOW}● ${name}${NC}  :${port}  在听但健康检查未通过"
    else
      echo -e "  ${RED}✗ ${name}${NC}  :${port}  未运行"
    fi
  done

  if nginx_active && port_listening 80; then
    echo -e "  ${GREEN}✓ Nginx${NC}     :80   系统服务运行中（学校反代入口，start/stop 不会动它）"
  elif nginx_active; then
    echo -e "  ${YELLOW}● Nginx${NC}     已运行，但未监听 80"
  else
    echo -e "  ${YELLOW}○ Nginx${NC}     未运行"
  fi

  if port_listening "${CHICKENSV_PUBLIC_PORT}"; then
    echo -e "  ${GREEN}● 备用入口${NC}  :${CHICKENSV_PUBLIC_PORT}  有进程在听"
  else
    echo -e "  ${BLUE}○ 备用入口${NC}  :${CHICKENSV_PUBLIC_PORT}  空闲"
  fi

  echo
  if systemd_unit_exists chickensv-mcp; then
    local mcp_st be_st
    mcp_st="$(systemctl is-active chickensv-mcp 2>/dev/null || true)"
    be_st="$(systemctl is-active chickensv-backend 2>/dev/null || true)"
    echo -e "  systemd: chickensv-mcp=${mcp_st:-unknown}  chickensv-backend=${be_st:-unknown}"
    if [[ "${mcp_st}" != "active" || "${be_st}" != "active" ]]; then
      echo -e "  ${YELLOW}说明: unit 已安装但当前未由 systemd 拉起（多半是 nohup 在跑）。开机后 systemd 会自动拉起。${NC}"
    fi
  else
    echo -e "  systemd: 未安装 chickensv-*.service（当前用 nohup 后台）"
  fi
}

# ---------- 智能默认：已对外则只重启后端，避免误启 Vite / 误占入口 ----------
if [[ -z "${MODE}" ]]; then
  if public_nginx_ready; then
    MODE=backend
    echo -e "${CYAN}检测到系统 Nginx 已对外，默认只重启 MCP + 后端（不碰反代）${NC}"
    echo -e "  若要开发热更新: bash start.sh --dev    仅看状态: bash start.sh --status"
  else
    MODE=dev
  fi
fi

if [[ "${MODE}" == "status" ]]; then
  print_status
  exit 0
fi

echo -e "${CYAN}  鸡基因组智能体 - 启动 (${MODE})${NC}  根目录: ${CHICKENSV_ROOT}"
echo -e "  端口: 对外 ${CHICKENSV_PUBLIC_PORT}(脚本备用) / 80(学校反代，不动) | 后端 ${CHICKENSV_BACKEND_PORT} | MCP ${CHICKENSV_MCP_PORT}"

if systemd_unit_exists chickensv-backend; then
  mcp_st="$(systemctl is-active chickensv-mcp 2>/dev/null || true)"
  be_st="$(systemctl is-active chickensv-backend 2>/dev/null || true)"
  if [[ "${mcp_st}" != "active" || "${be_st}" != "active" ]]; then
    echo -e "${YELLOW}  systemd unit 已启用但当前 inactive，本次用 nohup 重启；机器重启后由 systemd 接管。${NC}"
  fi
fi

stop_app_processes

# 优先：无密码 sudo 时走 systemd（开机自启一致）；否则 nohup
USE_SYSTEMD=0
if [[ "${MODE}" != "dev" ]] && systemd_unit_exists chickensv-backend && try_systemd; then
  USE_SYSTEMD=1
fi

start_mcp_backend() {
  local reload_flag="$1"

  if [[ "${USE_SYSTEMD}" == "1" ]]; then
    echo -e "${BLUE}[1/2] systemd: chickensv-mcp + chickensv-backend${NC}"
    sudo -n systemctl start chickensv-mcp chickensv-backend
    wait_http "http://127.0.0.1:${MCP_PORT}/health" "MCP" "${MCP_WAIT}" && echo -e "${GREEN}  ✓ MCP${NC}" || echo -e "${YELLOW}  ⚠ MCP 较慢${NC}"
    wait_http "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" "Backend" 20 || {
      echo -e "${RED}后端健康检查失败${NC}"
      sudo -n journalctl -u chickensv-backend -n 20 --no-pager || tail -15 "${LOGS_DIR}/backend.log"
      exit 1
    }
    echo -e "${GREEN}  ✓ Backend${NC}"
    return 0
  fi

  echo -e "${BLUE}[1/2] MCP :${MCP_PORT}${NC}"
  require_mcp_venv || { echo "请先: bash setup-env.sh"; exit 1; }
  nohup bash "${DEPLOY_DIR}/bin/run-mcp.sh" "${MCP_PORT}" > "${LOGS_DIR}/mcp.log" 2>&1 &
  wait_http "http://127.0.0.1:${MCP_PORT}/health" "MCP" "${MCP_WAIT}" && echo -e "${GREEN}  ✓ MCP${NC}" || echo -e "${YELLOW}  ⚠ MCP 较慢${NC}"
  write_listen_pid "${MCP_PORT}" "${AF_ROOT}/mcp.pid"

  echo -e "${BLUE}[2/2] Backend :${BACKEND_PORT}${NC}"
  export HOST=127.0.0.1 PORT="${BACKEND_PORT}" RELOAD="${reload_flag}" WORKERS="${WORKERS:-1}"
  nohup bash "${DEPLOY_DIR}/bin/run-backend.sh" > "${LOGS_DIR}/backend.log" 2>&1 &
  wait_http "http://127.0.0.1:${BACKEND_PORT}/api/v1/health" "Backend" 20 || {
    tail -15 "${LOGS_DIR}/backend.log"
    exit 1
  }
  echo -e "${GREEN}  ✓ Backend${NC}"
  write_listen_pid "${BACKEND_PORT}" "${AF_ROOT}/backend.pid"
}

if [[ "${MODE}" == "backend" ]]; then
  start_mcp_backend false
  echo
  echo -e "${GREEN}后端已后台就绪。系统 Nginx / 学校反代未改动。${NC}"
  echo -e "  停止应用: bash ${ROOT}/stop.sh     状态: bash ${ROOT}/start.sh --status"
  print_status
  exit 0
fi

if [[ "${MODE}" == "prod" ]]; then
  start_mcp_backend false
  echo -e "${BLUE}对外入口${NC}"
  if public_nginx_ready; then
    echo -e "${GREEN}  ✓ 系统 Nginx 已在对外端口运行，不启动 serve-proxy、不 reload Nginx${NC}"
  elif nginx_active; then
    echo -e "${YELLOW}  Nginx 已运行但未监听 80 / ${CHICKENSV_PUBLIC_PORT}，请检查 /etc/nginx/sites-enabled/chickensv${NC}"
  elif command -v nginx >/dev/null 2>&1 && [[ -f /etc/nginx/sites-enabled/chickensv ]]; then
    echo -e "${YELLOW}  Nginx 已配置但未运行。请在本机终端执行: sudo systemctl start nginx${NC}"
    echo -e "${YELLOW}  不自动启 serve-proxy，以免和学校反代抢入口。${NC}"
  elif [[ "${CHICKENSV_PUBLIC_PORT}" != "80" && "${CHICKENSV_PUBLIC_PORT}" != "443" ]]; then
    bash "${DEPLOY_DIR}/bin/start-public-proxy.sh" && echo -e "${GREEN}  ✓ 临时 serve-proxy :${CHICKENSV_PUBLIC_PORT}${NC}" || exit 1
  else
    echo -e "${YELLOW}  未安装 Nginx，且对外端口为 80，无法无 sudo 绑定。请: bash deploy/install-nginx.sh${NC}"
  fi
  echo
  echo -e "  停止应用: bash ${ROOT}/stop.sh     状态: bash ${ROOT}/start.sh --status"
  print_status
  exit 0
fi

# ---------- 开发模式 ----------
start_mcp_backend true

echo -e "${BLUE}Frontend :${FRONTEND_PORT}${NC}"
if command -v npm >/dev/null 2>&1; then
  cd "${FE_DIR}"
  [[ -d node_modules ]] || npm install
  # 仅本机，避免 --host 把开发服绑到 0.0.0.0
  nohup npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}" > "${LOGS_DIR}/frontend.log" 2>&1 &
  echo $! > "${AF_ROOT}/frontend.pid"
  echo -e "${GREEN}  ✓ Vite 开发服务器 http://127.0.0.1:${FRONTEND_PORT}${NC}"
  echo -e "  后端 :${BACKEND_PORT}、MCP :${MCP_PORT} 仅本机"
elif [[ -f "${FE_DIR}/dist/index.html" ]]; then
  echo -e "${YELLOW}  未找到 npm，使用 dist + serve-proxy${NC}"
  if public_nginx_ready; then
    echo -e "${GREEN}  系统 Nginx 已对外，不再启 serve-proxy${NC}"
  else
    bash "${DEPLOY_DIR}/bin/start-public-proxy.sh"
    echo -e "${GREEN}  访问 http://127.0.0.1:${CHICKENSV_PUBLIC_PORT}${NC}"
  fi
else
  echo -e "${YELLOW}  未找到 npm 且无 dist/，仅后端可用${NC}"
  echo -e "  构建前端: cd agent_framework/frontend && npm run build"
fi

echo
echo -e "停止: bash ${ROOT}/stop.sh  |  状态: bash ${ROOT}/start.sh --status  |  生产重启: bash ${ROOT}/start.sh --backend"
