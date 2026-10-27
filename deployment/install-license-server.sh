#!/usr/bin/env bash
# Separate license service; never starts/stops customer campaign schedules.
set -euo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo 'Chạy trong terminal root của VPS.' >&2; exit 1; }
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
[[ "$PWD" == /opt/zaloflow && -x .venv/bin/python ]] || { echo 'Cần bản /opt/zaloflow có .venv.' >&2; exit 1; }
site=/etc/nginx/sites-available/cskh.viettaxco.com
[[ -f "$site" ]] || { echo 'Không tìm thấy cấu hình Nginx của cskh.viettaxco.com.' >&2; exit 1; }
nginx -t
# Validate the edit before creating a service or modifying the live site.
.venv/bin/python - "$site" <<'PY'
import sys
from pathlib import Path
from deployment.license_nginx import configure
configure(Path(sys.argv[1]).read_text())
PY
snippet=/etc/nginx/snippets/zaloflow-license-location.conf
if [[ -f "$snippet" && $(head -n 1 "$snippet") != '# Managed by ZaloFlow license installer.'* ]]; then
  echo "Không ghi đè cấu hình không thuộc ZaloFlow: $snippet" >&2; exit 1
fi
install -d -m 700 /var/backups/zaloflow
backup_dir=$(mktemp -d /var/backups/zaloflow/license-XXXXXXXX)
cp -a "$site" "$backup_dir/nginx.conf"
if [[ -f "$snippet" ]]; then cp -a "$snippet" "$backup_dir/location.conf"; fi
(umask 022; .venv/bin/python -m pip install -r requirements-prod.txt)
if ! id zaloflow-license >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/zaloflow-licenses --shell /usr/sbin/nologin zaloflow-license
fi
install -d -m 700 -o zaloflow-license -g zaloflow-license /var/lib/zaloflow-licenses
if systemctl is-active --quiet zaloflow-license; then systemctl stop zaloflow-license; fi
rollback() {
  cp -a "$backup_dir/nginx.conf" "$site"
  if [[ -f "$backup_dir/location.conf" ]]; then cp -a "$backup_dir/location.conf" "$snippet"; else rm -f "$snippet"; fi
  systemctl stop zaloflow-license || true
  echo "Cài đặt chưa hoàn tất. Bản sao lưu: $backup_dir. Xem journalctl -u zaloflow-license -n 50 --no-pager." >&2
}
trap rollback ERR
if [[ -f /var/lib/zaloflow-licenses/signing-private.pem ]]; then
  cp -a /var/lib/zaloflow-licenses "$backup_dir/authority"
else
  runuser -u zaloflow-license -- .venv/bin/python -m license_system.admin init --url https://cskh.viettaxco.com/licenses
fi
install -m 644 deployment/zaloflow-license.service /etc/systemd/system/zaloflow-license.service
install -d -m 755 /etc/nginx/snippets
install -m 644 deployment/zaloflow-license-location.conf "$snippet"
.venv/bin/python deployment/license_nginx.py "$site"
nginx -t
systemctl daemon-reload
systemctl enable --now zaloflow-license
ready=0
for attempt in {1..15}; do
  if curl --silent --fail --connect-timeout 1 --max-time 2 --output /dev/null http://127.0.0.1:8010/admin/login; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]]
systemctl reload nginx
trap - ERR
echo 'Đã cài trang quản trị: https://cskh.viettaxco.com/licenses/admin'
echo 'Xem mật khẩu quản trị lần đầu bằng: cat /var/lib/zaloflow-licenses/admin-password.txt'
echo 'Tệp cấu hình công khai để dựng bản Windows: /var/lib/zaloflow-licenses/client-config.json'
echo 'Không chia sẻ signing-private.pem, admin-password.txt hoặc bản sao lưu authority.'
