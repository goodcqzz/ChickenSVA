#!/usr/bin/env bash
# =============================================================================
# ChickenSV-Agent 一键安装（普适：任意 Linux 服务器 / 任意安装路径）
#
# 用法（在仓库根目录）：
#   bash install.sh
#   bash install.sh --production --systemd
#
# 选项：
#   --root DIR        安装根 CHICKENSV_ROOT（默认：自动检测仓库根）
#   --user USER       systemd 运行用户（默认：当前用户）
#   --production      生成生产 .env（HOST=127.0.0.1 等）
#   --systemd         安装 systemd 单元并 enable（需 sudo）
#   --skip-frontend   跳过 npm build
#   --skip-venv       跳过 Python venv（仅生成配置）
#   --dev             开发模式 .env（0.0.0.0 + DEBUG）
#   -h|--help
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

DO_PRODUCTION=false
DO_DEV=false
DO_SYSTEMD=false
SKIP_FRONTEND=false
SKIP_VENV=false

usage() {
  sed -n '2,20p' "$0"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) CHICKENSV_ROOT="$(cd "$2" && pwd)"; export CHICKENSV_ROOT; shift 2 ;;
    --user) RUN_USER="$2"; RUN_GROUP="${2}"; shift 2 ;;
    --production) DO_PRODUCTION=true; shift ;;
    --dev) DO_DEV=true; shift ;;
    --systemd) DO_SYSTEMD=true; shift ;;
    --skip-frontend) SKIP_FRONTEND=true; shift ;;
    --skip-venv) SKIP_VENV=true; shift ;;
    -h|--help) usage 0 ;;
    *) die "未知参数: $1（用 --help）" ;;
  esac
done

# 重新 source 以刷新路径
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

log "ChickenSV-Agent 安装"
log "CHICKENSV_ROOT=${CHICKENSV_ROOT}"
log "RUN_USER=${RUN_USER}"
require_dirs

# ---------- 系统依赖（Debian/Ubuntu）----------
if command -v apt-get >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1; then
    log "安装系统依赖 (apt)..."
    sudo apt-get update -y
    sudo apt-get install -y \
      python3 python3-venv python3-pip \
      curl rsync build-essential \
      openjdk-17-jre-headless
    if [[ "${SKIP_FRONTEND}" != "true" ]] && ! command -v node >/dev/null 2>&1; then
      log "安装 Node.js（先 apt，再尝试 NodeSource）..."
      if ! sudo apt-get install -y nodejs npm 2>/dev/null; then
        curl -fsSL --connect-timeout 15 --max-time 120 \
          https://deb.nodesource.com/setup_20.x | sudo -E bash - || true
        sudo apt-get install -y nodejs || true
      fi
    fi
  else
    log "未找到 sudo，跳过 apt（请自行安装 python3-venv、openjdk-17-jre、nodejs）"
  fi
else
  log "非 Debian/Ubuntu，请手动安装：Python3.10+、venv、Java 17 JRE、Node 20（前端构建）"
fi

# ---------- Python 环境（Conda gaoai，见 setup-env.sh）----------
if [[ "${SKIP_VENV}" != "true" ]]; then
  bash "${CHICKENSV_ROOT}/setup-env.sh"
fi

# ---------- 配置文件 ----------
ENV_FILE="${CHICKENSV_ROOT}/config/chickensv.env"
ENV_EXAMPLE="${CHICKENSV_ROOT}/config/chickensv.env.example"
if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  log "已创建 ${ENV_FILE}，请填写 API Key"
fi

# 兼容旧路径：backend/.env 若不存在则链到说明
LEGACY_ENV="${BE_DIR}/.env"
if [[ ! -f "${LEGACY_ENV}" ]] && [[ "${DO_PRODUCTION}" == "true" || "${DO_DEV}" == "true" ]]; then
  log "后端从 config/chickensv.env 读取配置（无需 backend/.env）"
