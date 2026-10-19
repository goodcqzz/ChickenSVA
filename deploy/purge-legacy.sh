#!/usr/bin/env bash
# 安置机：删除已知废弃路径（不删 backend/data、chickensv.env、业务数据）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CHICKENSV_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

log() { echo "[purge] $*"; }
rm_path() {
  local p="$1"
  [[ -e "$p" ]] || return 0
  if [[ "$DRY" == "1" ]]; then
    log "[dry-run] rm -rf $p"
  else
    log "删除: $p"
    rm -rf "$p"
  fi
}

log "清理安置机 legacy 路径 (${ROOT})"

# 旧 deploy 布局
rm_path "${ROOT}/agent_framework/deploy"
rm_path "${ROOT}/agent_framework/start.sh"
rm_path "${ROOT}/agent_framework/stop.sh"
rm_path "${ROOT}/deploy.sh"
rm_path "${ROOT}/start.py"
rm_path "${ROOT}/frontend"
rm_path "${ROOT}/docs"
rm_path "${ROOT}/venv"
rm_path "${ROOT}/.venv"
rm_path "${ROOT}/_backups"

# 运行时垃圾
rm_path "${ROOT}/agent_framework/logs"
rm_path "${ROOT}/agent_framework/backend/logs"
rm_path "${ROOT}/agent_framework/frontend/node_modules"
rm_path "${ROOT}/agent_framework/frontend/.vite"
find "${ROOT}" -type d -name '__pycache__' -prune 2>/dev/null | while read -r d; do
  rm_path "$d"
done

# 根目录不应存在的旧文档（保留当前标准脚本）
KEEP_ROOT=(
  start.sh stop.sh setup-env.sh setup-dev.sh setup-production.sh
  verify.sh publish.sh sync.sh install.sh migrate-pack.sh restore-migrate.sh
  requirements-project.txt environment.yml README.md
)
if [[ "$DRY" != "1" && -d "${ROOT}" ]]; then
  for item in "${ROOT}"/*; do
    [[ -e "$item" ]] || continue
    base="$(basename "$item")"
    # 目录：只删明确废弃的
    case "$base" in
      agent_framework|mcp|deploy|config|data|refpanel|annotation|tests) continue ;;
    esac
    # 根目录文件：不在白名单且像旧脚本/备份则删
    if [[ -f "$item" ]]; then
      keep=0
      for k in "${KEEP_ROOT[@]}"; do [[ "$base" == "$k" ]] && keep=1 && break; done
      [[ "$keep" == "1" ]] && continue
      case "$base" in
        *.sh|*.py|*.md|*.tar|*.tar.gz|*.log|*.bak|*backup*) rm_path "$item" ;;
      esac
    fi
  done
fi

log "legacy 清理完成"
