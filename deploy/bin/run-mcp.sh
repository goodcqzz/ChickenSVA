#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/runtime.sh
source "${SCRIPT_DIR}/../lib/runtime.sh"
require_mcp_venv
runtime_activate
cd "${MCP_DIR}"
exec "${PROJECT_PY}" mcp_http_server.py "${1:-${MCP_PORT:-9802}}"