fi
# 写入/覆盖一个 KEY=VALUE：存在则替换，缺失则追加
ensure_env_kv() {
  local key="$1" val="$2" file="$3"
  if grep -qE "^${key}=" "${file}"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "${file}" || true
  else
    printf '%s=%s\n' "${key}" "${val}" >> "${file}"
  fi
}

if [[ "${DO_PRODUCTION}" == "true" ]] && [[ -f "${ENV_FILE}" ]]; then
  ensure_env_kv APP_ENV production "${ENV_FILE}"
  ensure_env_kv DEBUG false "${ENV_FILE}"
  ensure_env_kv RELOAD false "${ENV_FILE}"
  ensure_env_kv HOST 127.0.0.1 "${ENV_FILE}"
  # 公网安全默认：不持久化用户 Key + 启用通用 IP 限速
  ensure_env_kv PERSIST_USER_API_KEYS false "${ENV_FILE}"
  ensure_env_kv RATE_LIMIT_ENABLED true "${ENV_FILE}"
fi
if [[ "${DO_DEV}" == "true" ]] && [[ -f "${ENV_FILE}" ]]; then
  sed -i 's/^APP_ENV=.*/APP_ENV=development/' "${ENV_FILE}" || true
  sed -i 's/^DEBUG=.*/DEBUG=true/' "${ENV_FILE}" || true
  sed -i 's/^RELOAD=.*/RELOAD=true/' "${ENV_FILE}" || true
  sed -i 's/^HOST=.*/HOST=0.0.0.0/' "${ENV_FILE}" || true
fi

# ---------- 前端 build ----------
if [[ "${SKIP_FRONTEND}" != "true" ]] && [[ -d "${FE_DIR}" ]] && command -v npm >/dev/null 2>&1; then
  log "前端构建..."
  (cd "${FE_DIR}" && npm ci && npm run build)
  log "dist: ${FE_DIR}/dist"
fi

# ---------- systemd ----------
if [[ "${DO_SYSTEMD}" == "true" ]]; then
  command -v sudo >/dev/null 2>&1 || die "--systemd 需要 sudo"
  log "安装 systemd 单元..."
  render_template "${SCRIPT_DIR}/systemd/chickensv-mcp.service.template" /tmp/chickensv-mcp.service
  render_template "${SCRIPT_DIR}/systemd/chickensv-backend.service.template" /tmp/chickensv-backend.service
  sudo cp /tmp/chickensv-mcp.service /tmp/chickensv-backend.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable chickensv-mcp chickensv-backend
  sudo systemctl restart chickensv-mcp || true
  sleep 2
  sudo systemctl restart chickensv-backend || true
  log "systemd: chickensv-mcp chickensv-backend"
fi

# ---------- 自检 ----------
if [[ -x "${CHICKENSV_ROOT}/verify.sh" ]]; then
  log "运行环境自检..."
  CHICKENSV_ROOT="${CHICKENSV_ROOT}" bash "${CHICKENSV_ROOT}/verify.sh" || true
fi

cat <<EOF

========================================
安装完成
========================================
根目录:     ${CHICKENSV_ROOT}
后端配置:   ${ENV_FILE}
手动启动:   bash ${CHICKENSV_ROOT}/start.sh          # 开发
            bash ${CHICKENSV_ROOT}/start.sh --prod   # 生产（Nginx/proxy）
生产部署:   bash ${CHICKENSV_ROOT}/setup-production.sh
健康检查:   curl -sS http://127.0.0.1:9801/api/v1/health
            curl -sS http://127.0.0.1:9802/health
            curl -sS http://127.0.0.1:9800/api/v1/health   # Nginx 反代

数据目录（需自行准备或下载）:
  ${DATA_DIR}/          SV CSV、表型
  ${REFPANEL_DIR}/      beagle.jar + 参考 VCF
  ${ANNOTATION_DIR}/    GFF3（可选）

文档: ${CHICKENSV_ROOT}/README.md
========================================
EOF
