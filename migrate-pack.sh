#!/usr/bin/env bash
# ProjectAi3 完整迁移包
# 用法: screen -S pack && bash migrate-pack.sh
#       MIGRATE_OUT_DIR=/path/to/out bash migrate-pack.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${MIGRATE_OUT_DIR:-${ROOT}/migrate-out}"
STAMP="$(date +%Y%m%d_%H%M%S)"
UNCOMPRESSED="${MIGRATE_UNCOMPRESSED:-0}"

mkdir -p "${OUT_DIR}"
if [[ "${UNCOMPRESSED}" == "1" ]]; then
  ARCHIVE="${OUT_DIR}/projectai3-migrate-${STAMP}.tar"
else
  ARCHIVE="${OUT_DIR}/projectai3-migrate-${STAMP}.tar.gz"
fi
MANIFEST="${OUT_DIR}/projectai3-migrate-${STAMP}.MANIFEST.txt"
LOG="${OUT_DIR}/projectai3-migrate-${STAMP}.pack.log"

exec > >(tee -a "${LOG}") 2>&1
log() { echo "[$(date '+%F %T')] $*"; }

log "========== ProjectAi3 迁移打包 =========="
log "项目根: ${ROOT}"
log "输出: ${ARCHIVE}"

cd "${ROOT}"
for d in agent_framework mcp deploy; do
  [[ -d "${ROOT}/${d}" ]] || { log "错误: 缺少 ${d}/"; exit 1; }
done

INCLUDE=(
  agent_framework mcp deploy
  start.sh stop.sh setup-env.sh setup-dev.sh setup-production.sh verify.sh
  sync.sh publish.sh restore-migrate.sh migrate-pack.sh install.sh
  requirements-project.txt environment.yml
)
[[ -d data ]] && INCLUDE+=(data) || log "警告: 无 data/"
[[ -d config ]] && INCLUDE+=(config) || log "警告: 无 config/"
[[ -d refpanel && "${SKIP_REFPANEL:-0}" != "1" ]] && INCLUDE+=(refpanel) || log "跳过 refpanel"
[[ -d annotation && "${SKIP_ANNOTATION:-0}" != "1" ]] && INCLUDE+=(annotation) || log "跳过 annotation"

TAR_EXCLUDES=(
  --exclude='.git' --exclude='**/.git' --exclude='venv' --exclude='.venv'
  --exclude='**/node_modules' --exclude='**/.vite' --exclude='**/logs'
  --exclude='**/__pycache__' --exclude='**/*.pyc' --exclude='**/*.pid'
  --exclude='_backups' --exclude='chickensv-migrate-*.tar.gz'
  --exclude='projectai3-migrate-*.tar' --exclude='projectai3-migrate-*.tar.gz'
)
[[ "${MIGRATE_INCLUDE_ENV:-0}" != "1" ]] && TAR_EXCLUDES+=(--exclude='config/chickensv.env')
[[ "${SKIP_AGENT_DATA:-0}" == "1" ]] && TAR_EXCLUDES+=(--exclude='agent_framework/data')

{
  echo "ProjectAi3 migration package"
  echo "Created: $(date -Iseconds)"
  echo "Source: ${ROOT}"
  echo "Archive: ${ARCHIVE}"
  du -sh "${INCLUDE[@]}" 2>/dev/null || true
} > "${MANIFEST}"

TAR_CMD=(tar -cvf)
[[ "${UNCOMPRESSED}" != "1" ]] && TAR_CMD=(tar -czvf)
"${TAR_CMD[@]}" "${ARCHIVE}" "${TAR_EXCLUDES[@]}" "${INCLUDE[@]}"

ls -lh "${ARCHIVE}"
echo "${ARCHIVE}" > "${OUT_DIR}/projectai3-migrate-LATEST.txt"
log "完成。目标机: bash restore-migrate.sh $(basename "${ARCHIVE}")"
