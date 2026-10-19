#!/usr/bin/env bash
# 目标机解压 ProjectAi3 迁移包
# 用法: bash restore-migrate.sh /path/to/projectai3-migrate-*.tar.gz
set -euo pipefail

ARCHIVE="${1:?请指定迁移包路径}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${PROJECT_AI3_ROOT:-${SCRIPT_DIR}}"

[[ -f "${ARCHIVE}" ]] || { echo "找不到: ${ARCHIVE}" >&2; exit 1; }

echo "== 解压到 ${INSTALL_ROOT} =="
mkdir -p "${INSTALL_ROOT}"
case "${ARCHIVE}" in
  *.tar.gz|*.tgz) tar -xzf "${ARCHIVE}" -C "${INSTALL_ROOT}" ;;
  *.tar) tar -xf "${ARCHIVE}" -C "${INSTALL_ROOT}" ;;
  *) echo "不支持的格式: ${ARCHIVE}" >&2; exit 1 ;;
esac

export PROJECT_AI3_ROOT="${INSTALL_ROOT}"
cd "${INSTALL_ROOT}"
[[ -d agent_framework && -d mcp && -d deploy ]] || { echo "解压后目录不完整" >&2; exit 1; }

bash verify.sh || true

if [[ "${SKIP_BOOTSTRAP:-0}" != "1" ]]; then
  export SKIP_FRONTEND="${SKIP_FRONTEND:-1}"
  bash setup-production.sh
fi

echo "编辑 ${INSTALL_ROOT}/config/chickensv.env 后: bash verify.sh && sudo systemctl restart chickensv-mcp chickensv-backend"
