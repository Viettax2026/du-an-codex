# Bản quyền ZaloFlow Windows

Mỗi key dùng trên một máy Windows. Chủ phần mềm cấp key, đặt số ngày sử dụng, gia hạn, thu hồi hoặc hủy máy cũ qua trang quản trị riêng. Key khác với mật khẩu tài khoản ZaloFlow và mật khẩu root VPS.

Tool kiểm tra máy chủ mỗi lần mở và mỗi 5 phút khi đang mở. Máy chủ cấp phiên có chữ ký Ed25519, gắn với mã máy; phiên tối đa 1 giờ và không vượt hạn key. Khi mất mạng trong lúc đang dùng, phiên còn hạn được dùng tiếp tới thời điểm đó. Khi hết phiên/key hoặc máy chủ từ chối, không nhận thêm lượt chạy. Lượt đã bắt đầu được kết thúc; kết quả, bước chờ và hạn mức giữ nguyên. Gia hạn không tạo chiến dịch mới và không gửi lại bước đã làm.

## Cài máy chủ trên VPS hiện tại

Trong SSH root của VPS 103.77.172.174:

```bash
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/install-license-server.sh
```

Script yêu cầu tên miền đã có HTTPS, sao lưu cấu hình trước khi thêm đường dẫn `/licenses/`, tạo dịch vụ riêng `zaloflow-license` trên `127.0.0.1:8010`. Không mở cổng 8010 ra Internet. Script không bật/tắt bộ lịch chiến dịch trên VPS và không sửa database khách hàng. Khi cập nhật dịch vụ key, script sao lưu cả kho bản quyền trước; không tạo lại khóa ký đã có. Nếu Nginx không hợp lệ, cấu hình website được khôi phục và việc cài dịch vụ key dừng lại.

Mở **https://cskh.viettaxco.com/licenses/admin**. Xem mật khẩu quản trị ban đầu bằng:

```bash
cat /var/lib/zaloflow-licenses/admin-password.txt
```

Chỉ chủ phần mềm giữ mật khẩu này. Khách hàng không có quyền quản trị bằng tài khoản ZaloFlow của họ. Đổi mật khẩu quản trị qua SSH (nhập kín, không đưa mật khẩu vào dòng lệnh):

```bash
cd /opt/zaloflow
runuser -u zaloflow-license -- .venv/bin/python -m license_system.admin set-admin-password
```

Sau khi đổi, các phiên quản trị cũ hết hiệu lực và tệp mật khẩu ban đầu được xóa.

## Cấu hình bản Windows trước khi phát cho khách

Trên VPS, lấy **duy nhất cấu hình công khai** này:

```bash
cat /var/lib/zaloflow-licenses/client-config.json
```

Tệp chỉ có `version`, `server_url`, `public_key`. Có thể gửi nội dung tệp cho người dựng phần mềm hoặc lưu thành `desktop/license-config.json` trong kho mã. **Không gửi `signing-private.pem`, `admin-password.txt`, `session-secret.txt`, database bản quyền hoặc bản sao lưu authority.** Khóa ký chỉ được tạo và lưu trên VPS của chủ phần mềm.

GitHub Actions → **Build Windows desktop → Run workflow**: dán JSON công khai vào trường `license_config`, chọn main rồi Run workflow. Hoặc commit `desktop/license-config.json` để workflow tự dùng cho các lần dựng sau. Nếu chưa có cấu hình, workflow chỉ kiểm thử gói với danh tính tạm; không xuất bản gói khách hàng. Không dùng khóa thử để cấp key thật.

Khi lượt dựng có dấu xanh và artifact, tải `ZaloFlow-Windows-x64`, giải nén toàn bộ. Gói khách hàng chỉ có khóa công khai; không đóng gói kho key hoặc công cụ quản trị server. Dựng thủ công trên Windows cũng yêu cầu cấu hình công khai hợp lệ trước.

## Cấp, gia hạn và chuyển máy

1. Trang quản trị → nhập tên khách hàng và số ngày → **Tạo key — 1 máy**. Hạn tính từ lúc cấp key. Sao chép key ngay và gửi riêng cho khách: hệ thống chỉ lưu hash của key, không thể xem lại key gốc ở danh sách.
2. Khách mở tool → **Bản quyền** → nhập key → kích hoạt. Sau đó tạo/đăng nhập tài khoản ZaloFlow và quét QR Zalo như trước.
3. Gia hạn: chọn key trong trang quản trị → nhập số ngày → **Gia hạn / mở lại key**. Thêm ngày từ hạn hiện tại nếu còn hạn, hoặc từ hiện tại nếu đã hết hạn. Khách bấm **Kiểm tra lại / cập nhật gia hạn**, hoặc chờ lần kiểm tra định kỳ.
4. Chuyển máy: trên máy cũ, đăng nhập ZaloFlow → **Bản quyền → Hủy kích hoạt máy này**. Khi báo thành công, nhập cùng key trên máy mới. Đóng cửa sổ thông thường không hủy kích hoạt key. Không tự động đồng bộ dữ liệu chiến dịch sang máy mới.
5. Máy cũ bị mất/hỏng: chủ phần mềm dùng **Hủy máy để chuyển máy** trên trang quản trị rồi cấp lại cùng key cho máy mới. Máy cũ bị chặn ở lần kiểm tra tiếp; nếu đang mất mạng, phiên cũ có thể còn hiệu lực tối đa 1 giờ. Tương tự, thu hồi key được áp dụng trong khoảng này; không thể thu hồi ngay một máy không kết nối mạng.
6. Đổi sang key khác: hủy kích hoạt key hiện tại trước, để không giữ nhầm suất máy của key cũ. Không xóa thư mục dữ liệu hoặc database để đổi key.

## Vận hành và khôi phục

```bash
systemctl status zaloflow-license --no-pager
journalctl -u zaloflow-license -n 50 --no-pager
cd /opt/zaloflow
runuser -u zaloflow-license -- .venv/bin/python -m license_system.admin list
```

CLI cũng có `issue --customer TEN --days 30`, `extend ID --days 30`, `revoke ID`, `reset-devices ID`. Mặc định cấp một máy. Không gửi key riêng qua kho mã hoặc log công khai.

Sao lưu toàn bộ `/var/lib/zaloflow-licenses` trong lúc riêng dịch vụ key đã dừng; giữ bản sao ở nơi chỉ chủ phần mềm truy cập. Khi khôi phục phải giữ cả database, `signing-private.pem` và `session-secret.txt`. Không chạy `init` lại hoặc tạo khóa ký khác cho bản Windows đã phát. Mất khóa ký cần dựng lại bản khách với khóa công khai mới và cấp lại key.

Nếu cửa sổ key cần cấu hình máy chủ, kiểm tra gói được dựng với đúng `client-config.json`. Nếu xác thực thất bại do thời gian, bật đồng bộ ngày giờ Windows. Nếu key đủ số máy, hủy máy cũ hoặc nhờ chủ phần mềm reset; việc đăng ký tài khoản ZaloFlow mới không tăng số máy được phép.

Giới hạn: cơ chế áp dụng cho bản Windows mới có tích hợp kiểm tra key. Bản cũ chưa có kiểm tra vẫn hoạt động như trước; không thể thêm kiểm tra từ xa cho tệp EXE đã phát. Kho mã hiện công khai, nên đây là quản lý kích hoạt cho bản phân phối của chủ phần mềm, không phải cơ chế chống sửa mã tuyệt đối.
