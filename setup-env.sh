#!/usr/bin/env bash
# 项目 Conda 环境 gaoai（不存在则自动创建）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${ROOT}/deploy"
# shellcheck source=deploy/lib/common.sh
source "${DEPLOY_DIR}/lib/common.sh"

CONDA_BASE="${CONDA_BASE:-${HOME}/miniconda3}"
CONDA_ENV="${CHICKENSV_CONDA_ENV:-gaoai}"
ENV_PREFIX="${CONDA_BASE}/envs/${CONDA_ENV}"
PIP="${ENV_PREFIX}/bin/pip"
PY="${ENV_PREFIX}/bin/python"
REQ="${CHICKENSV_ROOT}/requirements-project.txt"
ENV_FILE="${CHICKENSV_ROOT}/config/chickensv.env"
ENV_EXAMPLE="${CHICKENSV_ROOT}/config/chickensv.env.example"

log() { echo "[$(date '+%F %T')] $*"; }

_find_conda() {
  if [[ -x "${CONDA_BASE}/bin/conda" ]]; then
    echo "${CONDA_BASE}/bin/conda"
    return 0
  fi
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi
  for base in "${HOME}/miniconda3" "${HOME}/anaconda3" "/opt/miniconda3"; do
    if [[ -x "${base}/bin/conda" ]]; then
      CONDA_BASE="${base}"
      echo "${base}/bin/conda"
      return 0
    fi
  done
  return 1
}

_conda_accept_tos() {
  local conda_bin="$1"
  if ! "${conda_bin}" tos --help >/dev/null 2>&1; then
    return 0
  fi
  log "接受 Conda 默认 channel 服务条款（非交互）..."
  "${conda_bin}" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main 2>/dev/null || true
  "${conda_bin}" tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r 2>/dev/null || true
}

_ensure_conda_env() {
  [[ -x "${PY}" ]] && return 0
  local conda_bin
  conda_bin="$(_find_conda)" || {
    echo "错误: 未找到 conda。安置机请先安装 Miniconda:" >&2
    echo "  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh" >&2
    echo "  bash Miniconda3-latest-Linux-x86_64.sh -b -p \$HOME/miniconda3" >&2
    echo "  \$HOME/miniconda3/bin/conda init bash && source ~/.bashrc" >&2
    exit 1
  }
  # shellcheck disable=SC1090
  source "${CONDA_BASE}/etc/profile.d/conda.sh" 2>/dev/null || true

  _conda_accept_tos "${conda_bin}"

  log "创建 Conda 环境 ${CONDA_ENV} (python 3.11) ..."
  if ! "${conda_bin}" create -n "${CONDA_ENV}" python=3.11 -y \
      -c conda-forge --override-channels; then
    log "conda-forge 不可用，使用默认 channel 重试..."
    _conda_accept_tos "${conda_bin}"
    "${conda_bin}" create -n "${CONDA_ENV}" python=3.11 -y
  fi

  ENV_PREFIX="${CONDA_BASE}/envs/${CONDA_ENV}"
  PIP="${ENV_PREFIX}/bin/pip"
  PY="${ENV_PREFIX}/bin/python"
}

if [[ "${1:-}" == "--check" ]]; then
  [[ -x "${PY}" ]] || { echo "缺少 ${ENV_PREFIX}，请运行: bash setup-env.sh"; exit 1; }
  "${PY}" --version
  "${PY}" -c "import fastapi, flask" && echo "OK fastapi+flask"
  [[ -x "${ENV_PREFIX}/bin/uvicorn" ]] && echo "OK uvicorn" || echo "WARN: 缺少 uvicorn，请运行 bash setup-env.sh"
  command -v bcftools >/dev/null && bcftools --version | head -1 || echo "WARN: bcftools"
  exit 0
fi

_ensure_conda_env
[[ -x "${PY}" ]] || { echo "缺少 Conda 环境 ${CONDA_ENV}: ${ENV_PREFIX}" >&2; exit 1; }

[[ -f "${REQ}" ]] || { echo "错误: 缺少 ${REQ}，请先 rsync 项目代码" >&2; exit 1; }

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${ENV_EXAMPLE}" ]]; then
    mkdir -p "$(dirname "${ENV_FILE}")"
    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log "已创建 ${ENV_FILE}，请填写 API Key"
  else
    log "WARN: 无 ${ENV_EXAMPLE}，跳过创建 chickensv.env"
    log "      请确保 ${ENV_FILE} 存在，或从开发机 sync config 模板"
  fi
fi

log "pip 安装依赖 -> ${CONDA_ENV}"
"${PIP}" install -U pip
"${PIP}" install -r "${REQ}"

if ! command -v bcftools >/dev/null 2>&1; then
  if [[ -x "${CONDA_BASE}/envs/sv-analysis/bin/bcftools" ]]; then
    bash "${DEPLOY_DIR}/install-bcftools-to-gaoai.sh"
  else
    log "WARN: 无 bcftools；可从开发机 conda 离线安装"
  fi
fi

log "完成: ${ENV_PREFIX}  配置: ${ENV_FILE}"
