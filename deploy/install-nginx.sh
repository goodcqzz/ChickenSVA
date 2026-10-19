#!/usr/bin/env bash
# 安置机安装 Nginx 反代 ChickenSV（默认 :9800，与 Dify :80 不冲突）
#
# 用法:
#   cd /path/to/ProjectAi3
#   bash deploy/install-nginx.sh
#   bash deploy/install-nginx.sh --domain example.com   # 有独立域名时 listen 80
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${CHICKENSV_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
DEPLOY="${ROOT}/deploy"
export CHICKENSV_ROOT="${ROOT}"
# shellcheck source=lib/common.sh
source "${DEPLOY}/lib/common.sh"
# shellcheck source=lib/ports.sh
source "${DEPLOY}/lib/ports.sh"

CONF_SRC="${ROOT}/deploy/nginx/chickensv.conf"
CONF_DST="/etc/nginx/sites-available/chickensv"
DOMAIN=""
LISTEN_PORT="${CHICKENSV_NGINX_PORT:-${CHICKENSV_PUBLIC_PORT}}"
PORT_EXPLICIT=0
SERVER_IP="$(hostname -I | awk '{print $1}')"

for arg in "$@"; do
  case "$arg" in
    --domain=*) DOMAIN="${arg#*=}" ;;
    --domain) shift; DOMAIN="${1:-}" ;;
    --port=*) LISTEN_PORT="${arg#*=}"; PORT_EXPLICIT=1 ;;
  esac
done

# 指定域名但未显式给端口时，默认监听 80（保持旧行为）
if [[ -n "${DOMAIN}" && "${PORT_EXPLICIT}" == "0" && -z "${CHICKENSV_NGINX_PORT:-}" ]]; then
  LISTEN_PORT=80
fi
# 监听端口通过模板注入（render_template 读取 CHICKENSV_PUBLIC_PORT）
export CHICKENSV_PUBLIC_PORT="${LISTEN_PORT}"

[[ -f "${CONF_SRC}" ]] || die "缺少 ${CONF_SRC}（请在项目根目录运行）"
[[ -f "${FE_DIR}/dist/index.html" ]] || die "缺少前端 dist，请先: cd agent_framework/frontend && npm run build"

command -v sudo >/dev/null 2>&1 || die "需要 sudo 安装系统 Nginx"

if ! command -v nginx >/dev/null 2>&1; then
  log "安装 nginx..."
  sudo apt-get update -qq
  sudo apt-get install -y nginx
fi

# serve-proxy 与 Nginx 不能同时占 9800
pkill -f 'deploy/bin/serve-proxy.py' 2>/dev/null || true
sleep 1

if ss -tln | grep -q ":${LISTEN_PORT} " && ! systemctl is-active nginx >/dev/null 2>&1; then
  die "端口 ${LISTEN_PORT} 被占用且 Nginx 未运行。先: pkill -f serve-proxy.py 或 bash stop.sh"
fi

TMP="$(mktemp)"
render_template "${CONF_SRC}" "${TMP}"
if [[ -n "${DOMAIN}" ]]; then
  sed -i "s/server_name _;/server_name ${DOMAIN};/" "${TMP}"
fi

sudo cp "${TMP}" "${CONF_DST}"
rm -f "${TMP}"
sudo chmod 644 "${CONF_DST}"
sudo ln -sf "${CONF_DST}" /etc/nginx/sites-enabled/chickensv

if [[ -f /etc/nginx/sites-enabled/default ]]; then
  log "禁用 default 站点（避免与 Dify :80 冲突）..."
  sudo rm -f /etc/nginx/sites-enabled/default
fi

sudo nginx -t

if systemctl is-active nginx >/dev/null 2>&1; then
  sudo systemctl reload nginx
else
  sudo systemctl enable nginx
  sudo systemctl start nginx
fi

chmod o+x "${HOME}" "${ROOT}" "${AF_ROOT}" "${FE_DIR}" 2>/dev/null || true
chmod -R o+rX "${FE_DIR}/dist"

cat <<EOF

Nginx 反代已就绪（ChickenSV 对外用 ${LISTEN_PORT}；Dify 仅本机 127.0.0.1:8080/8443，不对外）。
  访问: http://${SERVER_IP}:${LISTEN_PORT}/
  健康: curl -s http://127.0.0.1:${LISTEN_PORT}/api/v1/health
  状态: sudo systemctl status nginx
  防火墙: sudo ufw allow ${LISTEN_PORT}/tcp
EOF
