#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${ROOT}/setup-env.sh"
FE="${ROOT}/agent_framework/frontend"
if [[ -f "${FE}/package.json" ]] && command -v npm >/dev/null 2>&1; then
  (cd "${FE}" && npm ci)
fi
echo "开发就绪: vim ${ROOT}/config/chickensv.env && bash ${ROOT}/start.sh"
echo "端口: 9800 对外 | 9801 后端 | 9802 MCP"
