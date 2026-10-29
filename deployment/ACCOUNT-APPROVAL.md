# Duyệt đăng ký và đăng xuất

Trên **bản web**, đăng ký mới tạo tài khoản **Chờ duyệt**, không tự đăng nhập. Chỉ sau khi quản trị viên duyệt, người dùng mới đăng nhập được bằng mật khẩu đã đăng ký. Đặt lại mật khẩu, tạo cookie hoặc gửi thêm trường `role=admin` không thay thế bước duyệt.

Trên **tool Windows**, kích hoạt key hợp lệ rồi tự đăng ký và đăng nhập sử dụng ngay, không cần duyệt. Tài khoản chờ duyệt còn từ bản Windows trước được cho phép sử dụng khi đăng nhập đúng mật khẩu với key hợp lệ. Tài khoản bị khóa/từ chối rõ ràng vẫn bị chặn; không tự cấp vai trò quản trị. Việc bỏ bước duyệt chỉ áp dụng trong runtime Windows có bộ kiểm tra license, không áp dụng cho website.

## Cập nhật VPS và thiết lập quản trị viên

Chạy trong SSH của VPS hiện tại:

```bash
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/update.sh
runuser -u zaloflow -- .venv/bin/flask --app app:create_app grant-admin --username admin
```

Lệnh cuối dành cho chủ VPS, cấp quyền trên **tài khoản ZaloFlow đã tồn tại**, giữ nguyên mật khẩu và dữ liệu. Nếu tài khoản chủ ứng dụng không tên `admin`, thay bằng tên tài khoản đáng tin cậy của bạn. Không cấp cho một đăng ký chưa xác minh chỉ vì tên giống tên chủ phần mềm. Lệnh báo lỗi khi tài khoản không tồn tại, không tự tạo người dùng. Nếu chưa có tài khoản quản trị và muốn tạo tên `admin`, dùng lệnh `reset-admin` hiện có và nhập mật khẩu mới hai lần.

Đăng nhập lại tài khoản vừa được cấp quyền. Menu xuất hiện **Quản lý tài khoản**, địa chỉ `/admin/users`. Quyền này tách biệt với mật khẩu root VPS, key Windows và trang quản trị key `/licenses/admin`. Mọi người dùng mới đều có vai trò thường; hệ thống không tự cấp quyền quản trị cho tài khoản đầu tiên hay chỉ dựa vào tên `admin`.

## Duyệt và khóa

- **Chờ duyệt**: kiểm tra họ tên/tên đăng nhập, bấm **Duyệt** hoặc **Từ chối**.
- **Đã duyệt**: đăng nhập và sử dụng bình thường. Có thể **Khóa truy cập** khi cần.
- **Đã khóa/Từ chối**: chưa được đăng nhập; có thể duyệt lại sau khi xác minh.
- Có tìm kiếm, lọc trạng thái và phân trang. Không hiển thị mật khẩu hoặc mã khôi phục của người khác.

Chỉ quản trị viên đã đăng nhập được xem danh sách/thao tác. Các thao tác yêu cầu CSRF và được ghi vào lịch sử quản trị trong database. Không khóa chính mình hoặc tài khoản quản trị khác qua giao diện này. Cấp quyền quản trị mới chỉ qua lệnh tại máy chủ; tài khoản thường không thể tự nâng quyền.

Khóa truy cập vô hiệu hóa phiên cũ, chặn khóa API của người dùng và các lượt chạy chiến dịch mới. Lượt đã bắt đầu được ghi kết quả, không gửi lại. Dữ liệu, key API và tiến độ không bị xóa; khi được duyệt lại, người dùng phải đăng nhập lại, API còn hạn được dùng lại và lịch còn bật tiếp tục theo điều kiện đã lưu. Việc duyệt không đặt lại lịch sử gửi hoặc hạn mức.

## Tài khoản đã có trước bản cập nhật

