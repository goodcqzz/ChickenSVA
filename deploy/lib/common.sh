# shellcheck shell=bash
# deploy/lib/common.sh — 项目根下的 deploy/

_deploy_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEPLOY_DIR="$(cd "${_deploy_lib_dir}/.." && pwd)"

detect_install_root() {
  if [[ -n "${CHICKENSV_ROOT:-}" ]]; then
    echo "$(cd "${CHICKENSV_ROOT}" && pwd)"
    return 0
  fi
  if [[ -n "${PROJECT_AI3_ROOT:-}" ]]; then
    echo "$(cd "${PROJECT_AI3_ROOT}" && pwd)"
    return 0
  fi
  local candidate
  candidate="$(cd "${DEPLOY_DIR}/.." && pwd)"
  if [[ -d "${candidate}/mcp" && -d "${candidate}/agent_framework" ]]; then
    echo "${candidate}"
    return 0
  fi
  echo "${candidate}"
}

CHICKENSV_ROOT="${CHICKENSV_ROOT:-$(detect_install_root)}"
export CHICKENSV_ROOT PROJECT_AI3_ROOT="${CHICKENSV_ROOT}"

AF_ROOT="${CHICKENSV_ROOT}/agent_framework"
BE_DIR="${AF_ROOT}/backend"
FE_DIR="${AF_ROOT}/frontend"
MCP_DIR="${CHICKENSV_ROOT}/mcp"
DATA_DIR="${CHICKENSV_ROOT}/data"
REFPANEL_DIR="${CHICKENSV_ROOT}/refpanel"
ANNOTATION_DIR="${CHICKENSV_ROOT}/annotation"

RUN_USER="${RUN_USER:-$(id -un)}"
RUN_GROUP="${RUN_GROUP:-$(id -gn)}"

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "错误: $*" >&2; exit 1; }

require_dirs() {
  [[ -d "${AF_ROOT}" ]] || die "缺少 ${AF_ROOT}"
  [[ -d "${BE_DIR}" ]] || die "缺少 ${BE_DIR}"
  [[ -d "${MCP_DIR}" ]] || die "缺少 ${MCP_DIR}"
}

render_template() {
  local src="$1" dst="$2"
  sed \
    -e "s|@@CHICKENSV_ROOT@@|${CHICKENSV_ROOT}|g" \
    -e "s|@@AF_ROOT@@|${AF_ROOT}|g" \
    -e "s|@@BE_DIR@@|${BE_DIR}|g" \
    -e "s|@@MCP_DIR@@|${MCP_DIR}|g" \
    -e "s|@@DEPLOY_DIR@@|${DEPLOY_DIR}|g" \
    -e "s|@@RUN_USER@@|${RUN_USER}|g" \
    -e "s|@@RUN_GROUP@@|${RUN_GROUP}|g" \
    -e "s|@@CHICKENSV_PUBLIC_PORT@@|${CHICKENSV_PUBLIC_PORT:-9800}|g" \
    "$src" >"$dst"
}
