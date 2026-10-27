#!/usr/bin/env bash
# Stop only this installation, snapshot the entire instance, restore prior state.
set -euo pipefail
umask 077
name=${1:-zaloflow-web}
output=${2:-/var/backups/zaloflow-web}
[[ "$EUID" == 0 ]] || { echo 'Chạy bằng root hoặc sudo.' >&2; exit 1; }
[[ "$name" =~ ^[a-z][a-z0-9-]{2,30}$ ]] || { echo 'Tên bản cài không hợp lệ.' >&2; exit 1; }
app_root=/opt/$name
[[ -d "$app_root/instance" ]] || { echo 'Không tìm thấy thư mục instance.' >&2; exit 1; }
install -d -m 700 "$output"
snapshot=$(mktemp -d "$output/backup-XXXXXXXX")
web_active=0; scheduler_active=0
if systemctl is-active --quiet "$name.service"; then web_active=1; fi
if systemctl is-active --quiet "$name-scheduler.service"; then scheduler_active=1; fi
restart_prior() {
  if [[ "$web_active" == 1 ]]; then systemctl start "$name.service"; fi
  if [[ "$scheduler_active" == 1 ]]; then systemctl start "$name-scheduler.service"; fi
}
trap restart_prior EXIT
if [[ "$scheduler_active" == 1 ]]; then systemctl stop "$name-scheduler.service"; fi
if [[ "$web_active" == 1 ]]; then systemctl stop "$name.service"; fi
cp -a "$app_root/instance" "$snapshot/instance"
for file in WEB-RELEASE.json web-installation.json; do
  if [[ -f "$app_root/$file" ]]; then cp -a "$app_root/$file" "$snapshot/$file"; fi
done
tar -czf "$snapshot/instance-backup.tar.gz" -C "$snapshot" instance
rm -rf "$snapshot/instance"
echo "Đã sao lưu đầy đủ dữ liệu/ảnh/khóa/phiên Zalo: $snapshot/instance-backup.tar.gz"
