# Triển khai bản dùng thử trên VPS Ubuntu 24.04

Tên miền: cskh.viettaxco.com. IP: 103.77.172.174.
Đây là bản dùng thử: có quản lý hồ sơ, khách hàng và mô phỏng chiến dịch; có bộ kết nối QR không chính thức cần xác minh trên VPS; chưa gửi tự động. Không dùng dữ liệu khách hàng thực trước khi hoàn thiện vận hành, sao lưu và khôi phục tài khoản.

## 1. Tải và chuyển mã từ máy Windows

Lưu zaloflow-deploy.zip vào thư mục Downloads trên máy Windows. Mở PowerShell mới (dấu nhắc PS C:\...) và chạy:

```powershell
scp "$env:USERPROFILE\Downloads\zaloflow-deploy.zip" root@103.77.172.174:/root/
```

Nhập mật khẩu VPS ở dòng password: (không hiện ký tự). Kiểm tra dấu vân tay SSH nếu kết nối lần đầu.

## 2. Chuẩn bị VPS

Trong phiên SSH trên VPS (dấu nhắc root@quanly:~#):

```sh
apt install -y python3-venv unzip certbot python3-certbot-nginx
ls -lh /root/zaloflow-deploy.zip
```

Các bước dưới là cài lần đầu. Nếu /opt/zaloflow hoặc các tệp cấu hình cùng tên đã tồn tại, dừng để kiểm tra và sao lưu; không ghi đè mù quáng.

```sh
test ! -e /opt/zaloflow && mkdir /opt/zaloflow
unzip /root/zaloflow-deploy.zip -d /opt/zaloflow
cd /opt/zaloflow
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-prod.txt
```

## 3. Chạy ứng dụng với tài khoản riêng

```sh
useradd --system --user-group --home-dir /opt/zaloflow --shell /usr/sbin/nologin zaloflow
install -d -m 700 -o zaloflow -g zaloflow /opt/zaloflow/instance
install -m 644 deployment/zaloflow.service /etc/systemd/system/zaloflow.service
systemctl daemon-reload
systemctl enable --now zaloflow
systemctl status zaloflow --no-pager
curl -I http://127.0.0.1:8000/login
```

Kết quả mong đợi: service active (running), HTTP 200. Nếu lỗi:

```sh
journalctl -u zaloflow -n 50 --no-pager
```

Mã do root sở hữu; chỉ thư mục instance cho người dùng ứng dụng ghi dữ liệu. Không chạy Gunicorn dưới root và không mở cổng 8000 ra Internet.

## 4. Gắn Nginx

Kiểm tra không có server_name cskh.viettaxco.com trong một cấu hình khác. Đảm bảo các đích dưới chưa tồn tại trước khi cài lần đầu:

```sh
ls /etc/nginx/sites-available
ls /etc/nginx/conf.d
```

```sh
install -m 644 deployment/zaloflow-limits.conf /etc/nginx/conf.d/zaloflow-limits.conf
install -m 644 deployment/cskh.viettaxco.com.conf /etc/nginx/sites-available/cskh.viettaxco.com
ln -s /etc/nginx/sites-available/cskh.viettaxco.com /etc/nginx/sites-enabled/cskh.viettaxco.com
nginx -t
```

Chỉ khi nginx -t thành công:

```sh
systemctl reload nginx
```

Giữ nguyên cấu hình của các website khác. Cấu hình này hạn chế tốc độ truy cập trang đăng nhập/đăng ký cho bản dùng thử. COOKIE_SECURE bật sẵn nên phải hoàn thành HTTPS trước khi đăng ký hoặc đăng nhập.

## 5. HTTPS

Cổng TCP 80/443 cần được mở tại firewall nhà cung cấp và firewall VPS. Nếu UFW đang active, cho phép OpenSSH trước khi thay đổi luật để không mất SSH; không bật/reset firewall mù quáng.

```sh
ufw status
```

Nếu UFW active:

```sh
ufw allow OpenSSH
ufw allow 'Nginx Full'
```

```sh
certbot --nginx -d cskh.viettaxco.com
```

Nhập email và đồng ý điều khoản. Chọn chuyển HTTP sang HTTPS nếu được hỏi. Sau khi cấp chứng chỉ:

```sh
nginx -t
certbot renew --dry-run
```

Truy cập https://cskh.viettaxco.com/register để tạo tài khoản của bạn. Không có tài khoản hay mật khẩu mẫu. Kiểm tra đăng nhập, thêm khách hàng thử, tạo chiến dịch, mô phỏng và nhật ký. Dữ liệu/khóa được tạo mới trong /opt/zaloflow/instance; ZIP không chứa dữ liệu hoặc khóa từ môi trường phát triển.

## 6. Sau triển khai

Dữ liệu SQLite ở /opt/zaloflow/instance/zalo.sqlite3; khóa phiên ở /opt/zaloflow/instance/session.key. Sao lưu bằng SQLite backup hoặc dừng dịch vụ trước khi sao chép thư mục instance; bảo vệ bản sao lưu và kiểm tra khôi phục. Không đưa instance lên GitHub. Trước khi dùng thật cần quy định đăng ký, khôi phục tài khoản, giám sát, cập nhật hệ điều hành và kiểm thử bảo mật phù hợp. Tích hợp Zalo thật là hạng mục chưa triển khai.

## Cập nhật bộ kết nối QR trên bản VPS đã triển khai

Sao lưu instance và bảo vệ bản sao trước khi cập nhật. Nếu đã sửa mã trên VPS, xem git status trước và không reset/ghi đè các thay đổi. Với checkout sạch:

```sh
cd /opt/zaloflow
git pull --ff-only origin main
apt install -y nodejs npm
node --version
npm ci --prefix connector --ignore-scripts --no-audit --no-fund
install -m 644 deployment/zaloflow.service /etc/systemd/system/zaloflow.service
systemctl daemon-reload
systemctl restart zaloflow
systemctl status zaloflow --no-pager
```

Node.js cần >=18 theo thư viện; dùng gói được nhà cung cấp hệ điều hành hỗ trợ hoặc Node LTS phù hợp. Sau cập nhật, vào /accounts tạo hồ sơ, xác nhận rủi ro kết nối không chính thức rồi tạo QR, quét và xác nhận bằng điện thoại. Chỉ thành công khi UI báo được Zalo xác nhận. Không quét QR mà người khác gửi, không gửi ảnh QR hoạt động hoặc cookie cho hỗ trợ.

## Cập nhật gửi từng tin

Trên VPS đã cài QR, chạy riêng từng lệnh:

```sh
cd /opt/zaloflow
git pull --ff-only origin main
systemctl restart zaloflow
systemctl status zaloflow --no-pager
```

Không cần xóa instance hoặc quét lại nếu phiên còn hiệu lực. Bảng message_sends tự được thêm. Mở Hành động của chiến dịch, chọn tài khoản/khách hàng thử đã đồng ý, tìm người nhận và kiểm tra tên Zalo trước khi xác nhận gửi một tin. Kiểm tra tin đến trong Zalo của người nhận. Không xem kiểm thử mô phỏng hoặc mã tin là chứng cứ người nhận đã đọc. Nếu kết quả chưa xác định, kiểm tra hội thoại trước khi gửi lại thủ công.
