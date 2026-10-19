#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/runtime.sh
source "${SCRIPT_DIR}/../lib/runtime.sh"
require_backend_venv
runtime_activate
cd "${BE_DIR}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-${CHICKENSV_BACKEND_PORT:-9801}}"
RELOAD="${RELOAD:-}"
# 多 worker：默认 1。
# 安全提示：当前按 IP 的限速/配额与 WebSocket 聊天滑动窗口是「进程内」状态，
# 多 worker 会让这些计数按 worker 拆分，等效把限额放大 worker 倍；在前端无认证时
# 会削弱防滥用能力。仅在已把限速/配额改为共享存储（如 Redis）后再设置 WORKERS>1。
WORKERS="${WORKERS:-1}"
EXTRA=()
if [[ "${RELOAD}" == "1" || "${RELOAD}" == "true" ]]; then
  # --reload 与 --workers 互斥，开发热重载优先
  EXTRA+=(--reload)
elif [[ "${WORKERS}" =~ ^[0-9]+$ && "${WORKERS}" -gt 1 ]]; then
  EXTRA+=(--workers "${WORKERS}")
fi
exec "${UVICORN}" app.main:app --host "${HOST}" --port "${PORT}" "${EXTRA[@]}"
