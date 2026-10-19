#!/usr/bin/env bash
# =============================================================================
# 在安置机本地执行：清理旧代码，仅保留数据库与必要配置/数据
#
# 用法：
#   bash deploy/remote-stash-and-clean.sh
#   bash deploy/remote-stash-and-clean.sh --dry-run   # 仅预览
#
# 默认保留：
#   - agent_framework/backend/data/   （SQLite、llm_config、quota 等）
#   - config/chickensv.env            （API Key，不覆盖）
#   - refpanel/ data/ annotation/     （生信业务数据，体积大）
#
# 若只要数据库、其余业务数据也从开发机重同步：
#   PURGE_DATA_DIRS=1 bash deploy/remote-stash-and-clean.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CHICKENSV_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

log() { echo "[clean] $*"; }
run() { if [[ "$DRY" == "1" ]]; then log "[dry-run] $*"; else eval "$@"; fi; }

STASH="${ROOT}/.deploy-stash-$$"
mkdir -p "${STASH}"

log "项目根: ${ROOT}"

# ---------- 暂存必保留项 ----------
if [[ -d "${ROOT}/agent_framework/backend/data" ]]; then
  log "暂存 backend/data ..."
  run "cp -a '${ROOT}/agent_framework/backend/data' '${STASH}/backend-data'"
fi

if [[ -f "${ROOT}/config/chickensv.env" ]]; then
  log "暂存 config/chickensv.env ..."
  run "mkdir -p '${STASH}/config' && cp -a '${ROOT}/config/chickensv.env' '${STASH}/config/'"
fi

if [[ "${PURGE_DATA_DIRS:-0}" != "1" ]]; then
  for d in refpanel data annotation; do
    if [[ -d "${ROOT}/${d}" ]]; then
      log "暂存 ${d}/ ..."
      run "cp -a '${ROOT}/${d}' '${STASH}/${d}'"
    fi
  done
else
  log "PURGE_DATA_DIRS=1：不保留 refpanel/data/annotation（请随后从开发机 sync）"
fi

# ---------- 删除旧项目内容（含 agent_framework/deploy 等 legacy）----------
log "删除旧代码与目录 ..."
if [[ "$DRY" == "1" ]]; then
  log "[dry-run] rm -rf ${ROOT}/agent_framework ${ROOT}/mcp ${ROOT}/deploy ${ROOT}/config ..."
else
  rm -rf \
    "${ROOT}/agent_framework" \
    "${ROOT}/mcp" \
    "${ROOT}/deploy" \
    "${ROOT}/tests" \
    "${ROOT}/_backups" \
    "${ROOT}/.deploy-stash-"* 2>/dev/null || true

  # 根目录旧脚本/文档（保留 STASH 当前目录）
  find "${ROOT}" -maxdepth 1 -mindepth 1 ! -path "${STASH}" -exec rm -rf {} + 2>/dev/null || true
fi

# ---------- 恢复暂存 ----------
run "mkdir -p '${ROOT}/agent_framework/backend' '${ROOT}/config'"
if [[ -d "${STASH}/backend-data" ]]; then
  run "mv '${STASH}/backend-data' '${ROOT}/agent_framework/backend/data'"
  log "已恢复 backend/data"
fi
if [[ -f "${STASH}/config/chickensv.env" ]]; then
  run "mv '${STASH}/config/chickensv.env' '${ROOT}/config/chickensv.env'"
  run "chmod 600 '${ROOT}/config/chickensv.env'"
  log "已恢复 config/chickensv.env"
fi
if [[ "${PURGE_DATA_DIRS:-0}" != "1" ]]; then
  for d in refpanel data annotation; do
    if [[ -d "${STASH}/${d}" ]]; then
      run "mv '${STASH}/${d}' '${ROOT}/${d}'"
      log "已恢复 ${d}/"
    fi
  done
fi

run "rm -rf '${STASH}'"

log "清理完成。下一步在开发机执行: bash publish.sh"
log "或在安置机已有新代码后: bash deploy/remote-post-deploy.sh"
