#!/usr/bin/env bash
# Run after git pull in the existing /opt/zaloflow deployment.
set -euo pipefail
umask 077

if [[ "$EUID" -ne 0 ]]; then
  echo 'Chạy lệnh này trong terminal root của VPS.' >&2
  exit 1
fi
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "$PWD" != /opt/zaloflow || ! -x .venv/bin/python ]]; then
  echo 'Chỉ chạy cho bản đã triển khai tại /opt/zaloflow có .venv.' >&2
  exit 1
fi
systemctl cat zaloflow >/dev/null
command -v nginx >/dev/null
site=/etc/nginx/sites-available/cskh.viettaxco.com
if [[ ! -f "$site" ]]; then
  echo "Không tìm thấy $site. Cần xác định đúng cấu hình Nginx của ZaloFlow trước khi cập nhật." >&2
  exit 1
fi

install -d -m 700 /var/backups/zaloflow
backup_dir=$(mktemp -d /var/backups/zaloflow/update-XXXXXXXX)
cp -a "$site" "$backup_dir/nginx.conf"
git rev-parse HEAD > "$backup_dir/source-commit.txt"
echo "Thư mục sao lưu riêng: $backup_dir"
echo 'Cài phụ thuộc Python...'
# Libraries must be readable by the service user; backups retain umask 077.
(umask 022; .venv/bin/python -m pip install -r requirements-prod.txt)
if ! runuser -u zaloflow -- .venv/bin/python -c 'from PIL import Image' >/dev/null 2>&1; then
  echo 'Sửa quyền thư viện Pillow bằng cách cài lại cho người dùng dịch vụ đọc được...'
  (umask 022; .venv/bin/python -m pip install --force-reinstall --no-deps Pillow==11.3.0)
fi
# Import with the actual service identity before stopping it or migrating its data.
runuser -u zaloflow -- .venv/bin/python -c 'from PIL import Image; import campaign_actions'

# Preserve HTTPS/certbot settings and change only this site's upload allowance.
.venv/bin/python - "$site" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
names = re.findall(r'\bserver_name\s+([^;]+);', text)
if not names or any(name.strip() != 'cskh.viettaxco.com' for name in names):
    raise SystemExit('Cấu hình chứa tên miền khác. Không tự sửa để tránh ảnh hưởng website khác.')
if re.search(r'\bclient_max_body_size\s+[^;]+;', text):
    text = re.sub(r'\bclient_max_body_size\s+[^;]+;', 'client_max_body_size 12m;', text)
else:
    text = re.sub(r'(\bserver_name\s+cskh\.viettaxco\.com\s*;)', r'\1\n    client_max_body_size 12m;', text)
path.write_text(text)
PY
if ! nginx -t; then
  cp -a "$backup_dir/nginx.conf" "$site"
  echo 'Nginx không hợp lệ; đã khôi phục cấu hình, chưa dừng ZaloFlow.' >&2
  exit 1
fi

stopped=0
on_failure() {
  if [[ "$stopped" == 1 ]]; then
    systemctl start zaloflow || true
  fi
  echo "Cập nhật chưa hoàn tất. Giữ nguyên bản sao lưu tại $backup_dir; kiểm tra systemctl status zaloflow." >&2
}
trap on_failure ERR
echo 'Tạm dừng riêng ZaloFlow để sao lưu dữ liệu nhất quán...'
systemctl stop zaloflow
stopped=1
if [[ -d instance ]]; then
  cp -a instance "$backup_dir/instance"
fi
systemctl start zaloflow
stopped=0
systemctl reload nginx

# Poll with short intervals; this checks the application after schema migration.
for attempt in {1..15}; do
  if curl --silent --fail --connect-timeout 1 --max-time 3 --output /dev/null http://127.0.0.1:8000/login; then
    trap - ERR
    echo 'Đã cập nhật ZaloFlow: /login trả HTTP 200. Kiểm tra đăng nhập và menu Hành động trên web.'
    exit 0
  fi
  sleep 1
done
echo "Ứng dụng chưa sẵn sàng. Xem journalctl -u zaloflow -n 50 --no-pager. Bản sao lưu: $backup_dir" >&2
exit 1