Để xóa một tài khoản thử trống, chủ VPS có thể chạy `runuser -u zaloflow -- .venv/bin/flask --app app:create_app delete-test-user --username test12345` trong `/opt/zaloflow` sau khi cập nhật và khởi động lại web bằng `deployment/update.sh`. Lệnh tìm đúng tên, chỉ nhận tên bắt đầu bằng `test`, từ chối tài khoản quản trị hoặc tài khoản còn dữ liệu/liên kết; chỉ xóa người dùng thử cùng mã khôi phục và lịch sử duyệt của chính người đó. Không tự xóa dây chuyền khách hàng/chiến dịch hoặc lịch sử của tài khoản khác. Không tìm thấy thì không thay đổi gì. Mã định danh đã xóa không được cấp lại để phiên đăng nhập cũ không thể truy cập tài khoản đăng ký sau đó. Đây là lệnh CLI của chủ VPS, không phải API công khai.

Các tài khoản cũ giữ trạng thái được phép sử dụng để không làm gián đoạn hoạt động. Chúng không tự có quyền quản trị. Chủ VPS cấp quyền cho đúng tài khoản chủ ứng dụng bằng `grant-admin`, sau đó xem tab **Đã duyệt** và khóa những tài khoản không còn được phép sử dụng. Đăng ký mới sau cập nhật luôn chờ duyệt, kể cả sau khởi động lại hoặc nâng cấp tiếp.

## Nút Đăng xuất

Nút **Đăng xuất** nằm ở góc phải thanh trên cùng, hiện trên mọi trang đăng nhập kể cả Chiến dịch, Media và màn hình nhỏ. Thanh này bám theo khi cuộn. Menu trái có thể cuộn khi thấp. Đăng xuất dùng POST có CSRF và xóa phiên trình duyệt, không hủy key hoặc xóa dữ liệu. Bộ lịch web tiếp tục theo cài đặt như trước; muốn dừng chiến dịch cần tạm ngừng chiến dịch riêng.

## Kiểm thử VPS trước khi đóng gói Windows

1. Dùng tài khoản quản trị đã cấp quyền, kiểm tra trang Quản lý tài khoản.
2. Trình duyệt khác đăng ký một tài khoản thử, xác nhận không tự đăng nhập và đăng nhập bị báo chờ duyệt.
3. Quản trị viên duyệt; tài khoản thử đăng nhập được.
4. Kiểm tra nút Đăng xuất ở Bảo mật tài khoản, Chiến dịch, Media và khi thu nhỏ màn hình. Đăng xuất rồi truy cập trang riêng phải quay về đăng nhập.
5. Khóa tài khoản thử; phiên cũ không vào được trang riêng. Duyệt lại rồi đăng nhập lại. Tài khoản thường không truy cập được `/admin/users`.
6. Kiểm thử Quên mật khẩu bằng tài khoản thử đã duyệt. Đặt lại mật khẩu không tự duyệt tài khoản còn chờ.

Chỉ sau khi VPS được xác nhận hoạt động đúng mới chạy workflow Windows thủ công với `vps_tested`. Cập nhật lần này không tự tạo bộ cài Windows.

## Quyền quản trị cục bộ Windows khi chủ máy có nhu cầu

Bản Windows có dữ liệu/tài khoản riêng, không nhận duyệt từ VPS. Người dùng bình thường không cần các bước dưới đây để đăng ký hoặc sử dụng tool sau khi kích hoạt key. Nếu chủ máy muốn quản lý/khóa các tài khoản cục bộ, sau khi đăng ký tài khoản chủ máy, đóng tool, mở PowerShell bằng quyền quản trị viên Windows trên đúng máy và chạy:

```powershell
$zaloData = Join-Path $env:LOCALAPPDATA 'ZaloFlow'
$zaloExe = Join-Path $env:LOCALAPPDATA 'Programs\ZaloFlow\ZaloFlow.exe'
& $zaloExe --grant-account-admin TEN_TAI_KHOAN --data-dir $zaloData
```

Kiểm tra thông tin trong hộp thoại rồi xác nhận. Mở tool bình thường và đăng nhập lại để duyệt người dùng khác. Lệnh yêu cầu quyền quản trị Windows, dữ liệu/tài khoản đã tồn tại và tool đã đóng; không thay mật khẩu hoặc bỏ kiểm tra key. Nếu dùng tài khoản Windows quản trị khác, điền đúng đường dẫn của người dùng đang được hỗ trợ.
