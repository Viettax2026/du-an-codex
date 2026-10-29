# Khôi phục mật khẩu bằng email — bản web

Luồng mặc định: **Quên mật khẩu? → nhập tài khoản và email → Gửi mã qua email → nhập mã 5 số và mật khẩu mới**. Mã dùng một lần, hết hạn sau 10 phút, tối đa 5 lần nhập sai cho một mã. Gửi lại mã thay thế mã cũ. Chờ ít nhất 60 giây giữa hai yêu cầu; tối đa 5 yêu cầu/tài khoản/giờ, 20 yêu cầu/địa chỉ mạng/giờ. Giới hạn nhập mã còn áp dụng chung theo tài khoản (10 lượt/giờ) và địa chỉ mạng (30 lượt/giờ), nên đổi IP hay xin nhiều mã không mở thêm lượt đoán. Khi bị giới hạn, cần chờ cửa sổ thời gian tương ứng kết thúc.

Email khi đăng ký được lưu ở trạng thái **chưa xác minh**, không được dùng để khôi phục ngay. Sau khi quản trị viên duyệt tài khoản, người dùng đăng nhập, vào **Bảo mật tài khoản**, xác nhận mật khẩu hiện tại và nhập mã gửi đến email đó. Tài khoản cũ như `admin` bổ sung email tại cùng màn hình. Không suy đoán email của tài khoản cũ từ tên đăng nhập. Đổi email cũng phải xác nhận mật khẩu và chứng minh quyền truy cập email mới; email cũ tiếp tục có hiệu lực đến khi xác minh thành công.

## Cập nhật VPS hiện tại

```bash
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/update.sh
```

Không cài lại VPS, không xóa database, không sửa dịch vụ quản lý key `/licenses`. Script cập nhật sao lưu `instance` trước khi nâng cấp.

## Bật gửi thư bằng Gmail

1. Dùng hộp Gmail mà bạn quản lý làm địa chỉ gửi. Bật **Xác minh 2 bước** của Google.
2. Vào <https://myaccount.google.com/apppasswords>, tạo **Mật khẩu ứng dụng** tên `ZaloFlow`. Nếu Google Workspace/chính sách tài khoản không cho phép tạo mật khẩu ứng dụng, cần quản trị viên cho phép hoặc dùng nhà cung cấp SMTP khác. Mật khẩu Gmail đăng nhập thông thường không dùng thay mật khẩu ứng dụng.
3. Chạy trên VPS, nhập thông tin trong các câu hỏi. Mật khẩu được nhập ẩn; không gửi mật khẩu vào chat, không đặt trên dòng lệnh:

```bash
cd /opt/zaloflow
runuser -u zaloflow -- .venv/bin/flask --app app:create_app configure-smtp
```

Các giá trị cho Gmail:

| Câu hỏi | Giá trị |
| --- | --- |
| Máy chủ SMTP | `smtp.gmail.com` |
| Bảo mật | `starttls` |
| Cổng | `587` |
| Tài khoản SMTP | Địa chỉ Gmail đầy đủ của bạn |
| Mật khẩu ứng dụng SMTP | Mật khẩu ứng dụng 16 ký tự do Google cấp, nhập hai lần |
| Email gửi | Cùng địa chỉ Gmail trên |

Có thể dùng `ssl`/cổng `465` nếu VPS không kết nối được cổng 587. Luôn kiểm tra chứng chỉ TLS; không hỗ trợ gửi mật khẩu SMTP qua kết nối không mã hóa.

4. Gửi thư thử đến hộp thư do bạn kiểm soát, thay địa chỉ bên dưới:

```bash
runuser -u zaloflow -- .venv/bin/flask --app app:create_app test-email --to EMAIL_CUA_BAN
```

Thông báo thành công nghĩa là máy chủ SMTP đã nhận thư; cần kiểm tra thực tế hộp thư và thư rác. Mã `00000` trong thư thử không tạo bản ghi khôi phục. Nếu lỗi, kiểm tra mật khẩu ứng dụng, quyền Gmail, địa chỉ gửi, DNS, kết nối TCP của VPS tới `smtp.gmail.com:587` hoặc `:465`. Không tắt kiểm tra TLS để sửa lỗi. Gmail có hạn mức gửi; đây không phải dịch vụ gửi thư số lượng lớn.

