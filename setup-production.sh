#!/usr/bin/env bash
# =============================================================================
# ChickenSV 安置机一键生产部署
#
# 用法（在仓库根目录）:
#   bash setup-production.sh              # 完整：环境 + systemd + 前端构建 + Nginx
#   bash setup-production.sh --skip-nginx # 不装 Nginx，用 serve-proxy 占 9800
#   bash setup-production.sh --skip-build # 跳过 npm build（需已有 dist/）
#
# 前置：config/chickensv.env 已填写 API Key
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="${ROOT}/deploy"
# shellcheck source=deploy/lib/common.sh
source "${DEPLOY}/lib/common.sh"
# shellcheck source=deploy/lib/ports.sh
source "${DEPLOY}/lib/ports.sh"

SKIP_NGINX=0
SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --skip-nginx) SKIP_NGINX=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
  esac
done

log "ChickenSV 生产部署"
log "根目录: ${CHICKENSV_ROOT}"
log "端口: 对外 ${CHICKENSV_PUBLIC_PORT} | 后端 ${CHICKENSV_BACKEND_PORT} | MCP ${CHICKENSV_MCP_PORT}"

ENV_FILE="${CHICKENSV_ROOT}/config/chickensv.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${CHICKENSV_ROOT}/config/chickensv.env.example" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  die "已创建 ${ENV_FILE}，请填写 API Key 后重新运行本脚本"
fi

log "[1/6] Conda 环境 (gaoai)..."
bash "${ROOT}/setup-env.sh"

log "[2/6] 安装生产配置 + systemd..."
INSTALL_ARGS=(--production --systemd --skip-venv)
[[ "${SKIP_BUILD}" == "1" ]] && INSTALL_ARGS+=(--skip-frontend)
bash "${DEPLOY}/install.sh" "${INSTALL_ARGS[@]}"

if [[ "${SKIP_BUILD}" != "1" ]]; then
  if command -v npm >/dev/null 2>&1; then
    log "[3/6] 前端构建..."
    (cd "${FE_DIR}" && npm ci && npm run build)
  else
    log "[3/6] 跳过前端构建（无 npm）"
    [[ -f "${FE_DIR}/dist/index.html" ]] || die "缺少 dist/，请安装 Node.js 后重试或去掉 --skip-build 前先手动构建"
  fi
else
  log "[3/6] 跳过前端构建 (--skip-build)"
  [[ -f "${FE_DIR}/dist/index.html" ]] || die "缺少 dist/index.html"
fi

log "[4/6] 停止开发进程..."
bash "${ROOT}/stop.sh" 2>/dev/null || true
pkill -f 'deploy/bin/serve-proxy.py' 2>/dev/null || true
sleep 1

log "[5/6] 启动 MCP + 后端 (systemd)..."
if command -v sudo >/dev/null 2>&1; then
  sudo systemctl start chickensv-mcp chickensv-backend 2>/dev/null || {
    log "WARN: systemd 启动失败，尝试 bash start.sh --backend"
    bash "${ROOT}/start.sh" --backend
  }
else
  bash "${ROOT}/start.sh" --backend
fi

sleep 2
curl -sf "http://127.0.0.1:${CHICKENSV_BACKEND_PORT}/api/v1/health" >/dev/null || die "后端未就绪，查看 journalctl -u chickensv-backend"
curl -sf "http://127.0.0.1:${CHICKENSV_MCP_PORT}/health" >/dev/null || die "MCP 未就绪，查看 journalctl -u chickensv-mcp"

log "[6/6] 对外入口 :${CHICKENSV_PUBLIC_PORT}..."
if [[ "${SKIP_NGINX}" == "1" ]]; then
  bash "${DEPLOY}/bin/start-public-proxy.sh"
else
  if command -v nginx >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    bash "${DEPLOY}/install-nginx.sh"
  else
    log "WARN: 无 nginx/sudo，改用 serve-proxy"
    bash "${DEPLOY}/bin/start-public-proxy.sh"
  fi
fi

SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

========================================
生产部署完成
========================================
访问:     http://${SERVER_IP:-localhost}:${CHICKENSV_PUBLIC_PORT}/
健康:     curl -s http://127.0.0.1:${CHICKENSV_PUBLIC_PORT}/api/v1/health
配置:     ${ENV_FILE}
服务:     sudo systemctl status chickensv-mcp chickensv-backend nginx
日志:     ${AF_ROOT}/logs/  |  journalctl -u chickensv-backend -f
Dify:     本机 http://127.0.0.1/v1（端口 80，与 ChickenSV 9800 互不冲突）
========================================
EOF
