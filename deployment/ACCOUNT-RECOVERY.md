# Quên mật khẩu ZaloFlow

Màn hình đăng nhập có **Quên mật khẩu?** để đặt mật khẩu mới, không hiển thị lại mật khẩu cũ. Bản web ưu tiên mã 5 số gửi đến email đã xác minh; xem [cấu hình Gmail và kiểm thử email](EMAIL-RECOVERY.md). Mã khôi phục bên dưới dùng dự phòng khi không truy cập email. Bản Windows và web có tài khoản/mã riêng.

## Khi còn đăng nhập được

Mở **Bảo mật tài khoản** → xác nhận mật khẩu hiện tại → **Tạo mã khôi phục** → **Tải mã khôi phục**. Cất tệp ở nơi riêng tư, không cùng mật khẩu. Mã chỉ hiển thị khi tạo; hệ thống lưu SHA-256 của mã ngẫu nhiên 128 bit, không lưu mã gốc. Mỗi tài khoản có một mã cá nhân; tạo mã thay thế vô hiệu hóa mã cá nhân cũ. Mã không tự hết hạn nhưng dùng thành công một lần sẽ hết hiệu lực.

## Khi quên mật khẩu

Chọn **Quên mật khẩu? → Chưa xác minh email hoặc không nhận được thư? → dùng mã khôi phục dự phòng**, nhập tài khoản, mã đã lưu và hai lần mật khẩu mới (8–256 ký tự). Thành công sẽ trở về đăng nhập. Tất cả phiên đăng nhập và mã khôi phục cũ của tài khoản hết hiệu lực; đăng nhập lại rồi tạo mã mới.

Khách hàng, chiến dịch, lịch sử, tiến độ, hạn mức, phiên Zalo và key được giữ nguyên. Không xóa database hoặc đăng ký tài khoản khác để lấy lại dữ liệu. API token tích hợp và bộ lịch không bị thay đổi bởi đặt lại mật khẩu.

Mã không hợp lệ/đã dùng/hết hạn và tài khoản không tồn tại trả cùng thông báo lỗi. POST yêu cầu CSRF; mã/mật khẩu không nằm trong URL hoặc cookie. Giới hạn thử lưu trong SQLite, không bị đặt lại khi khởi động web; thử quá nhiều cần chờ 15 phút. Bản web chỉ nhận X-Real-IP từ Nginx trên loopback (Nginx ghi đè bằng địa chỉ khách); bỏ qua header từ kết nối ngoài và X-Forwarded-For. Bản Windows không tin proxy header. Nếu dùng cấu hình proxy khác, có thể đặt RECOVERY_TRUST_LOCAL_PROXY=False trong cấu hình ứng dụng.

## Tài khoản web cũ chưa có mã hoặc đã mất mã

Chủ VPS xác minh người yêu cầu qua kênh liên lạc đã biết trước rồi chạy bằng người dùng dịch vụ:

```bash
cd /opt/zaloflow
runuser -u zaloflow -- .venv/bin/flask --app app:create_app issue-recovery-code --username TEN_TAI_KHOAN
```

Lệnh chỉ cấp cho tài khoản đã tồn tại, không tạo tài khoản/đổi mật khẩu ngay. Mã hỗ trợ có hiệu lực **15 phút**, dùng **một lần**; chỉ gửi riêng sau khi xác minh chủ tài khoản. Cấp lại vô hiệu hóa mã hỗ trợ cũ. Mã cá nhân vẫn dùng được cho tới khi đặt lại thành công; khi thành công mọi mã cũ đều hết hiệu lực.

Với bộ cài web mới tên mặc định `zaloflow-web`, dùng `/opt/zaloflow-web` và người dùng `zaloflow-web`. Không cấp mã trên VPS để khôi phục tài khoản Windows: hai database tách biệt.

`reset-admin` vẫn đặt trực tiếp mật khẩu `admin` trên VPS, nay cũng vô hiệu hóa phiên và mã cũ. Đây không phải tài khoản quản trị key tại `/licenses/admin`.

## Tài khoản Windows cũ chưa có mã hoặc đã mất mã

Chủ phần mềm không thể lấy tài khoản Windows từ VPS. Quản trị viên Windows có quyền quản lý dữ liệu trên **chính máy đó** có thể cấp mã hỗ trợ bằng bản cài mới. Chức năng yêu cầu quyền quản trị Windows, không phải nút HTTP công khai và không nhận key làm bằng chứng sở hữu tài khoản.