Lệnh lưu `instance/smtp.json` bằng ghi tệp thay thế nguyên tử, quyền `600`, không in mật khẩu. Web đọc cấu hình mỗi lần gửi, không cần khởi động lại chỉ để thay SMTP. Không chia sẻ tệp hoặc đưa vào Git. Sao lưu toàn bộ `instance` có chứa thông tin SMTP nên phải giữ riêng tư. Đổi/thu hồi mật khẩu ứng dụng trong Google nếu nghi bị lộ. Cấu hình nâng cao cũng nhận biến môi trường `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`; giá trị trong môi trường được ưu tiên hơn tệp.

Với bộ cài web trên VPS mới, dùng thư mục/người dùng dịch vụ tương ứng, mặc định `/opt/zaloflow-web` và `zaloflow-web`.

## Kiểm thử VPS trước khi đóng gói Windows

1. Tạo tài khoản thử với email do bạn kiểm soát, duyệt trong **Quản lý tài khoản**. Đăng nhập, mở **Bảo mật tài khoản**, gửi và nhập mã xác minh email.
2. Đăng nhập tài khoản thử ở trình duyệt thứ hai. Ở trình duyệt đầu, đăng xuất, chọn **Quên mật khẩu?**, nhập tài khoản/email đã xác minh, gửi mã. Kiểm tra nhận được đúng 5 số trong Gmail.
3. Nhập mã và mật khẩu mới. Kiểm tra mật khẩu mới đăng nhập được; mật khẩu cũ, mã đã dùng và phiên trình duyệt thứ hai không còn hiệu lực.
4. Thử nhập sai, mã quá hạn, gửi lại mã sau 60 giây và dùng mã cũ. Xác nhận các trường hợp này bị từ chối; dữ liệu công việc và tiến độ chiến dịch không bị thay đổi.
5. Báo kết quả VPS với phiên bản đang thử. Chỉ đóng gói Windows sau khi xác nhận VPS ổn định. Kiểm thử tự động/local không chứng minh Gmail của VPS đã gửi thành công.

Hiện triển khai gửi Gmail cho **bản web**. Không đưa `smtp.json` hay mật khẩu Gmail vào bộ cài Windows để phân phối. Bản Windows và web có database/tài khoản riêng; cấu hình Gmail trên VPS không tự áp dụng cho app cài trên máy khác. Khi chuẩn bị bản Windows, cần chọn cách cung cấp dịch vụ gửi mail riêng an toàn hoặc cấu hình do chủ máy quản lý, không đóng gói mật khẩu dùng chung.

## Bảo vệ dữ liệu và hỗ trợ

Chỉ lưu HMAC-SHA256 của mã 5 số, dùng khóa bí mật riêng của ứng dụng; không lưu mã gốc trong database, URL, cookie hay nhật ký. Gửi mã qua SMTP có TLS. Yêu cầu gửi trả cùng thông báo cho tài khoản không tồn tại, email chưa xác minh/không khớp, thời gian chờ và gửi thành công; không tiết lộ hộp thư của người khác. Khi SMTP lỗi, mã chưa gửi bị xóa và nhật ký chỉ có thông báo chung, không chứa phản hồi/credential của nhà cung cấp.

Đổi mật khẩu và tiêu thụ mã trong cùng giao dịch SQLite: hai yêu cầu đồng thời chỉ có một lần thành công. Thành công tăng phiên bản xác thực, vô hiệu hóa các phiên đăng nhập và mọi mã khôi phục cũ. Không tự duyệt/mở khóa tài khoản, không đổi khách hàng, chiến dịch, lịch, tiến độ, hạn mức, key hoặc phiên Zalo. Khi email đổi thành công, mã đặt lại gửi đến email cũ hết hiệu lực.

**Mã khôi phục dự phòng** và mã hỗ trợ tại [ACCOUNT-RECOVERY.md](ACCOUNT-RECOVERY.md) vẫn dùng được khi không truy cập email. Trong màn hình Quên mật khẩu mở **Chưa xác minh email hoặc không nhận được thư? → dùng mã khôi phục dự phòng**. Không cho phép đổi email bằng tên tài khoản đơn thuần; khi mất cả mật khẩu lẫn email, chủ VPS phải xác minh qua kênh liên lạc đã biết trước rồi cấp mã hỗ trợ.
