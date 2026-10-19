# shellcheck shell=bash
# 统一运行时：Conda 环境 gaoai（可通过 config/chickensv.env 中 CHICKENSV_CONDA_ENV 覆盖）

_deploy_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEPLOY_DIR="$(cd "${_deploy_lib_dir}/.." && pwd)"
# shellcheck source=common.sh
source "${DEPLOY_DIR}/lib/common.sh"
# shellcheck source=ports.sh
source "${DEPLOY_DIR}/lib/ports.sh"

CONDA_BASE="${CONDA_BASE:-${HOME}/miniconda3}"
CONDA_ENV_NAME="${CHICKENSV_CONDA_ENV:-gaoai}"

_resolve_conda_python() {
  local base env py
  for base in "${CONDA_BASE}" "${HOME}/miniconda3" "${HOME}/anaconda3" "/opt/miniconda3"; do
    [[ -d "${base}" ]] || continue
    env="${CHICKENSV_ENV:-${base}/envs/${CONDA_ENV_NAME}}"
    py="${env}/bin/python"
    if [[ -x "${py}" ]]; then
      CONDA_BASE="${base}"
      PROJECT_ENV="${env}"
      PROJECT_PY="${py}"
      UVICORN="${env}/bin/uvicorn"
      return 0
    fi
  done
  return 1
}

PROJECT_ENV="${CHICKENSV_ENV:-${CONDA_BASE}/envs/${CONDA_ENV_NAME}}"
PROJECT_PY="${PROJECT_ENV}/bin/python"
UVICORN="${PROJECT_ENV}/bin/uvicorn"

CHICKENSV_ENV_FILE="${CHICKENSV_ROOT}/config/chickensv.env"

load_chickensv_env() {
  if [[ -f "${CHICKENSV_ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${CHICKENSV_ENV_FILE}"
    set +a
    CONDA_ENV_NAME="${CHICKENSV_CONDA_ENV:-${CONDA_ENV_NAME}}"
    PROJECT_ENV="${CHICKENSV_ENV:-${CONDA_BASE}/envs/${CONDA_ENV_NAME}}"
    PROJECT_PY="${PROJECT_ENV}/bin/python"
    UVICORN="${PROJECT_ENV}/bin/uvicorn"
  fi
}

runtime_activate() {
  load_chickensv_env
  if [[ ! -x "${PROJECT_PY}" ]]; then
    _resolve_conda_python || true
  fi
  if [[ ! -x "${PROJECT_PY}" ]]; then
    echo "缺少 Conda 环境 ${CONDA_ENV_NAME}: ${PROJECT_ENV}" >&2
    echo "在安置机执行: bash ${CHICKENSV_ROOT}/setup-env.sh" >&2
    echo "然后: bash ${CHICKENSV_ROOT}/setup-env.sh --check" >&2
    return 1
  fi
  export PATH="${PROJECT_ENV}/bin:${PATH}"
  export CHICKENSV_ENV="${PROJECT_ENV}"
  local jar="${CHICKENSV_ROOT}/refpanel/beagle.jar"
  [[ -f "${jar}" ]] && export BEAGLE_JAR_PATH="${BEAGLE_JAR_PATH:-${jar}}"
  [[ -f "${jar}" ]] && export BEAGLE_PATH="${BEAGLE_PATH:-${jar}}"
  return 0
}

require_project_env() { runtime_activate; }
require_backend_venv() { require_project_env; }
require_mcp_venv() { require_project_env; }
runtime_prepend_tools_path() { runtime_activate; }

wait_http() {
  local url="$1" label="$2" max="${3:-30}"
  local i
  for ((i = 1; i <= max; i++)); do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "OK ${label}"
      return 0
    fi
    sleep 1
  done
  echo "TIMEOUT ${label} (${max}s)" >&2
  return 1
}
