#!/usr/bin/env bash
# 发布到安置机（支持 SSH 密码登录，ControlMaster 只需输一次密码）
#
# 用法:
#   bash publish.sh                 # 增量同步 + 重启
#   bash publish.sh --fresh           # 删除安置机多余旧文件（保留 backend/data）
#   bash publish.sh --skip-build      # 不重建前端
#   bash publish.sh --with-env         # 同步 chickensv.env（安置机无文件时；有则跳过）
#   bash publish.sh --with-env --force-env  # 覆盖安置机 env（会先备份）
#
# 安置机大清理（可选，SSH 登录 107 后）:
#   bash deploy/remote-stash-and-clean.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/ssh-remote.sh
source "${ROOT}/deploy/lib/ssh-remote.sh"

DO_BUILD=1
SYNC_DIST=1
SYNC_ENV=0
FRESH=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) DO_BUILD=0 ;;
    --code-only) DO_BUILD=0; SYNC_DIST=0 ;;
    --fresh) FRESH=1 ;;
    --with-env) SYNC_ENV=1 ;;
  esac
done

echo "目标: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_BASE}"
[[ "$FRESH" == "1" ]] && echo "模式: --fresh（删除安置机多余旧代码，保留 backend/data）"
echo "提示: 首次连接会要求输入 SSH 密码，同一轮发布只需输入一次。"

if [[ "$DO_BUILD" == "1" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "WARN: 未找到 npm，跳过前端构建（使用已有 dist/）"
    [[ -f "${ROOT}/agent_framework/frontend/dist/index.html" ]] || {
      echo "错误: 无 dist，请安装 npm 后构建或去掉 --skip-build 前先手动 npm run build" >&2
      exit 1
    }
  else
    (cd "${ROOT}/agent_framework/frontend" && npm run build)
  fi
fi

SYNC_ARGS=(code)
[[ "$FRESH" == "1" ]] && SYNC_ARGS+=(--fresh)
export SYNC_KEEP_SSH=1
bash "${ROOT}/sync.sh" "${SYNC_ARGS[@]}"
[[ "$SYNC_DIST" == "1" ]] && bash "${ROOT}/sync.sh" dist
if [[ "$SYNC_ENV" == "1" ]]; then
  ENV_ARGS=(env)
  for arg in "$@"; do
    [[ "$arg" == "--force-env" ]] && ENV_ARGS+=(--force)
  done
  bash "${ROOT}/sync.sh" "${ENV_ARGS[@]}"
fi
unset SYNC_KEEP_SSH

ssh_remote "${REMOTE_USER}@${REMOTE_HOST}" "bash ${REMOTE_BASE}/deploy/remote-post-deploy.sh"
close_ssh_master
echo "发布完成"
