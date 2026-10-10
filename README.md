# ZaloFlow

## Đường dẫn dùng thử trên Render

Kho đã có `render.yaml` và `requirements-prod.txt` cho bản dùng thử bằng Gunicorn. Sau khi mã nguồn được đưa lên GitHub, kết nối kho `Viettax2026/du-an-codex` với Render và tạo Blueprint từ `render.yaml`. Render cung cấp địa chỉ HTTPS của dịch vụ sau khi triển khai thành công; hiện chưa có dịch vụ hoặc địa chỉ được tạo.

Bản Render miễn phí dùng SQLite trên ổ đĩa tạm: tài khoản và dữ liệu có thể mất khi khởi động lại hoặc triển khai lại. Chỉ dùng dữ liệu thử. Muốn dùng thực tế cần ổ đĩa bền vững hoặc cơ sở dữ liệu ngoài và các bước vận hành bên dưới. Dịch vụ miễn phí có thể ngủ khi không hoạt động; cần kiểm tra hạn mức của tài khoản Render.

Ứng dụng web tiếng Việt cho quản lý khách hàng và chuẩn bị chiến dịch Zalo cá nhân, viết bằng Flask và SQLite.

## Chạy tại máy phát triển

```sh
cd /workspace/du-an-codex
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python app.py
```

Ứng dụng phục vụ trên cổng 8000. Mở trang đăng ký để tạo tài khoản; không có mật khẩu mặc định. Dữ liệu nằm trong `instance/zalo.sqlite3`; khóa phiên được tạo trong `instance/session.key`. Các tệp này bị Git bỏ qua và cần được bảo vệ, sao lưu khi triển khai.

## Quy trình

1. Đăng ký hoặc đăng nhập.
2. Thêm khách hàng hoặc nhập CSV UTF-8 (cột `name,phone`, tùy chọn `tag,zalo_id,consent`).
3. Ghi nhận sự đồng ý nhận tin khi đã có sự đồng ý thực tế.
4. Tạo chiến dịch với nhóm khách hàng; dùng `{{name}}` trong nội dung để cá nhân hóa.
5. Xem trước rồi gửi thử. Tin nhắn chỉ được ghi vào cơ sở dữ liệu, **không gửi đến Zalo**. Mỗi chiến dịch được gửi thử một lần; tạo chiến dịch mới để chạy lại.

Dữ liệu được phân tách theo tài khoản. Các biểu mẫu có bảo vệ CSRF và mật khẩu được băm bằng Werkzeug. Không có dữ liệu khách hàng giả được tự động thêm.

## Kiểm thử

```sh
.venv/bin/python -m pytest -q
```

## Phạm vi hiện tại

Đã có đăng nhập, dữ liệu bền vững, nhập CSV, tìm khách hàng, phân nhóm, cập nhật đồng ý nhận tin, tạo chiến dịch, xem trước và nhật ký mô phỏng. Giao diện chiến dịch và hộp thoại thêm tài khoản đã được chỉnh theo ảnh Akabiz do người dùng cung cấp. Bộ lọc tìm kiếm/thời gian/trạng thái/nhóm và nhật ký từng chiến dịch sử dụng dữ liệu lưu trong ứng dụng. Trang `/accounts` lưu hồ sơ tên và nhóm; chưa đăng nhập Zalo.

**Chưa có gửi thật, OAuth OA, webhook, lịch gửi, hàng đợi, ZNS, thanh toán hay kết bạn tự động.** Để triển khai gửi thật cần xác nhận OA, loại tin và quyền API; xây dựng OAuth và token refresh, mã hóa token, xác minh webhook, chính sách người nhận và hàng đợi có retry/idempotency theo tài liệu Zalo hiện hành. Không dùng số điện thoại thay cho OA user ID.

Máy chủ Flask hiện tại phục vụ phát triển. Trước khi mở công khai cần máy chủ WSGI, HTTPS, `COOKIE_SECURE=1`, hạn chế tốc độ đăng nhập/đăng ký, kiểm soát đăng ký, quản lý khôi phục tài khoản, sao lưu và vận hành. Không đưa khóa hoặc token vào Git.

## Hướng sử dụng đã chọn: Zalo cá nhân

Sau khi chạy mô phỏng, sao chép nội dung trong nhật ký và tự gửi qua ứng dụng Zalo. Có bộ kết nối QR cá nhân không chính thức ở phiên bản mới; ứng dụng không tự chọn người nhận và không xác nhận gửi thật. Gửi tự động chưa triển khai.

## Giao diện theo ảnh tham chiếu

Trang `/campaigns` có bảng, bộ lọc, chi tiết và nhật ký bên phải. Chọn tên chiến dịch để xem chi tiết; nút Hành động mở màn hình xem trước/gửi thử. Có nút sao chép nội dung từng tin mô phỏng (cần trình duyệt cho phép clipboard). Hộp thoại `/accounts` cho phép lưu tên và nhóm tài khoản; Mở Zalo dẫn tới trang Zalo Web chính thức và không liên kết phiên đăng nhập về ứng dụng. Proxy chưa được hỗ trợ. Phiên bản mới có đăng nhập QR qua zca-js; xem mục bên dưới.

## Đăng nhập QR Zalo cá nhân (kết nối không chính thức)

Bộ kết nối dùng [zca-js 2.2.0](https://github.com/RFS-ADRENO/zca-js). Đây không phải API chính thức của Zalo; tác giả cảnh báo có thể bị khóa/hạn chế tài khoản. Người dùng phải xác nhận trước khi tạo QR. QR được lấy từ Zalo, không tự tạo QR giả. Chỉ ghi nhận thành công sau khi Zalo xác nhận. Chưa có gửi tự động, listener, quét data hay tự động kết bạn.

Cần Node.js >=18 và npm trên VPS. Cài phụ thuộc đã khóa phiên bản:

```sh
cd /opt/zaloflow
npm ci --prefix connector --ignore-scripts --no-audit --no-fund
```

Đặt `ZALO_QR_ENABLED=1` trong dịch vụ. Tệp deployment/zaloflow.service mới có thiết lập này. Tiến trình Node chỉ chạy khi có yêu cầu QR, tối đa 10 phiên đồng thời và tự dừng sau 180 giây. Không mở thêm cổng mạng. Mỗi người dùng chỉ truy cập QR của hồ sơ của mình; CSRF bắt buộc cho tạo/xóa phiên.

Cookie/IMEI/user agent được mã hóa AES-256-GCM trong instance/zalo; khóa auth.key giữ quyền 0600. Không trả cookie/token qua HTTP hoặc ghi lỗi thượng nguồn vào log. Sao lưu/thao tác instance phải bảo vệ cả khóa và ciphertext; không đưa lên GitHub. Xóa phiên khỏi ứng dụng chỉ xóa cục bộ, không thu hồi đăng nhập tại Zalo; thu hồi thiết bị từ Zalo trên điện thoại khi cần.

`Đã xác nhận đăng nhập` là kết quả ở thời điểm quét thành công, không phải kiểm tra phiên còn hiệu lực liên tục. Chưa có sử dụng/làm mới phiên để gửi tin.

Kiểm thử:

```sh
.venv/bin/python -m pytest -q
npm --prefix connector test
```

Kiểm thử nội bộ không thay cho đăng nhập Zalo thực. Môi trường Codex chặn Zalo, nên phải xác minh QR thật và quét thành công từ VPS triển khai. Nếu kết nối lỗi, ứng dụng hiển thị lỗi, không báo đăng nhập thành công.
