#!/usr/bin/env bash
# 安置机发布后清理旧目录并更新 systemd
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CHICKENSV_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
DEPLOY="${ROOT}/deploy"
# shellcheck source=lib/common.sh
source "${DEPLOY}/lib/common.sh"

log() { echo "[post-deploy] $*"; }

bash "${ROOT}/deploy/purge-legacy.sh" 2>/dev/null || true

# ---------- 删除已废弃路径（补充）----------
LEGACY=(
  "${ROOT}/agent_framework/deploy"
  "${ROOT}/agent_framework/start.sh"
  "${ROOT}/agent_framework/stop.sh"
  "${ROOT}/_backups"
)
for p in "${LEGACY[@]}"; do
  if [[ -e "$p" ]]; then
    log "删除旧路径: $p"
    rm -rf "$p"
  fi
done

# ---------- 更新 systemd（ExecStart 指向 deploy/bin/）----------
if command -v sudo >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null; then
    log "更新 systemd 单元..."
    render_template "${DEPLOY}/systemd/chickensv-mcp.service.template" /tmp/chickensv-mcp.service
    render_template "${DEPLOY}/systemd/chickensv-backend.service.template" /tmp/chickensv-backend.service
    sudo cp /tmp/chickensv-mcp.service /tmp/chickensv-backend.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable chickensv-mcp chickensv-backend 2>/dev/null || true
  else
    log "跳过 systemd（需 sudo 无密码或手动执行 cp + daemon-reload）"
  fi
fi

# ---------- 依赖（可选）----------
if ! bash "${ROOT}/deploy/bin/diagnose-runtime.sh" 2>/dev/null; then
  log "Conda/依赖未就绪，尝试 setup-env.sh ..."
  bash "${ROOT}/setup-env.sh" || log "WARN: setup-env 失败，请手动执行"
fi
PIP="${HOME}/miniconda3/envs/gaoai/bin/pip"
if [[ -x "$PIP" && -f "${ROOT}/requirements-project.txt" ]]; then
  log "更新 pip 依赖..."
  "$PIP" install -q -r "${ROOT}/requirements-project.txt" || true
fi

# ---------- 重启 ----------
if command -v sudo >/dev/null 2>&1 && sudo -n systemctl restart chickensv-mcp chickensv-backend 2>/dev/null; then
  log "已重启 chickensv-mcp / chickensv-backend"
else
  log "请手动: sudo systemctl restart chickensv-mcp chickensv-backend"
fi

sleep 2
_systemd_active() {
  systemctl is-active --quiet "$1" 2>/dev/null
}

if curl -sf http://127.0.0.1:9802/health >/dev/null; then
  if _systemd_active chickensv-mcp; then
    log "MCP OK (systemd)"
  else
    log "WARN: MCP 有响应但 systemd 未 active（可能是旧进程占用 9802）"
    log "      请: pkill -f mcp_http_server.py && sudo systemctl restart chickensv-mcp"
  fi
else
  log "WARN: MCP health 失败"
fi

if curl -sf http://127.0.0.1:9801/api/v1/health >/dev/null; then
  if _systemd_active chickensv-backend; then
    log "Backend OK (systemd)"
  else
    log "WARN: Backend 有响应但 systemd 未 active"
  fi
else
  log "WARN: Backend health 失败（gaoai 未装好时常如此）"
fi

log "完成。配置: ${ROOT}/config/chickensv.env（未覆盖）"
