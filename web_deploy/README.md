# ZaloFlow Web — bộ cài cho VPS và domain mới

Đăng ký mới ở trạng thái chờ duyệt. Chủ VPS thiết lập quản trị viên bằng `runuser -u zaloflow-web -- /opt/zaloflow-web/.venv/bin/flask --app app:create_app grant-admin --username TEN_TAI_KHOAN` trong `/opt/zaloflow-web` sau khi tài khoản chủ đã đăng ký. Không tự cấp quyền quản trị qua đăng ký công khai; nếu tên/thư mục cài khác cần thay tương ứng. Sau đó đăng nhập lại, mở **Quản lý tài khoản** để duyệt người dùng. Nút Đăng xuất luôn hiện trên thanh trên cùng. Xem [hướng dẫn đầy đủ](https://github.com/Viettax2026/du-an-codex/blob/main/deployment/ACCOUNT-APPROVAL.md).

Đăng nhập có **Quên mật khẩu?** bằng mã khôi phục dùng một lần. Khi còn đăng nhập, mở **Bảo mật tài khoản** để tạo/tải mã. Với tài khoản đã mất mật khẩu và chưa có mã, chủ VPS xác minh rồi cấp mã hỗ trợ 15 phút bằng `runuser -u zaloflow-web -- /opt/zaloflow-web/.venv/bin/flask --app app:create_app issue-recovery-code --username TEN_TAI_KHOAN` (chạy trong `/opt/zaloflow-web`; thay tên dịch vụ/thư mục nếu cài tên khác). Đặt lại giữ dữ liệu và vô hiệu hóa phiên cũ. Xem [hướng dẫn đầy đủ](https://github.com/Viettax2026/du-an-codex/blob/main/deployment/ACCOUNT-RECOVERY.md).

Gói `zaloflow-web.zip` chứa mã nguồn web, giao diện, bộ kết nối Zalo và script cài đặt. Mã không gắn với domain/IP cũ. Dùng Ubuntu 24.04 LTS x64 hoặc ARM64; cần Internet để tải Python/Node/thư viện và kết nối Zalo. Bản web có tài khoản, database và bộ chạy lịch riêng; không yêu cầu key Windows.

## Cài nhanh trên VPS mới

1. Trỏ bản ghi DNS **A** của domain mới vào IP VPS. Nếu có AAAA, bản ghi đó cũng phải trỏ đúng VPS. Mở cổng 22 cho SSH và 80/443 cho website trong firewall của nhà cung cấp; không mở cổng nội bộ 8040.
2. Tải ZIP về Windows. Trong PowerShell, thay `IP_VPS_MOI` bằng IP thật:

```powershell
scp "$env:USERPROFILE\Downloads\zaloflow-web.zip" root@IP_VPS_MOI:/root/
```

3. SSH vào VPS mới, rồi chạy (thay domain/email bằng thông tin thật):

```bash
apt-get update
apt-get install -y unzip python3
unzip /root/zaloflow-web.zip -d /root/
cd /root/zaloflow-web
bash web_deploy/install-web.sh --domain crm.example.com --email owner@example.com
```

Script cài Python, Node 22 riêng cho bản web, thư viện đã khóa phiên bản, Nginx, HTTPS tự gia hạn và dịch vụ chạy nền. Nginx chỉ chuyển yêu cầu của domain đã nhập đến cổng loopback. Script không thay Node của website khác và từ chối ghi đè bản cài/domain/cổng đã tồn tại.

4. Mở `https://crm.example.com/register`, tự tạo tài khoản; không có mật khẩu mẫu. Thêm tài khoản Zalo và quét QR.
5. Khi sẵn sàng chạy lịch:

```bash
systemctl enable --now zaloflow-web-scheduler.service
```

Bộ lịch mặc định chưa bật, để có thời gian kiểm tra dữ liệu và tránh chạy trùng khi khôi phục chiến dịch cũ. Nếu cài mới hoàn toàn và muốn bật ngay, thêm `--start-scheduler` vào lệnh cài. Đóng trình duyệt không dừng bản web.

## Đặt tên riêng hoặc cài nhiều bản

```bash
bash web_deploy/install-web.sh --domain crm2.example.com --email owner@example.com --name crm2-web --port 8050
```

Tên bản cài mặc định `zaloflow-web`, cổng `8040`, mã/dữ liệu ở `/opt/zaloflow-web`. Tham số `--name` đổi đồng thời thư mục, user hệ thống và tên các dịch vụ; `--port` phải là cổng chưa dùng. Mỗi bản cài có database/tài khoản/ảnh/khóa riêng. Không đặt tên `zaloflow` để tránh nhầm bản VPS cũ.

File cấu hình đã dùng lưu ở `/opt/zaloflow-web/web-installation.json`. Xem trạng thái và lỗi:

```bash
systemctl status zaloflow-web --no-pager
systemctl status zaloflow-web-scheduler --no-pager
journalctl -u zaloflow-web -n 60 --no-pager
```

Thay tên dịch vụ tương ứng nếu đã dùng `--name` khác. Tạo/đặt lại mật khẩu tài khoản admin web khi cần:

```bash
cd /opt/zaloflow-web
runuser -u zaloflow-web -- .venv/bin/flask --app app reset-admin
```

## Chuyển dữ liệu và chiến dịch từ VPS cũ

ZIP chỉ chứa mã, **không chứa khách hàng, lịch sử, ảnh hoặc mật khẩu từ VPS cũ**. Muốn giữ dữ liệu cần sao lưu toàn bộ `instance`, gồm SQLite, media, `session.key`, `zalo/auth.key` và các phiên QR. Chỉ sao chép thư mục khi web và bộ lịch tương ứng đã dừng; sao chép riêng file SQLite có thể bỏ sót ảnh hoặc làm dữ liệu không nhất quán.

Tải và giải nén cùng gói mã này trên VPS cũ để có script sao lưu. Nếu VPS cũ dùng tên dịch vụ `zaloflow`, chạy script với tên đó:

```bash
bash /root/zaloflow-web/web_deploy/backup-web.sh zaloflow /var/backups/zaloflow-transfer
```

Script chỉ dừng hai dịch vụ của bản được chọn, chép toàn bộ instance vào một tệp `.tar.gz` rồi khôi phục trạng thái chạy trước đó. Bản sao lưu chứa thông tin riêng tư; lưu ngoài mã nguồn và chỉ chủ VPS được truy cập. Chuyển bản sao đó sang VPS mới qua SCP/SFTP.

Trước khi thay dữ liệu ở VPS mới, dừng bộ lịch và web mới. Nếu đã có dữ liệu mới, sao lưu trước. Ví dụ với bản cài mặc định:

```bash
systemctl stop zaloflow-web-scheduler zaloflow-web
mv /opt/zaloflow-web/instance "/opt/zaloflow-web/instance-before-restore-$(date +%Y%m%d-%H%M%S)"
tar -xzf /root/instance-backup.tar.gz -C /opt/zaloflow-web
chown -R zaloflow-web:zaloflow-web /opt/zaloflow-web/instance
chmod 700 /opt/zaloflow-web/instance
systemctl start zaloflow-web
```

Đăng nhập bằng tài khoản web cũ, kiểm tra ảnh/lịch sử/tài khoản Zalo và đăng nhập QR lại nếu phiên đã hết hiệu lực. **Dừng bộ lịch ở VPS cũ trước khi bật lịch VPS mới**, để hai bản sao cùng chiến dịch không cùng gửi. Không xóa dữ liệu cũ trước khi kiểm tra xong. `instance-before-restore` là bản giữ lại để có thể quay lại, không được đưa vào Git hoặc chia sẻ công khai.

## Phạm vi của gói

Gói không có ứng dụng Windows, kho key Windows, khóa ký bản quyền hay dữ liệu thực. Máy chủ cấp key tại `/licenses/` là dịch vụ khác; việc tạo bản web ở domain mới không chuyển hoặc thay đổi máy chủ key đang dùng cho Windows. Muốn di chuyển máy chủ key cần chuyển riêng kho bản quyền và giữ nguyên khóa ký; xem tài liệu bản quyền trong kho mã.

Các thư viện Python và npm cần tải khi cài; ZIP không phải bản cài ngoại tuyến. `--http-only` chỉ phục vụ kiểm tra nội bộ trước khi có DNS/HTTPS, không dùng cho tài khoản hoặc dữ liệu thật. Việc cấp SSL cần domain đã trỏ đúng và cổng 80/443 truy cập được.

Nếu cài lỗi giữa chừng, script giữ thư mục mới để xem log và từ chối ghi đè khi chạy lại. Không xóa một thư mục đã có dữ liệu để thử cài lại. Kiểm tra DNS/certbot/Nginx theo thông báo; mã và cấu hình render có thể dùng để hoàn tất cài đặt thủ công. Đây là script cài mới, không thay thế quy trình cập nhật hoặc sao lưu bản đang dùng.
