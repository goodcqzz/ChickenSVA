# shellcheck shell=bash
# 安置机 SSH/rsync：支持密码登录，ControlMaster 只需输入一次密码
# 用法：
#   export REMOTE_HOST=your-server-ip
#   export REMOTE_USER=your-user
#   export REMOTE_BASE=/path/to/ProjectAi3
#   source deploy/lib/ssh-remote.sh

REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_USER="${REMOTE_USER:-}"
REMOTE_BASE="${REMOTE_BASE:-}"

if [[ -z "${REMOTE_HOST}" || -z "${REMOTE_USER}" || -z "${REMOTE_BASE}" ]]; then
  echo "错误: 请设置 REMOTE_HOST、REMOTE_USER、REMOTE_BASE 后再调用发布脚本" >&2
  exit 1
fi

mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh" 2>/dev/null || true
SSH_CTL="${HOME}/.ssh/cm-deploy-%r@%h:%p"

_ssh_opts() {
  echo -n "-o StrictHostKeyChecking=accept-new"
  echo -n " -o ControlMaster=auto"
  echo -n " -o ControlPath=${SSH_CTL}"
  echo -n " -o ControlPersist=10m"
  if [[ "${SSH_BATCH:-0}" == "1" ]]; then
    echo -n " -o BatchMode=yes"
  fi
}

# rsync 用（勿加 -n，否则无法读密码）
# shellcheck disable=SC2086
export RSYNC_RSH="${RSYNC_RSH:-ssh $(_ssh_opts)}"

ssh_remote() {
  # shellcheck disable=SC2086
  ssh $(_ssh_opts) "$@"
}

close_ssh_master() {
  # shellcheck disable=SC2086
  ssh $(_ssh_opts) -O exit "${REMOTE_USER}@${REMOTE_HOST}" 2>/dev/null || true
}