1. Đóng tool hoàn toàn, chờ lượt đang xử lý kết thúc.
2. Mở **PowerShell → Run as administrator** bằng cùng tài khoản Windows đang lưu dữ liệu.
3. Chạy, thay `TEN_TAI_KHOAN` bằng tên đăng nhập ZaloFlow:

```powershell
$zaloData = Join-Path $env:LOCALAPPDATA 'ZaloFlow'
$zaloExe = Join-Path $env:LOCALAPPDATA 'Programs\ZaloFlow\ZaloFlow.exe'
& $zaloExe --support-recovery TEN_TAI_KHOAN --data-dir $zaloData
```

4. Kiểm tra tài khoản/thư mục trong hộp thoại rồi xác nhận. Mã dùng một lần hiện ra, hết hạn sau 15 phút. Bấm **Ctrl+C** trong hộp thoại để sao chép nội dung.
5. Mở lại tool bình thường, chọn **Quên mật khẩu?** và dùng mã đặt mật khẩu mới.

Nếu nâng quyền bằng tài khoản quản trị viên khác, điền **đường dẫn thật của người dùng cần hỗ trợ** vào `$zaloData` và `$zaloExe`, tránh dùng nhầm `%LOCALAPPDATA%` của quản trị viên. Lệnh từ chối tài khoản không tồn tại hoặc tool đang mở, không khởi động bộ lịch/gửi tin.

Người có quyền quản trị hệ điều hành có thể quản lý dữ liệu cục bộ. Key Windows vẫn được kiểm tra riêng, không bị bỏ qua bởi chức năng hỗ trợ này.

## Cập nhật

Kiểm thử VPS trước khi dựng Windows:

1. Cập nhật VPS bằng các lệnh bên dưới, lưu thông báo thư mục sao lưu và kết quả cập nhật.
2. Mở `https://cskh.viettaxco.com/login`, kiểm tra có **Quên mật khẩu?**.
3. Dùng một tài khoản thử riêng, không thêm tài khoản Zalo hoặc tạo chiến dịch gửi thật. Tài khoản đăng ký mới cần được quản trị viên duyệt trong **Quản lý tài khoản** trước khi đăng nhập. Sau khi duyệt, đăng nhập, mở **Bảo mật tài khoản**, xác nhận mật khẩu rồi tạo/tải mã.
4. Đăng nhập cùng tài khoản thử ở một trình duyệt khác để kiểm tra vô hiệu hóa phiên cũ. Đăng xuất ở trình duyệt đầu, chọn **Quên mật khẩu?**, nhập mã và đặt mật khẩu mới.
5. Kiểm tra đăng nhập được bằng mật khẩu mới; mật khẩu cũ không dùng được, phiên trình duyệt thứ hai yêu cầu đăng nhập lại, mã đã dùng không thể dùng lần nữa. Không thử đổi mật khẩu tài khoản đang vận hành để tránh gián đoạn công việc.
6. Kiểm tra tài khoản làm việc vẫn hiển thị dữ liệu/tiến độ bình thường. Báo kết quả hoặc lỗi; chỉ sau khi xác nhận VPS chạy ổn mới kích hoạt **Build Windows desktop → Run workflow → vps_tested** với đúng phiên bản đã thử. Không thay mã giữa lần thử VPS và lần đóng gói.

Các kiểm tra trong CI hoặc container không thay thế bước xác nhận trên VPS thật. Workflow Windows đã bỏ kích hoạt tự động khi push để giữ đúng thứ tự này.

- Windows: tải **Build Windows desktop → Artifacts → ZaloFlow-Setup-Windows-x64**, đóng tool rồi cài đè. Dữ liệu/kích hoạt được giữ nguyên.
- VPS hiện tại: `cd /opt/zaloflow`, `git pull --ff-only origin main`, `bash deployment/update.sh`. Script sao lưu nhất quán trước khi nâng cấp, không cài lại VPS.
- Schema thêm `auth_version`, bảng hash mã và bảng giới hạn lượt thử. Cookie cũ của tài khoản chưa đổi mật khẩu vẫn hợp lệ; sau khi đặt lại thì hết hiệu lực. Bản sao lưu đầy đủ `instance` bao gồm các bảng mới; cần bảo vệ bản sao lưu.
