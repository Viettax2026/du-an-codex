#!/usr/bin/env bash
# Fresh installs only. Existing installations are never overwritten.
set -euo pipefail
umask 022
source_root=$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
domain=''; email=''; name=zaloflow-web; port=8040; http_only=0; start_scheduler=0
usage() {
  cat <<'HELP'
Ubuntu 24.04 LTS, fresh web installation:
  sudo bash web_deploy/install-web.sh --domain crm.example.com --email owner@example.com
Options: --name zaloflow-web --port 8040 --start-scheduler
Testing only: --http-only (HTTP without secure login cookies)
The web package and Windows app use independent accounts and databases.
HELP
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain|--email|--name|--port)
      [[ $# -ge 2 && -n "$2" ]] || { echo "Thiếu giá trị: $1" >&2; exit 2; }
      case "$1" in --domain) domain=$2;; --email) email=$2;; --name) name=$2;; --port) port=$2;; esac
      shift 2 ;;
    --http-only) http_only=1; shift ;;
    --start-scheduler) start_scheduler=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Tùy chọn không hợp lệ: $1" >&2; usage; exit 2 ;;
  esac
done
[[ "$EUID" == 0 ]] || { echo 'Chạy bằng root hoặc sudo trên VPS mới.' >&2; exit 1; }
[[ -n "$domain" ]] || { usage; exit 2; }
if [[ "$http_only" == 0 && ! "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  echo 'Cần --email để cấp HTTPS. Trỏ DNS domain tới VPS trước.' >&2; exit 2
fi
[[ -f /etc/os-release ]] || { echo 'Cần Ubuntu 24.04 LTS.' >&2; exit 1; }
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Gói này được kiểm tra cho Ubuntu 24.04 LTS.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Cài python3 trước: apt-get update && apt-get install -y python3' >&2; exit 1; }
python3 "$source_root/web_deploy/configure.py" --domain "$domain" --name "$name" --port "$port" >/dev/null
domain=${domain,,}
port=$(python3 -c 'import sys; print(int(sys.argv[1]))' "$port")
app_root=/opt/$name
site=/etc/nginx/sites-available/$name
enabled=/etc/nginx/sites-enabled/$name
limits=/etc/nginx/conf.d/$name-limits.conf
for target in "$app_root" "$site" "$enabled" "$limits" "/etc/systemd/system/$name.service" "/etc/systemd/system/$name-scheduler.service"; do
  [[ ! -e "$target" && ! -L "$target" ]] || { echo "Đã tồn tại $target. Không ghi đè; dùng --name khác hoặc quy trình cập nhật." >&2; exit 1; }
done
if id "$name" >/dev/null 2>&1; then echo "Tài khoản hệ thống $name đã tồn tại. Dùng --name khác." >&2; exit 1; fi
if [[ -d /etc/nginx ]]; then
  python3 - "$domain" <<'PY'
import re,sys
from pathlib import Path
for folder in ('/etc/nginx/sites-enabled','/etc/nginx/conf.d'):
    for path in Path(folder).glob('*'):
        if path.is_file():
            text=re.sub(r'#.*','',path.read_text(errors='replace'))
            for match in re.finditer(r'\bserver_name\s+([^;]+);',text):
                if sys.argv[1] in match[1].split():
                    raise SystemExit('Domain đã có trong Nginx: '+str(path)+'. Không sửa website đang chạy.')
PY
fi
python3 - "$port" <<'PY'
import socket,sys
with socket.socket() as sock:
    sock.bind(('127.0.0.1',int(sys.argv[1])))
PY
[[ -f "$source_root/app.py" && -f "$source_root/WEB-RELEASE.json" ]] || { echo 'Giải nén đầy đủ gói zaloflow-web.zip trước khi cài.' >&2; exit 1; }
python3 "$source_root/web_deploy/package.py" verify "$source_root"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nginx certbot curl ca-certificates xz-utils
useradd --system --user-group --home-dir "$app_root" --shell /usr/sbin/nologin "$name"
install -d -m 755 "$app_root"
# The package builder includes code only. Never copy a developer instance/venv.
python3 "$source_root/web_deploy/package.py" install-code "$source_root" "$app_root"
chown -R root:root "$app_root"
find "$app_root" -type d -exec chmod 755 {} +
find "$app_root" -type f -exec chmod 644 {} +
install -d -m 700 -o "$name" -g "$name" "$app_root/instance"
bash "$app_root/web_deploy/node-runtime.sh" "$app_root/runtime/node"
export PATH="$app_root/runtime/node/bin:$PATH"
python3 -m venv "$app_root/.venv"
"$app_root/.venv/bin/python" -m pip install -q -r "$app_root/requirements-prod.txt"
(cd "$app_root/connector"; npm ci --omit=dev --no-audit --no-fund)
install -d -m 755 "/var/lib/$name/letsencrypt"
rendered=$(mktemp -d)
trap 'rm -rf "$rendered"' EXIT
python3 "$app_root/web_deploy/configure.py" --domain "$domain" --name "$name" --port "$port" --http-only --output "$rendered"
install -m 644 "$rendered/$name-limits.conf" "$limits"
install -m 644 "$rendered/$name.nginx.conf" "$site"
ln -s "$site" "$enabled"
rollback_nginx() {
  rm -f "$enabled" "$site" "$limits"
  nginx -t && systemctl reload nginx || true
  echo "Cài đặt chưa hoàn tất; mã/dữ liệu giữ tại $app_root. Không chạy lại để ghi đè. Xem hướng dẫn khôi phục." >&2
}
trap rollback_nginx ERR
nginx -t
systemctl enable --now nginx
systemctl reload nginx
if [[ "$http_only" == 0 ]]; then
  certbot certonly --webroot --webroot-path "/var/lib/$name/letsencrypt" --cert-name "$domain" -d "$domain" --email "$email" --agree-tos --non-interactive --keep-until-expiring
  python3 "$app_root/web_deploy/configure.py" --domain "$domain" --name "$name" --port "$port" --output "$rendered"
  install -m 644 "$rendered/$name.nginx.conf" "$site"
  install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
  printf '#!/bin/sh\nnginx -t && systemctl reload nginx\n' > "/etc/letsencrypt/renewal-hooks/deploy/$name-reload-nginx"
  chmod 755 "/etc/letsencrypt/renewal-hooks/deploy/$name-reload-nginx"
  systemctl enable --now certbot.timer
fi
nginx -t
install -m 644 "$rendered/$name.service" "/etc/systemd/system/$name.service"
install -m 644 "$rendered/$name-scheduler.service" "/etc/systemd/system/$name-scheduler.service"
install -m 644 "$rendered/installation.json" "$app_root/web-installation.json"
systemctl daemon-reload
systemctl enable --now "$name.service"
ready=0
for attempt in {1..20}; do
  if curl --silent --fail --connect-timeout 1 --max-time 2 --output /dev/null "http://127.0.0.1:$port/login"; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]]
systemctl reload nginx
if [[ "$start_scheduler" == 1 ]]; then systemctl enable --now "$name-scheduler.service"; fi
trap 'rm -rf "$rendered"' EXIT
trap - ERR
scheme=https; [[ "$http_only" == 0 ]] || scheme=http
echo "Đã cài bản web riêng: $scheme://$domain/register"
echo "Dữ liệu: $app_root/instance"
if [[ "$start_scheduler" == 0 ]]; then echo "Bộ lịch chưa bật. Khi sẵn sàng: systemctl enable --now $name-scheduler.service"; fi
