#!/usr/bin/env bash
# =============================================================================
# 安置机一键初始化（清理 legacy + 创建 gaoai + 依赖 + systemd + 重启）
#
# 在安置机上执行（需先 rsync 最新代码到 CHICKENSV_ROOT）：
#   cd /path/to/ProjectAi3
#   bash deploy/remote-bootstrap.sh
#
# 仅预览清理：
#   bash deploy/remote-bootstrap.sh --dry-run
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CHICKENSV_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
export CHICKENSV_ROOT="${ROOT}"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

log() { echo "[bootstrap] $*"; }

cd "${ROOT}"

# ---------- 1. 清理旧脚本/目录 ----------
if [[ "$DRY" == "1" ]]; then
  bash deploy/purge-legacy.sh --dry-run
else
  bash deploy/purge-legacy.sh
fi

# ---------- 2. 停掉占用端口的旧进程 ----------
if [[ "$DRY" != "1" ]]; then
  log "停止旧 MCP/Backend 进程..."
  pkill -f 'mcp_http_server.py' 2>/dev/null || true
  pkill -f 'uvicorn app.main:app' 2>/dev/null || true
  sleep 2
fi

# ---------- 3. Conda 环境 gaoai ----------
if [[ "$DRY" == "1" ]]; then
  log "[dry-run] bash setup-env.sh"
else
  bash setup-env.sh
  bash setup-env.sh --check
fi

# ---------- 4. systemd ----------
if [[ "$DRY" == "1" ]]; then
  log "[dry-run] 更新 systemd + restart"
  exit 0
fi

if command -v sudo >/dev/null 2>&1; then
  log "更新 systemd 单元..."
  render_template "${DEPLOY_DIR}/systemd/chickensv-mcp.service.template" /tmp/chickensv-mcp.service
  render_template "${DEPLOY_DIR}/systemd/chickensv-backend.service.template" /tmp/chickensv-backend.service
  sudo cp /tmp/chickensv-mcp.service /tmp/chickensv-backend.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable chickensv-mcp chickensv-backend
  sudo systemctl restart chickensv-mcp chickensv-backend
fi

sleep 3
if systemctl is-active --quiet chickensv-mcp 2>/dev/null; then
  curl -sf http://127.0.0.1:9802/health && log "MCP OK (systemd)" || log "WARN: MCP 未就绪"
else
  log "WARN: chickensv-mcp 未 active，请先完成 setup-env.sh"
fi
if systemctl is-active --quiet chickensv-backend 2>/dev/null; then
  curl -sf http://127.0.0.1:9801/api/v1/health && log "Backend OK (systemd)" || log "WARN: Backend 未就绪"
else
  log "WARN: chickensv-backend 未 active"
fi

log "完成。请确认 config/chickensv.env 中 API Key 与 DEBUG=false（生产）"
