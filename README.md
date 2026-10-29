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

Ứng dụng phục vụ trên cổng 8000. Mở trang đăng ký để tạo tài khoản chờ duyệt; chủ máy chạy `.venv/bin/flask --app app:create_app grant-admin --username TEN_TAI_KHOAN` trong terminal khác để thiết lập quản trị viên đầu tiên, sau đó đăng nhập lại. Không có mật khẩu mặc định. Dữ liệu nằm trong `instance/zalo.sqlite3`; khóa phiên được tạo trong `instance/session.key`. Các tệp này bị Git bỏ qua và cần được bảo vệ, sao lưu khi triển khai.

## Quy trình

1. Đăng ký, được quản trị viên duyệt, rồi đăng nhập.
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

**Kênh Zalo cá nhân có gửi thủ công và gửi theo lịch đã bật.** Kênh OA/OAuth, webhook và ZNS chưa triển khai; số điện thoại không thay cho OA user ID.

Máy chủ Flask hiện tại phục vụ phát triển. Trước khi mở công khai cần máy chủ WSGI, HTTPS, `COOKIE_SECURE=1`, hạn chế tốc độ đăng nhập/đăng ký, kiểm soát đăng ký, quản lý khôi phục tài khoản, sao lưu và vận hành. Không đưa khóa hoặc token vào Git.

## Hướng sử dụng đã chọn: Zalo cá nhân

Mô phỏng chỉ lưu nội dung để kiểm tra. Có thể gửi thủ công qua bộ kết nối QR hoặc bật lịch tự động cho chiến dịch sau khi chọn tài khoản và kiểm tra data/nội dung. Lịch chỉ xử lý những người chưa có lần gửi trong chiến dịch.

## Giao diện theo ảnh tham chiếu

Trang `/campaigns` có bảng, bộ lọc, chi tiết và nhật ký bên phải. Chọn tên chiến dịch để xem chi tiết; nút Hành động mở màn hình xem trước/gửi thử. Có nút sao chép nội dung từng tin mô phỏng (cần trình duyệt cho phép clipboard). Hộp thoại `/accounts` cho phép lưu tên và nhóm tài khoản; Mở Zalo dẫn tới trang Zalo Web chính thức và không liên kết phiên đăng nhập về ứng dụng. Proxy chưa được hỗ trợ. Phiên bản mới có đăng nhập QR qua zca-js; xem mục bên dưới.

## Đăng nhập QR Zalo cá nhân (kết nối không chính thức)

Bộ kết nối dùng [zca-js 2.2.0](https://github.com/RFS-ADRENO/zca-js). Đây không phải API chính thức của Zalo; tác giả cảnh báo có thể bị khóa/hạn chế tài khoản. Người dùng phải xác nhận trước khi tạo QR. QR được lấy từ Zalo, không tự tạo QR giả. Chỉ ghi nhận thành công sau khi Zalo xác nhận. Có gửi theo lịch với các hành động đã chọn trong chiến dịch; chưa có listener hoặc quét data.

Cần Node.js >=18 và npm trên VPS. Cài phụ thuộc đã khóa phiên bản:

```sh
cd /opt/zaloflow
npm ci --prefix connector --ignore-scripts --no-audit --no-fund
```

Đặt `ZALO_QR_ENABLED=1` trong dịch vụ. Tệp deployment/zaloflow.service mới có thiết lập này. Tiến trình Node chỉ chạy khi có yêu cầu QR, tối đa 10 phiên đồng thời và tự dừng sau 180 giây. Không mở thêm cổng mạng. Mỗi người dùng chỉ truy cập QR của hồ sơ của mình; CSRF bắt buộc cho tạo/xóa phiên.

Cookie/IMEI/user agent được mã hóa AES-256-GCM trong instance/zalo; khóa auth.key giữ quyền 0600. Không trả cookie/token qua HTTP hoặc ghi lỗi thượng nguồn vào log. Sao lưu/thao tác instance phải bảo vệ cả khóa và ciphertext; không đưa lên GitHub. Xóa phiên khỏi ứng dụng chỉ xóa cục bộ, không thu hồi đăng nhập tại Zalo; thu hồi thiết bị từ Zalo trên điện thoại khi cần.

`Đã xác nhận đăng nhập` là kết quả ở thời điểm quét thành công, không phải kiểm tra phiên còn hiệu lực liên tục. Phiên được khôi phục khi tìm người nhận và gửi từng tin; nếu hết hiệu lực, đăng nhập QR lại.

Kiểm thử:

```sh
.venv/bin/python -m pytest -q
npm --prefix connector test
```

Kiểm thử nội bộ không thay cho đăng nhập Zalo thực. Môi trường Codex chặn Zalo, nên phải xác minh QR thật và quét thành công từ VPS triển khai. Nếu kết nối lỗi, ứng dụng hiển thị lỗi, không báo đăng nhập thành công.

## Gửi từng tin từ chiến dịch

Mở Chiến dịch → Hành động → Gửi tin qua tài khoản Zalo. Chọn tài khoản đã đăng nhập QR và khách hàng đồng ý nhận tin trong nhóm chiến dịch. Tìm người nhận theo số điện thoại, kiểm tra tên Zalo và nội dung cá nhân hóa, tích xác nhận rồi bấm Gửi tin thật. Tra cứu phụ thuộc cài đặt riêng tư; ứng dụng không tự kết bạn hoặc vượt hạn chế Zalo.

Nhật ký gửi thật riêng với deliveries mô phỏng, lưu trong message_sends. Thành công nghĩa là Zalo trả mã tin, không chứng minh đã đọc. Mỗi khách hàng có tối đa một lần gửi trong một chiến dịch; ràng buộc SQLite và cập nhật trạng thái trước khi gọi mạng chống gửi trùng. Bản xem trước chưa gửi có thể hủy để chọn lại tài khoản/người nhận. Gửi lỗi hoặc chưa xác định không tự thử lại. Nếu tiến trình bị dừng lúc gửi, trạng thái sending được giữ và cần kiểm tra hội thoại Zalo; không xóa lịch sử để gửi lại.

Bộ kết nối khôi phục phiên AES-GCM trong tiến trình Node, không trả cookie ra HTTP. Tìm người nhận/gửi có giới hạn chờ 40 giây, Python dừng tiến trình sau 45 giây. Có bộ chạy lịch riêng cho chiến dịch đã bật; chưa có listener hoặc quét dữ liệu. Các kiểm thử dùng dữ liệu giả lập API; môi trường Codex chặn Zalo nên phải xác minh gửi thật và tin đến trên VPS với người nhận thử đã đồng ý.

Cập nhật VPS đã có bộ kết nối: git pull --ff-only origin main rồi systemctl restart zaloflow. Cơ sở dữ liệu tự thêm bảng, không xóa dữ liệu hoặc phiên QR đã có.

Trang **Chiến dịch** có bảng gọn, menu trái thu gọn/mở rộng, bộ lọc thời gian/trạng thái/tài khoản/loại hành động/nhóm, khung chi tiết có thể đóng và bảng tiến trình riêng bên phải. Chọn tên hoặc dòng chiến dịch để mở chi tiết và nhật ký; tab Trợ lý hướng dẫn thao tác. Tiến độ gửi thật chỉ tăng khi mọi hành động đã chọn trong bản gửi được xác nhận thành công; lỗi/chưa xác định/chờ xác nhận không tính hoàn tất. Nhật ký mô phỏng có nhãn riêng. Cột ngày hiển thị ngày tạo và trạng thái lịch nếu đã bật. Dừng khóa các hành động mới; tiếp tục cho phép bộ chạy lịch xử lý tiếp trong khung giờ đã lưu.

Biểu mẫu tạo/sửa chiến dịch có thanh bước bên trái, bộ đếm các mục đã điền và dấu tích theo từng bước. Chọn bước để chuyển đến phần tương ứng; tiêu đề từng phần cho phép thu gọn/mở lại. Nếu ô bắt buộc nằm trong phần đang đóng, lưu biểu mẫu sẽ mở lại phần đó để nhập bổ sung.

## Tạo và sửa chiến dịch theo số điện thoại

Form có các phần cài đặt chung, hành động, nguồn data, danh sách SĐT, nội dung và lịch chạy. Có thể nhập tối đa 500 số Việt Nam, mỗi dòng một số; +84 được chuẩn hóa về 0, loại số trùng. Phải xác nhận đồng ý nhận tin trước khi lưu danh sách. Khách hàng hiện có được giữ nguyên tên/nhóm; người mới lưu tên tạm theo số điện thoại.

Danh sách riêng lưu trong campaign_contacts và chỉ áp dụng cho chiến dịch đó; khi để trống thì dùng nhóm khách hàng như trước. Tài khoản gửi đã chọn được lưu và chọn sẵn ở màn hình gửi thật. Lưu/sửa khi tắt lịch không tự gửi; bật lịch sẽ cho phép bộ chạy nền xử lý trong khung giờ đã đặt. Chỉ sửa được bản nháp chưa mô phỏng và chưa có bản xem trước/lần gửi thật để bảo toàn nhật ký. Cơ sở dữ liệu cũ tự thêm cột account_id và bảng liên kết, không xóa dữ liệu.

Có lựa chọn nhắn tin/kết bạn riêng, Media và lịch chạy theo ngày/tuần/tháng.


## Soạn lời mời kết bạn và tin nhắn

Hành động “Nhắn tin, kết bạn đến SĐT” có hai ô lựa chọn độc lập. Có thể chỉ nhắn tin, chỉ kết bạn hoặc cả hai. Lời mời tối đa 150 ký tự, hỗ trợ {{name}} và xem trước. Giới hạn kiểm tra cả sau khi chèn tên thật.

Trong chế độ thủ công, tìm người nhận và tạo bản xem trước không gửi hành động nào. Người dùng xác nhận riêng “Gửi lời mời kết bạn” và “Gửi tin thật”; không tự gửi tin sau lời mời hoặc chờ chấp nhận tự động. Lời mời được lưu với friend_state riêng; tiếp nhận lời mời không có nghĩa đã chấp nhận. Double click, kết quả chưa xác định và khởi động lại không tự gửi lại lời mời. Bản xem trước có bất kỳ hành động đã xử lý không thể xóa để gửi lại.

zca-js.sendFriendRequest có thể bị Zalo từ chối nếu đã là bạn bè hoặc bị chặn. SDK lưu ý yêu cầu kết bạn có thể được xử lý như chấp nhận lời mời đã đến; ứng dụng không tự suy diễn trạng thái bạn bè. Kiểm thử API giả lập không xác minh gửi lời mời thật trên VPS. Đổi tên gợi nhớ, media và giới hạn hành động đã được bổ sung ở các bản sau (xem bên dưới). Gắn tag Zalo chưa triển khai. Lịch tự động xử lý các hành động đã chọn, không chờ người nhận chấp nhận kết bạn.

## Cá nhân hóa lời mời và tin nhắn

Nút Cá nhân hóa chèn token tại con trỏ vào từng nội dung, giữ {{name}} tương thích. Token hỗ trợ: #{FULL_NAME} (tên hiển thị Zalo), #{ORIGINAL_NAME} (tên gốc Zalo), #{INPUT_FULLNAME} (tên khách hàng lưu trong ứng dụng), #{PHONE}, #{EMAIL}, #{INFO1}…#{INFO5}, #{SEX{anh-chị-anh/chị}}, #{TODAY(DD/MM/YYYY)}, #{TODAY(DD-MM-YYYY)} và #{TODAY(YYYY-MM-DD)}.

Giới tính dùng trường Zalo trả về: 0 nam, 1 nữ, không rõ dùng lựa chọn thứ ba; không suy đoán theo tên. Tên Zalo chỉ có sau khi tìm người nhận. Ngày lấy lúc tạo bản xem trước người nhận theo Asia/Bangkok (UTC+7); bản đã xác nhận giữ nguyên ngày/nội dung, không tự đổi lúc gửi.

Xem trước trong form dùng dữ liệu mẫu được ghi rõ. Xem trước thực dùng dữ liệu khách hàng và kết quả tìm Zalo. Thiếu thông tin hoặc cú pháp không hợp lệ sẽ chặn tạo bản gửi thật, không gửi nguyên token. Thay thế một lần, không diễn giải token nằm trong dữ liệu khách hàng. Kiểm tra độ dài sau cá nhân hóa: lời mời 150 ký tự, tin nhắn 2000 ký tự.

CSV UTF-8 xuất từ Excel hỗ trợ cột email, info1…info5 ngoài name/phone/tag/zalo_id/consent. Số trùng vẫn được bỏ qua khi import; chỉnh dữ liệu khách hàng đã có bằng liên kết Thông tin cá nhân hóa trong danh sách. Quyền sở hữu và CSRF áp dụng cho sửa. Nội dung các bản xem trước đã có không tự thay đổi sau khi sửa thông tin khách hàng.

### Đổi tên gợi nhớ Zalo
Trong tùy chọn chiến dịch, bật **Kiêm đổi tên gợi nhớ trên Zalo** và nhập mẫu
`#{FULL_NAME} - #{PHONE}`. Mẫu hỗ trợ cùng các trường cá nhân hóa của tin nhắn.
Sau khi tìm người nhận, tên được chèn dữ liệu và cố định trong bản xem trước;
xác nhận **Đổi tên gợi nhớ** để gọi API Zalo. Đây là tên riêng trong tài khoản gửi,
không phải tên hồ sơ người nhận. API có thể từ chối người chưa là bạn bè.
Kết quả được ghi riêng với tin nhắn và lời mời; kết quả không rõ sẽ không tự thử lại.
Các chiến dịch cũ mặc định tắt tính năng này. Cần tạo chiến dịch mới hoặc sửa bản nháp
chưa có bản xem trước để bật. Chưa tự chạy hành động theo lịch.

## Đăng nhập bằng tài khoản

Đăng ký bằng tên tài khoản từ 3–64 ký tự: chữ không dấu, số, dấu chấm, gạch dưới và gạch ngang; không phân biệt chữ hoa/thường. Tài khoản mới cần nhập email để khôi phục mật khẩu, sau khi được duyệt phải xác minh email trong Bảo mật tài khoản. Cơ sở dữ liệu cũ tự chuyển định danh email sang tài khoản và giữ nguyên mật khẩu, dữ liệu: người dùng cũ vẫn nhập nguyên email cũ vào ô Tài khoản, bổ sung/xác minh email khôi phục riêng.

Tài khoản cũ `lienhe.viettaxco@gmail.com` được đổi thành `admin` khi khởi động phiên bản mới, giữ nguyên mật khẩu và dữ liệu. Nếu tên `admin` đã tồn tại, ứng dụng báo lỗi và không ghi đè tài khoản. Các tài khoản cũ khác giữ nguyên định danh.

## Đặt lại mật khẩu admin trên VPS

Chạy `sudo -u zaloflow /opt/zaloflow/.venv/bin/flask --app app:create_app reset-admin` trong `/opt/zaloflow`. Nhập mật khẩu mới hai lần khi được hỏi (không hiển thị khi gõ), từ 10–256 ký tự. Lệnh tạo admin nếu chưa có, hoặc đổi mật khẩu trên chính tài khoản admin hiện có, giữ nguyên dữ liệu. Không truyền mật khẩu trong dòng lệnh.

## Menu Hành động chiến dịch

Đã có đủ 12 mục theo ảnh tham chiếu:

- **Dừng / tiếp tục chiến dịch**: khóa tạo bản xem trước, mô phỏng và gửi/kết bạn/đổi tên tiếp theo. Không thu hồi hành động đã chuyển đến Zalo và không tự chạy lại khi tiếp tục.
- **Sửa**: sửa cấu hình chung của bản nháp chưa có bản xem trước/lần gửi. Chiến dịch đã xử lý dùng các mục cập nhật riêng để giữ lịch sử.
- **Nhân bản**: tạo bản nháp mới với cấu hình, tài khoản, media, giới hạn và danh sách riêng; không chép lần gửi/nhật ký. Có màn hình kiểm tra tên trước khi tạo; lưu không gọi Zalo.
- **Lấy ID chiến dịch**: sao chép ID, có hiển thị ID nếu clipboard bị chặn.
- **Cập nhật giới hạn gửi**: hạn mức theo ngày Việt Nam hoặc 24 giờ gần nhất; hạn mức nhắn tin/kết bạn trong khung phút tùy chọn và khoảng cách tối thiểu giữa các hành động của chiến dịch. 0 là không giới hạn. Một lần xử lý nội dung + media cho một người là một hành động; tính cả thất bại/đang xử lý/chưa xác định, không tính bản xem trước hoặc mô phỏng. Khóa SQLite kiểm tra và ghi nhận trước gọi mạng, chống vượt hạn mức khi mở nhiều tab. Lần gửi cũ được đưa vào bộ đếm theo thời gian tạo bản ghi, do bản cũ chưa lưu riêng thời gian bắt đầu gửi.
- **Cập nhật nội dung + media**: hỗ trợ một tệp JPG/JPEG, PNG, WEBP, PDF hoặc MP4 tối đa 10 MB. Kiểm tra định dạng và ảnh tối đa 25 triệu điểm ảnh. Media lưu riêng trong instance/media, chỉ chủ tài khoản truy cập; chỉ gửi sau xác nhận. Bản xem trước cũ giữ nguyên nội dung, lời mời và media, kể cả khi chiến dịch đổi/gỡ tệp. PDF/MP4 được SDK gửi dưới dạng tệp đính kèm; chữ và tệp có thể là hai tin trong Zalo. Chỉ báo tiếp nhận khi có mã xác nhận của tệp; nếu chỉ chữ thành công thì kết quả chưa xác định, không tự gửi lại. Chưa hỗ trợ album nhiều tệp hoặc tải media từ URL.
- **Thêm data**: bổ sung số điện thoại hoặc CSV UTF-8 có phone, tùy chọn name/email/info1…info5; tổng danh sách tối đa 10.000 khách hàng khi thêm từ nhóm; nhập tay/tệp tối đa 500 số mỗi lần, CSV tối đa 2 MB. Chuẩn hóa +84, loại số trùng, giữ thông tin khách hàng đã có và yêu cầu xác nhận đồng ý. Nhóm hiện tại được chốt thành danh sách riêng trước khi bổ sung; không thay đổi lần gửi cũ.
- **Xem báo cáo chi tiết**: thống kê theo trạng thái thực, chi tiết nội dung/media đã chốt, nhật ký mô phỏng riêng và xuất CSV gửi thật. CSV bảo vệ các ô bắt đầu bằng ký tự công thức bảng tính. Không suy diễn đã đọc hoặc đã kết bạn từ phản hồi tiếp nhận.
- **Đăng nhập lại Zalo**: mở đúng hồ sơ đã chọn trong chiến dịch; tài khoản đã kết nối có nút đăng nhập lại bằng QR. Nếu chưa chọn mặc định thì mở danh sách để tự chọn. Vẫn cần xác nhận dùng kết nối không chính thức và quét QR.
- **Thông tin tài khoản**: tên/nhóm/trạng thái hồ sơ mặc định và các tài khoản đã dùng trong bản xem trước/gửi. Không hiển thị cookie, khóa hoặc token.
- **Lịch sử chạy**: nhật ký thao tác và bắt đầu/kết quả từng hành động, có phân trang. Lịch sử chỉ ghi từ bản cập nhật này; lần gửi trước đó vẫn có trong báo cáo.
- **Xóa**: xác nhận rồi đưa vào lưu trữ, dừng mọi hành động tiếp theo và ẩn khỏi danh sách hoạt động. Bộ lọc **Đã xóa** vẫn mở được báo cáo/lịch sử. Không xóa khách hàng, phiên QR, media hoặc nhật ký để tránh mất dữ liệu và gửi trùng.

Các chức năng trên phục vụ quy trình xác nhận từng người nhận. Chưa có bộ chạy hàng loạt, lịch chạy tự động hoặc xác nhận đã đọc. Kiểm thử API giả lập và trình duyệt không thay thế kiểm tra gửi thật từ VPS với người nhận thử.

### Cập nhật VPS cho phiên bản menu Hành động

Trong terminal root của VPS đã triển khai tại /opt/zaloflow:

```sh
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/update.sh
```

Script cài thêm Pillow, sao lưu toàn bộ instance khi tạm dừng riêng dịch vụ ZaloFlow vào thư mục root-only /var/backups/zaloflow/update-*, khởi động ứng dụng để nâng cấp SQLite và kiểm tra /login nội bộ. Script chỉ sửa client_max_body_size của tệp Nginx cskh.viettaxco.com lên 12m, giữ cấu hình HTTPS và từ chối tự sửa nếu tệp chứa tên miền khác. Các dịch vụ website khác không bị dừng. Bản sao lưu chứa dữ liệu, khóa và phiên Zalo; bảo vệ thư mục đó. Script không tự khôi phục dữ liệu nếu nâng cấp lỗi; giữ bản sao để kiểm tra trước khi phục hồi.

Nếu đang dùng đường dẫn triển khai hoặc Nginx khác, dùng hướng dẫn deployment/DEPLOY.md để điều chỉnh thủ công. Không sao chép cấu hình HTTP mẫu đè lên cấu hình HTTPS đang hoạt động.

## Chọn, sửa và xóa khách hàng

Trang **Khách hàng** có ô chọn từng dòng hoặc chọn toàn bộ kết quả đang hiển thị sau khi tìm kiếm. Thanh công cụ hiển thị số đã chọn, nút **Sửa đã chọn** và **Xóa đã chọn**; mỗi dòng cũng có **Sửa/Xóa** riêng. Tối đa 10.000 khách hàng mỗi thao tác, danh sách ID được kiểm tra quyền sở hữu và CSRF phía máy chủ.

**Sửa đã chọn** mở màn hình xem lại và cho đổi nhóm gốc hoặc đặt đồng ý/tắt nhận tin cho các hồ sơ đã chọn; bỏ trống trường để giữ nguyên. Sửa từng người vẫn có thông tin tên, email và Info1…Info5. **Xóa đã chọn** mở màn hình xem lại và cần đánh dấu xác nhận trước khi xóa. Xóa dùng lưu trữ hồ sơ: ẩn khỏi Khách hàng, mọi nhóm data và người nhận chiến dịch, đồng thời tắt nhận tin; các lần gửi, nguồn data và lịch sử cũ được giữ lại. Bản xem trước chưa gửi của khách đã xóa bị chặn. Nhập/thêm lại rõ ràng cùng số điện thoại khôi phục hồ sơ cũ thay vì tạo trùng; thông tin và lịch sử được giữ lại.

## Loại trừ gửi cho khách hàng

Trong **Thêm/Sửa chiến dịch → Tùy chọn hành động**, thẻ **Loại trừ gửi cho khách hàng** cho phép chọn một nhóm điều kiện và tối đa 20 danh sách số điện thoại/Zalo ID. Dấu **+** tạo nhóm điều kiện dùng lại; **Quản lý danh sách** tạo hoặc sửa danh sách ngay trong hộp thoại, giữ nguyên nội dung chiến dịch đang điền. Có thể cập nhật lựa chọn sau khi đã tạo bản xem trước qua **Hành động → Loại trừ khách hàng**.

- Khách hàng consent=false luôn bị chặn, không thể tắt. Nhập lại hoặc bổ sung số đã có vào chiến dịch giữ nguyên trạng thái đồng ý cũ; chỉ khách mới được ghi nhận theo xác nhận khi nhập. Có thể xác nhận lại cho hồ sơ cũ bằng cách chọn đồng ý khi nhập vào nhóm, xác nhận nhóm trong hộp Thêm bằng nhóm hoặc sửa trạng thái trong Khách hàng.
- Nhóm điều kiện khớp **ít nhất một** trong các điều kiện đã chọn: Zalo đã tiếp nhận tin, tiếp nhận lời mời hoặc đổi tên gợi nhớ ở **chiến dịch khác**, hoặc thuộc một nhóm data. Nhật ký mô phỏng và trạng thái chưa xác định không tính. Bỏ qua lịch sử của chính chiến dịch hiện tại để nhắn tin xong vẫn có thể xác nhận các hành động khác đã chọn. Điều kiện nhóm data theo thành viên hiện tại, kể cả khi nhóm được đổi tên.
- Mỗi danh sách hỗ trợ tối đa 500 số Việt Nam và 500 Zalo ID dạng số; gộp trùng và chuẩn hóa +84. Đây là danh sách do người dùng nhập, chưa tự lấy danh sách bạn bè từ Zalo. Zalo ID được so với ID đã lưu/bản xem trước; nếu chưa biết ID thì kiểm tra ngay sau bước tìm người nhận. Vì vậy mô phỏng theo số điện thoại chưa biết UID có thể vẫn có dòng đó, nhưng gửi thật bị chặn sau khi tìm ra UID thuộc danh sách.
- Lựa chọn lưu theo chiến dịch; nhân bản giữ cùng các nhóm/danh sách loại trừ. Sửa danh sách dùng chung áp dụng cho lần xác nhận tiếp theo ở mọi chiến dịch đang chọn nó. Có thể bỏ chọn để gỡ loại trừ tùy chọn; quy tắc consent mặc định vẫn giữ nguyên. Bổ sung data giữ nguyên các thành viên đang bị loại trừ trong danh sách nền, không xóa khách hàng.

Bộ lọc dùng chung cho người nhận, số lượng trên trang Chiến dịch, mô phỏng và gửi thật. Mọi hành động nhắn tin/kết bạn/đổi tên kiểm tra lại điều kiện trong khóa giao dịch trước khi gửi. Nút gửi của bản xem trước không còn đủ điều kiện bị vô hiệu hóa; lịch sử cũ được giữ lại. Thay đổi không thu hồi hành động đã bắt đầu gửi. Tạo nhóm/danh sách và lưu cấu hình không gọi Zalo; dữ liệu chỉ thuộc tài khoản đăng nhập.

## API tích hợp riêng của ZaloFlow

Mở menu **API tích hợp** (`/integrations`) để tạo khóa có thời hạn 1–365 ngày và chọn quyền `data:read`, `data:write`, `media:read`, `media:write`. Mặc định chỉ chọn quyền đọc; mỗi tài khoản có tối đa 10 khóa còn hiệu lực. Khóa chỉ hiện đầy đủ khi tạo, cơ sở dữ liệu chỉ lưu SHA-256; có thể thu hồi ngay tại màn hình này. Gửi `Authorization: Bearer <khóa>` cho API; cookie đăng nhập và `username` không thay thế khóa hoặc chọn chủ dữ liệu. Tệp OpenAPI 3.0.3 tại `/integrations/openapi.json` có thể nhập vào Postman. API này chạy trên chính ZaloFlow, không gọi dịch vụ akaAgent.

| Phương thức | Đường dẫn | Chức năng |
| --- | --- | --- |
| GET / POST | `/api/v1/data-groups` | Danh sách / tạo nhóm data |
| GET / POST | `/api/v1/data-groups/{group_id}/members` | Danh sách / thêm data theo SĐT |
| GET / POST | `/api/v1/media-groups` | Danh sách / tạo nhóm Media |
| GET / POST | `/api/v1/media` | Danh sách / tải lên một tệp |
| GET | `/api/v1/media/{media_id}/file` | Tải tệp về với cùng khóa API |
| PATCH / DELETE | `/api/v1/media/{media_id}` | Chuyển nhóm / xóa Media |

Danh sách dùng `page`, `per_page` (mặc định 50, tối đa 100). API nhóm hỗ trợ `search`; Media hỗ trợ `q`, `kind` và `group_id`. Phản hồi JSON có `status`, `error_code`, `message`, `data`; API tải tệp trả nội dung tệp. Lỗi trả HTTP 400/401/403/404/409/413/415 theo tài liệu. CSRF vẫn áp dụng cho biểu mẫu web; API dùng bearer độc lập với phiên web.

Thêm data bằng JSON như sau, thay ID trong đường dẫn bằng ID nhóm lấy từ danh sách:

```json
{
  "data": [{"name": "Khách hàng mẫu", "phone": "0901234567", "info1": "CRM"}],
  "source_name": "CRM nội bộ",
  "consent": true,
  "dry_run": true
}
```

Tối đa 500 dòng/yêu cầu, dùng cùng quy tắc chuẩn hóa số Việt Nam như nhập Excel. Mỗi dòng cần một SĐT; API chưa hỗ trợ nhập chỉ email hoặc nhóm UID. Các trường tùy chọn gồm `name`, `zalo_id`, `email`, `info1`…`info5`. Dòng sai được bỏ qua, trả lý do (tối đa 100 lỗi chi tiết), các số trùng giữ dòng đầu. Kết quả có `received_count`, `added_count`, `existing_count`, `invalid_count`; `added_count` tính số mới thuộc nhóm, kể cả hồ sơ đã có ở nhóm khác. Hồ sơ cũ giữ nguyên tên/thông tin và nhóm gốc. Bỏ trường consent giữ trạng thái cũ; gửi rõ `consent:true` cập nhật cả khách đã có sang đồng ý. Khách mới mặc định consent=true; gửi false nếu không bật nhận tin. Nhập thật (`dry_run:false`) ghi nguồn **Nhập qua API** và tên nguồn, xuất hiện ngay trong nhóm và lịch sử nguồn trên web.

Header tùy chọn `Idempotency-Key` (1–128 ký tự chữ/số hoặc `_.:-`) giúp thử lại lần nhập thật với cùng khóa API, nhóm và nội dung mà không ghi thêm lô/nguồn. Tái sử dụng mã với nội dung khác trả 409. Chạy thử không lưu mã và không thay đổi khách hàng, nhóm hoặc nguồn. Mỗi lần nhập khác dùng mã mới. Dữ liệu và kết quả mã nhập được lưu cùng transaction, gồm cả khi có yêu cầu đồng thời.

Media dùng multipart `file`, tùy chọn `group_id`; giữ giới hạn/kiểm tra định dạng của thư viện. PATCH nhận `{"group_id":123}` hoặc null để bỏ nhóm. DELETE cần `{"confirm_delete":true}`; tệp đang dùng trong chiến dịch/lịch sử gửi chỉ ẩn khỏi thư viện, trả `retained_for_campaigns:true`. Các đường dẫn tải tệp API vẫn yêu cầu quyền `media:read`.

## Thư viện Media

Menu **Media** quản lý ảnh JPG/JPEG, PNG, WEBP, video MP4 và tài liệu PDF, tối đa 10 MB/tệp và 1.000 tệp/tài khoản. Có nhóm riêng, tải nhiều tệp lần lượt, kéo thả, dán ảnh bằng Ctrl+V, lọc tên/đuôi/ngày, sắp xếp, xem dạng lưới/danh sách và xem trước. Nút Dán ảnh dùng quyền clipboard của trình duyệt; khi không được cấp quyền có thể dùng Ctrl+V hoặc chọn tệp.

Tệp lưu trong bộ lưu trữ riêng trên máy chủ (mặc định `instance/media`), chỉ chủ tài khoản truy cập; chưa kết nối Cloudflare R2. Chọn tệp đã tải tại **Thêm/Sửa chiến dịch → Nội dung tin nhắn** hoặc **Hành động → Cập nhật nội dung + media** để dùng cho chiến dịch. Xóa tệp chưa dùng sẽ xóa khỏi ổ đĩa sau xác nhận; tệp đã gắn chiến dịch hoặc lịch sử gửi chỉ được ẩn khỏi thư viện và được giữ lại để bảo toàn nội dung đã chốt. Các tệp được giữ lại vẫn tính vào dung lượng và hạn mức.

Data mới thêm qua biểu mẫu Khách hàng, nhập nhóm TXT/CSV/Excel hoặc API mặc định bật nhận tin. Các ô chọn đồng ý trong biểu mẫu được tích sẵn. Bỏ tích để tạo khách chưa đồng ý; CSV ở mục Khách hàng có thể đặt `consent=0`, API gửi `consent:false`. Nếu không xác nhận thêm thì hồ sơ cũ giữ trạng thái nhận tin. Tích đồng ý khi nhập vào nhóm sẽ cập nhật cả những số đã có trong lần nhập đó; việc cập nhật không gửi tin.

## Nhóm data và nguồn data chiến dịch

Mục **Nhóm data** (`/data-groups`) quản lý các nhóm khách hàng hiện có và cho phép tạo nhóm mới, tìm theo tên/UID/SĐT, nhập trực tiếp hoặc tải TXT, CSV UTF-8 và Excel `.xlsx`/`.xls`. Mỗi khách hàng có một nhóm gốc theo trường nhóm hiện tại và có thể xuất hiện trong các nhóm nhân bản thông qua liên kết danh sách. Nhập số đã có sẽ liên kết hồ sơ vào nhóm đích nếu chưa thuộc nhóm; giữ nguyên thông tin và nhóm gốc. Tích đồng ý sẽ xác nhận lại trạng thái nhận tin của các hồ sơ trong lần nhập; bỏ tích không tự thu hồi trạng thái của hồ sơ đã có. Số đã thuộc nhóm đích không được thêm trùng. Có thể lưu khách hàng chưa đồng ý nhận tin; chiến dịch chỉ lấy người đã đồng ý.

Trong tạo/sửa chiến dịch, **Cách thêm data vào chiến dịch** có hai lựa chọn:

- **Thêm trực tiếp:** nhập số, tải tệp hoặc **Thêm bằng nhóm**. Nút Thêm bằng nhóm mở hộp thoại tìm kiếm/tải lại nhóm, hiển thị số thành viên và số khách đã đồng ý. **Chọn nhóm** lấy data hiện tại vào bảng xem trước (50 dòng/trang), gộp trùng khi chọn lại hoặc chọn các nhóm chồng nhau. Danh sách riêng chốt ngay lúc chọn bằng ID hồ sơ; khách phát sinh trong nhóm sau đó không tự được thêm, kể cả trước lúc bấm Lưu. Tối đa 10.000 khách hàng/chiến dịch từ nhóm, nhập tay/tệp tối đa 500 số mỗi lần. Có thể bỏ từng dòng hoặc **Xóa hết** (có xác nhận). Khi sửa danh sách trên 500 khách, data vẫn ở dạng danh sách riêng, không chuyển thành hàng nghìn dòng nhập tay.
- **Chọn nhóm data để chạy:** chọn một nhóm, danh sách người nhận theo khách hàng đã đồng ý của nhóm tại thời điểm xử lý. Thay đổi nhóm sẽ ảnh hưởng danh sách chưa xử lý; các bản xem trước và nhật ký đã có vẫn được giữ nguyên.

Menu Hành động → **Thêm data** cũng hỗ trợ TXT/CSV/Excel và thêm bằng nhóm. Việc bổ sung chuyển danh sách hiện tại thành danh sách riêng, giữ lịch sử và chống gửi trùng như trước. Lưu data không gọi Zalo.

Nhóm chưa ghi nhận đồng ý vẫn hiển thị trong hộp thoại. Chọn nhóm rồi bấm **Xác nhận đồng ý nhận tin cho … khách trong nhóm** để cập nhật ngay những hồ sơ đang có consent=0; số lượng được tải lại và nút Chọn nhóm được mở khi đủ điều kiện. Thao tác này chỉ thay đổi trạng thái của nhóm thuộc tài khoản đăng nhập, không gửi tin và không khôi phục khách đã xóa. Nhóm vượt 10.000 khách đã đồng ý được báo rõ, không tự cắt bớt. Dữ liệu từ nhóm dùng trạng thái đồng ý đã ghi nhận, không tự bật lại consent; nhập tay/tệp vẫn cần xác nhận. Mọi lựa chọn ID được kiểm tra lại quyền sở hữu khi lưu. **Chọn nhóm data để chạy** vẫn là chế độ riêng theo nhóm động, không bị đổi thành bản sao.

Tệp tối đa 2 MB và 500 dòng mỗi lần nhập. TXT mỗi dòng một số. CSV/Excel cần cột `phone`, tùy chọn `name,zalo_id,email,info1,info2,info3,info4,info5`. Có tệp mẫu ở `static/data-template.csv`. Excel dùng định dạng văn bản cho cột số điện thoại; hỗ trợ cả `.xlsx` và `.xls`. Chưa có nguồn dữ liệu quét để nhập.

Cập nhật VPS theo quy trình `deployment/update.sh` hiện có để cài thêm `openpyxl==3.1.5` và `xlrd==2.0.2` và khởi động lại dịch vụ. Bảng nhóm được tạo bổ sung khi khởi động, không xóa dữ liệu cũ.

Tab **Từ template Excel ZaloFlow** hỗ trợ chọn hoặc kéo thả một tệp, tự đọc và xem trước trước khi lưu. Có thể dùng tiêu đề `name,phone,info1…info5` hoặc `Tên,Số điện thoại,Info 1…Info 5`. Tab **File Excel/CSV của khách hàng** cho phép tự chọn cột và bỏ dòng tiêu đề. Chuẩn hóa/xem trước chưa ghi dữ liệu; chỉ nút **Thêm vào nhóm** mới lưu.

### Nhân bản nhóm data

Xóa nhóm sẽ xóa vĩnh viễn nhóm và liên kết thành viên, cho phép tạo lại cùng tên với ID mới. Hồ sơ khách hàng, thành viên ở nhóm khác và lịch sử nguồn vẫn được giữ nguyên. Khách hàng chỉ thuộc nhóm đã xóa trở thành chưa có nhóm gốc. Chiến dịch dùng nhóm động được chốt thành danh sách riêng tại thời điểm xóa; điều kiện loại trừ dùng nhóm giữ danh sách khách hàng hiện tại. Nhóm tạo lại không làm thay đổi chiến dịch hoặc loại trừ cũ. Khi cập nhật, các nhóm đã bị ẩn ở phiên bản trước cũng được xử lý theo cách này.

Biểu tượng hai ô vuông cạnh nhóm mở màn hình **Nhân bản nhóm data**, cho phép đặt tên mới. Nhóm sao chép có ID riêng, giữ màu, loại data và danh sách hiện tại, bao gồm khách hàng chưa đồng ý nhận tin. Hai nhóm dùng chung hồ sơ khách hàng; không tạo thêm số điện thoại trùng hoặc đổi nhóm gốc. Thêm khách hàng mới vào nhóm gốc sau đó không tự bổ sung vào bản sao. Nhóm sao chép dùng được trong chiến dịch, bộ lọc tài khoản và xuất CSV; chiến dịch chỉ lấy khách hàng đã đồng ý nhận tin. Không sao chép chiến dịch hoặc nhật ký gửi. Nút sao chép nhỏ tại huy hiệu ID vẫn chép ID vào clipboard.

### Lịch sử nguồn data

Bấm cột **Nguồn data** để xem tệp nguồn, thời điểm ghi nhận (Asia/Bangkok), ID danh sách và ID lô nhập. Nguồn đang dùng được giữ lại khi nhập tệp khác; lần nhập sau được ghi thêm vào lịch sử. Data cũ chưa có nguồn có thể nhập lại tệp gốc vào cùng nhóm để bổ sung nguồn mà không tạo trùng hoặc đổi thông tin/đồng ý nhận tin của khách hàng. Không tự suy đoán tên tệp, ngày nhập hoặc ID lô từ dữ liệu cũ.

## Soạn nội dung chiến dịch

Mục **Nội dung tin nhắn** dùng chung cho các tài khoản trong chiến dịch, có chế độ văn bản thường hoặc định dạng: đậm, nghiêng, gạch chân/gạch ngang, tiêu đề, danh sách, trích dẫn, thụt lề, chèn đường dẫn và hoàn tác. **Cá nhân hóa** chèn thông tin khách hàng; **Xem trước** dùng dữ liệu mẫu Lan. Nhập các biến thể thủ công bằng dấu `|` ngoài cùng; dùng `\|` để giữ dấu gạch đứng trong tin nhắn. Tối đa 20 biến thể, mỗi biến thể tối đa 2.000 đơn vị ký tự UTF-16 theo Zalo; emoji có thể tính hai đơn vị. Không tự sinh nội dung. Xem trước trong ô soạn hiển thị tất cả biến thể.

Mỗi lần tạo bản xem trước cho người nhận mới chọn biến thể tiếp theo theo thứ tự 1 → 2 → … → 1. Bộ đếm riêng của chiến dịch được lưu trong SQLite cùng bản xem trước, dùng chung giữa các tài khoản gửi; tải lại trang, gửi lại biểu mẫu trùng hoặc lỗi tạo bản xem trước không làm nhảy lượt. Gửi dùng đúng nội dung đã chốt; hủy bản xem trước không hoàn lại lượt để tránh đổi nội dung các bản còn lại. Mô phỏng xoay lần lượt từ biến thể 1, không tăng bộ đếm gửi thật. Sửa nội dung/định dạng đặt lượt mới về 1; đổi riêng tệp hoặc lời mời giữ lượt. Bản sao chiến dịch bắt đầu ở biến thể 1.

Trong mỗi nội dung, cú pháp `{a|b|c}` chọn ngẫu nhiên một cách viết bạn đã nhập. Ví dụ `{Chào|Xin chào} {{name}}` có thể thành “Chào Lan” hoặc “Xin chào Lan”. Có thể dùng nhiều nhóm và lồng tối đa 10 cấp; tối đa 100 nhóm và 20 lựa chọn mỗi nhóm trong một biến thể. Chọn ngẫu nhiên khi chuẩn bị người nhận, lưu kết quả cùng định dạng vào bản xem trước; thao tác gửi thủ công và chạy theo lịch dùng nguyên kết quả này, không chọn lại khi gửi hoặc tải lại. Bản xem trước mẫu có thể khác giữa các lần xem. Dữ liệu chèn từ tên/Info và cú pháp cá nhân hóa không được xử lý thành nhóm ngẫu nhiên. Viết `\{a\|b\}` để gửi nguyên văn `{a|b}`. Giới hạn 2.000 UTF-16 được kiểm tra theo lựa chọn dài nhất, và kiểm tra lại sau cá nhân hóa. Nhóm chưa đóng hoặc quá giới hạn được báo lỗi trước khi lưu; kết quả rỗng không được chuẩn bị để gửi.

**Lưu mẫu** lưu nội dung và định dạng theo tên/nhóm riêng của tài khoản. **Chọn mẫu / Nhóm mẫu nội dung** thay nội dung đang soạn sau xác nhận; **Quản lý mẫu** cho chọn để sửa rồi lưu đè hoặc xóa. Mẫu không chứa tệp đính kèm. Chọn một tệp bằng **Chọn file** hoặc **Từ thư viện Media**, xem trước bằng tên tệp và gỡ bằng biểu tượng thùng rác. Gỡ chỉ bỏ tệp khỏi chiến dịch; không xóa thư viện.

Định dạng được làm sạch phía máy chủ, chuyển sang style ranges của SDK Zalo sau khi cá nhân hóa và lưu cùng bản xem trước/nhật ký. Sửa nội dung sau đó không đổi chữ, định dạng hoặc media của bản xem trước cũ. Các API `/message-templates` và `/composer/*` phục vụ giao diện web, cần phiên đăng nhập và CSRF cho POST; không phải Public API.

Khi có ảnh JPG/PNG/WEBP và nội dung định dạng, bộ kết nối gửi ảnh không chú thích trước rồi gửi tin chữ với định dạng đã chốt ngay sau đó. Thư viện zca-js 2.2.0 không chuyển style ranges vào chú thích ảnh, nên ghép chữ vào ảnh sẽ mất in đậm/nghiêng. Chỉ báo thành công khi cả ảnh và chữ đều có mã xác nhận; thiếu xác nhận hoặc lỗi giữa hai phần được đánh dấu chưa xác định và không tự gửi lại. Hai phần vẫn thuộc một lượt gửi cho một khách hàng trong hạn mức của chiến dịch. Ảnh kèm văn bản thường vẫn dùng chú thích ảnh; PDF/MP4 dùng đường gửi chữ và tệp của SDK.

## Lịch chạy chiến dịch (UTC+7)

Mục **6. Lịch chạy** có trong Thêm, Sửa, Nhân bản chiến dịch. Chiến dịch cũ và bản sao mặc định tắt lịch; chọn **Bật lịch chạy tự động** và tài khoản gửi rồi lưu để cho phép xử lý tự động. **Hành động → Lịch chạy** cập nhật lịch/tài khoản ngay cả khi chiến dịch đã có nhật ký. Bộ chạy dùng giờ Việt Nam (`Asia/Ho_Chi_Minh`), độc lập múi giờ VPS/trình duyệt.

Giờ chạy và giờ dừng nhập dạng 24 giờ `HH:MM`: `00:00` là đầu ngày, `12:00` là 12 giờ trưa, `17:00` là 5 giờ chiều. Không dùng bộ chọn SA/CH phụ thuộc trình duyệt. Khi bật lịch, cả các nút gửi tin, kết bạn và đổi tên thủ công cũng bị chặn ngoài lịch; điều kiện được kiểm tra lại trong giao dịch chốt hành động trước khi gọi Zalo. Tìm người nhận/xem trước có thể thực hiện trước giờ chạy và chưa gửi tin. Nhật ký mới ghi ngày/giờ lịch đã lưu, tài khoản gửi và nguồn thao tác (theo lịch tự động hoặc xác nhận thủ công). Cấu hình cũ `00:00` được giữ nguyên; muốn chạy buổi trưa cần đổi thành `12:00` và lưu lại.

Tích **Không chạy ngày Chủ nhật** để bỏ qua Chủ nhật theo giờ Việt Nam, áp dụng cho lịch ngày/tuần/tháng, data chạy tiếp và các hành động thủ công khi lịch đang bật. Chủ nhật không tạo lượt mới hoặc xử lý bản chờ; giữ data cho ngày chạy hợp lệ tiếp theo. Lịch hằng ngày tiếp tục vào Thứ 2; lịch tuần/tháng tiếp tục theo ngày đã chọn hoặc chế độ chạy tiếp đang bật. Lịch tuần chỉ chọn Chủ nhật sẽ được yêu cầu chọn thêm ngày Thứ 2–Thứ 7. Tùy chọn được lưu, giữ khi nhân bản và mặc định tắt cho cấu hình cũ; biểu mẫu cũ không có trường mới không tự xóa lựa chọn đã lưu.

- Hằng ngày, các thứ trong tuần hoặc ngày 1–31 trong tháng, từ ngày bắt đầu. Tháng thiếu ngày được chọn dùng ngày cuối tháng.
- Giờ dừng phải sau giờ chạy trong cùng ngày. Không bật giờ dừng thì dừng nhận lượt mới lúc 23:59. Lượt đã bắt đầu có thể hoàn tất sau giờ dừng.
- **Tiếp tục data hôm sau** cho phép xử lý phần còn lại vào ngày kế tiếp, kể cả khi ngày đó không thuộc lịch tuần/tháng. Bỏ chọn thì chờ đúng ngày lịch kế tiếp. Hết data không gửi lại; data mới của nguồn nhóm chỉ được nhận trong một lần lịch đến hạn.
- Chỉ dùng khách còn đồng ý nhận tin, thuộc chiến dịch và không bị loại trừ. Bản xem trước thủ công không được bộ chạy tự xác nhận. Mỗi người chỉ có một bản gửi trong chiến dịch; mô phỏng không ảnh hưởng lịch gửi thật.
- Lịch lưu bản xem trước có nội dung/biến thể/định dạng/media rồi chốt từng hành động trước khi gọi Zalo. Dừng chiến dịch, tắt/đổi lịch và hết giờ được kiểm tra lại ngay trước mỗi lượt. Áp dụng giới hạn ngày, khung phút và khoảng nghỉ; khi một hành động hết hạn mức có thể tiếp tục hành động khác theo lựa chọn tại mục Giới hạn hành động.
- Không gửi lại hành động lỗi/chưa xác định. Mất đăng nhập, lỗi tìm người nhận/cá nhân hóa, kết quả chưa xác định hoặc tiến trình cũ gián đoạn sẽ hiện **Cần kiểm tra**, ghi lịch sử và dừng lịch. Sửa nguyên nhân rồi lưu lại lịch để tiếp tục các lượt chưa gửi. Hủy bản xem trước tự động sẽ tắt lịch đó.

Bộ chạy riêng: `python -m flask --app app run-scheduler` (Linux), hoặc `--once` để kiểm tra một chu kỳ. Khóa tệp theo database chỉ cho một tiến trình chạy lịch; ràng buộc SQLite và claim bảo vệ cả khi gửi thủ công đồng thời. `deployment/update.sh` dừng bộ lịch cùng web trước khi sao lưu, nâng cấp schema qua web rồi cài/bật dịch vụ `zaloflow-scheduler`. SIGTERM cho lượt đang xử lý hoàn tất trước khi dừng (tối đa 50 giây). Xem `systemctl status zaloflow-scheduler` và `journalctl -u zaloflow-scheduler` khi cần kiểm tra. Khởi động lại không gửi lại lượt đã chốt.

Khi tra cứu không tìm được người nhận Zalo (gồm mã 216, thông báo không tìm thấy và lỗi tra cứu riêng số đó), chiến dịch ghi lý do bỏ qua, hoàn thành xử lý số đó rồi nghỉ đúng khoảng cài đặt trước khi tìm số tiếp theo. Ví dụ nghỉ 120 giây thì không tra cứu số kế tiếp trước khi hết 120 giây; thời điểm tiếp tục được lưu qua khởi động lại. Không thử lại số đã bỏ qua trong cùng chiến dịch; không tạo Zalo ID giả, không tính thành công, không tiêu hạn mức gửi hoặc lượt biến thể. Báo cáo, CSV và tiến trình hiển thị riêng lý do/số lượng bỏ qua. Lỗi mạng/phản hồi không hợp lệ tự đợi tối thiểu 60 giây, giới hạn tra cứu đợi tối thiểu 15 phút rồi thử lại; lỗi đăng nhập báo rõ cần quét QR. Mã lỗi và nhóm lỗi được lọc trước khi hiện, không ghi cookie/token hay nội dung lỗi gốc. Các lịch đang bật bị dừng bởi hai dạng thông báo tra cứu chung của phiên bản trước tự tiếp tục sau cập nhật, vẫn giữ tạm dừng/ngày/giờ đã cài và không gửi lại lượt cũ. Gửi thủ công chọn khách còn lại, vẫn cần xác nhận người nhận/nội dung trước khi gửi.

Phần **Chi tiết** ngay dưới danh sách chiến dịch có 6 tab: Thông tin, Tài khoản, Data ban đầu, Kết quả chạy, Xem trước nội dung và Lịch sử chạy. Chọn dòng chiến dịch để xem dữ liệu riêng; bảng dài có phân trang, kết quả và lịch sử tự tải lại mỗi 15 giây khi đang xem. Thời gian lịch sử có giây, theo UTC+7. Tab chỉ đọc, không gọi gửi/tra cứu Zalo; tab Tài khoản đọc trạng thái phiên đã lưu. Data danh sách riêng hiển thị các thành viên đã lưu (kể cả hồ sơ đã xóa để tra cứu lịch sử); nhóm động được ghi rõ là danh sách hiện tại, không giả lập bản chụp lúc tạo.

Tab **Xem trước nội dung** hiển thị mỗi biến thể trong một khung hội thoại Zalo, đặt cạnh nhau trên màn hình rộng và xếp dọc trên điện thoại. Dùng tên tài khoản gửi đã chọn, lặp lại tệp chung cho từng biến thể và giữ định dạng chữ. Ảnh kèm chữ định dạng được minh họa thành ảnh rồi tin chữ riêng, phù hợp luồng gửi; ảnh kèm chữ thường dùng chú thích chung. Video/PDF hiện sau tin chữ. Đây là bản minh họa nội dung đã lưu, không giả lập trạng thái người nhận đang online và không gửi tin khi mở tab.

## Giới hạn hành động

Mục **7. Giới hạn hành động** trong Thêm/Sửa/Nhân bản chiến dịch có khoảng nghỉ giữa hai hành động, thẻ Nhắn tin và Kết bạn, số lượt đã chạy/còn lại và thanh tiến độ. **Đổi số phút/giờ** mở số phút của từng khung, từ 1 đến 1.440 phút. Có thể cập nhật sau khi đã có lần gửi qua **Hành động → Cập nhật giới hạn gửi**. Giới hạn đổi tên gợi nhớ được giữ trong phần mở rộng.

Biểu mẫu chiến dịch mới mặc định nghỉ 120 giây, 100 tin/ngày, 25 lời mời/ngày và 5 lượt mỗi loại trong 65 phút. 0 là không giới hạn. Giới hạn ngày mới mặc định đến 24:00 giờ Việt Nam; có lựa chọn 24 giờ gần nhất. Chiến dịch cũ giữ hạn mức, cách tính 24 giờ và khoảng nghỉ đã lưu. Nhân bản sao chép cấu hình nhưng bắt đầu số lượt đã dùng bằng 0.

Hạn mức tính theo chiến dịch, cộng chung tài khoản gửi, áp dụng cho cả gửi thủ công và bộ chạy lịch. Nhắn tin tính mọi tin đến SĐT trong chiến dịch. Tin kèm media tính một lượt. Lượt đã chốt trước khi gọi Zalo được tính cả khi lỗi, đang xử lý hoặc chưa xác định; xem trước/mô phỏng không tính. Sửa hạn mức không xóa lịch sử; các cửa sổ thời gian tự hết hạn theo đồng hồ máy chủ.

Bật **Chiến dịch sẽ tiếp tục chạy khi 1 trong các hành động đạt giới hạn**: bộ chạy bỏ qua hành động đang hết hạn mức, tiếp tục các hành động còn hạn mức ở những khách tiếp theo. Hành động chờ vẫn giữ nguyên nội dung đã chốt và được xử lý khi hạn mức còn lại. Bỏ chọn: toàn chiến dịch chờ khi một hành động đã chọn hết hạn mức. Khoảng nghỉ luôn áp dụng giữa các hành động của chiến dịch.

Các kiểm tra hạn mức và ghi lượt thực hiện trong cùng khóa ghi SQLite, chống vượt mức khi mở nhiều tab hoặc gửi thủ công cùng lúc với bộ lịch. Giao diện tải số lượt hiện tại qua `/campaigns/<id>/limits/usage` (chỉ chủ chiến dịch, không thay đổi dữ liệu), tự cập nhật sau khi đổi cách tính ngày/khung phút và định kỳ khi đang mở. Biểu mẫu POST vẫn yêu cầu CSRF.

## Kiểm tra trùng lặp tin nhắn

Mục **8. Kiểm tra trùng lặp** có trong Thêm/Sửa/Nhân bản chiến dịch. Biểu mẫu tạo mới mặc định bật, 10 ngày, kiểm tra trên tài khoản gửi đang chọn. **Kiểm tra trên toàn bộ tài khoản** mở rộng sang mọi tài khoản thuộc cùng người dùng; không đọc lịch sử người dùng khác. Khoảng kiểm tra từ 1 đến 3.650 ngày, tính lùi từ thời điểm kiểm tra. Chiến dịch cũ mặc định tắt; nhân bản giữ lựa chọn của chiến dịch gốc. Có thể sửa sau khi có bản xem trước tại **Hành động → Kiểm tra trùng lặp**.

Kiểm tra lịch sử nhắn tin trong mọi chiến dịch của người dùng, kể cả đã xóa, theo số điện thoại hoặc Zalo ID. Dùng thời điểm chốt gửi thực tế trong `campaign_attempts`; dữ liệu cũ thiếu thời điểm này dùng thời gian bản ghi đã có. Ghi lại số điện thoại trong bản xem trước để việc sửa hồ sơ không thay đổi danh tính trong lịch sử. Chỉ tính tin Zalo đã tiếp nhận, đang gửi hoặc chưa xác định kết quả; tin gửi lỗi, xem trước, mô phỏng, lời mời kết bạn và đổi tên không được tính là tin nhắn trước đó.

Gửi thủ công hiển thị lý do và khóa nút gửi khi phát hiện trùng; máy chủ kiểm tra lại trong khóa ghi SQLite ngay trước khi tạo lượt gửi. Hai tab/chiến dịch chốt đồng thời không thể vượt kiểm tra; lượt đang gửi ở chiến dịch kia cũng được tính. Bị chặn không tăng hạn mức hoặc ghi thêm lượt gọi Zalo.

Bộ chạy lịch bỏ qua riêng tin nhắn trùng, ghi lý do trong lịch sử và tiếp tục các hành động kết bạn/đổi tên đã chọn. Tin đã chuẩn bị từ trước vẫn được kiểm tra lại khi chốt gửi. Người trùng số đã biết và chỉ có hành động nhắn tin được bỏ qua trước bước tìm Zalo. Bỏ qua không làm tăng lượt biến thể mới. Lượt đã bỏ qua không tự được gửi lại khi tắt kiểm tra hoặc hết số ngày; quy tắc mỗi người chỉ có một bản gửi trong chiến dịch vẫn giữ nguyên. Tạo chiến dịch mới khi cần một đợt liên hệ tiếp theo.

### Quét data Zalo và lưu kết quả

Trong **Nhóm data → Quét data** hoặc **Thêm data vào nhóm → Thêm từ dữ liệu quét**, chọn tài khoản Zalo và nguồn: bạn bè, group đã tham gia, thành viên group, hoặc khách đã gửi tin thành công trong ZaloFlow. Nguồn cuối lấy từ nhật ký của ứng dụng; không đọc toàn bộ lịch sử trò chuyện Zalo. Quét từ Zalo yêu cầu tài khoản còn đăng nhập và chỉ đọc dữ liệu được quyền xem; không tự tham gia group, gửi tin hay kết bạn.

Mỗi lượt đọc tối đa 100 dòng; bạn bè/group dùng **Tải tiếp**, còn quét thành viên tự đọc tiếp các trang khi cửa sổ đang mở, tối đa 10.000 dòng mỗi kết quả. Nếu danh sách thành viên từ `getGroupInfo` bị rút gọn, bộ kết nối thử `getGroupLinkDetail` và `getGroupLinkInfo(memberPage)` qua link đang bật của đúng nhóm đã tham gia; không tự bật link, tham gia nhóm hay đổi quyền riêng tư. Con trỏ trang được lưu để đọc tiếp sau gián đoạn, UID trùng được gộp. Giao diện ghi rõ số hồ sơ Zalo đã trả về và số thành viên khai báo; danh sách chưa đầy đủ không được báo quét đủ. Kết quả được lưu trong SQLite, có tìm kiếm, lọc SĐT/vai trò, chọn nhiều trang và xuất Excel. Nếu Zalo giới hạn danh sách thành viên hoặc quyền xem, giao diện thông báo kết quả chưa đầy đủ. SĐT bị ẩn/không hợp lệ để trống; không suy ra SĐT từ UID. **Kiểm tra SĐT có Zalo** chỉ tra cứu các số đã có và đối chiếu UID, không tìm số ẩn.

**Thêm vào nhóm** chỉ thêm các SĐT hợp lệ đã chọn; UID không có SĐT vẫn nằm trong kết quả quét để xuất Excel. Không chuyển danh sách group thành khách hàng theo SĐT. Hồ sơ đã có giữ thông tin và đồng ý nhận tin; hồ sơ mới mặc định chưa đánh dấu đồng ý trừ khi người dùng tích ô xác nhận. Quét, xuất Excel và tạo bản xem trước không gửi tin thật.

Nếu quét thiếu hoặc trả về 0 hồ sơ, vai trò thành viên và cài đặt ẩn danh sách chưa đủ để kết luận nguyên nhân. Bấm **Tải chẩn đoán** trong kết quả quét thành viên để tải JSON gồm số lượng ID từ từng phần phản hồi, trạng thái lấy link/đọc trang và mã lỗi số nếu có. Báo cáo không chứa tên nhóm, UID, SĐT, link mời hay thông tin đăng nhập. Kết quả cũ cần **Tải data** để tạo lượt quét mới có chẩn đoán. Link trả về rỗng hoặc bước đọc link lỗi không làm mất những hồ sơ lấy được từ thông tin nhóm; ứng dụng giữ phần đã đọc và báo chưa đầy đủ.

Danh sách qua link được gộp theo UID với danh sách từ thông tin nhóm, kể cả khi link chỉ trả về một người và báo không còn trang. ID chỉ có ở thông tin nhóm được tải hồ sơ theo từng phần tối đa 100 người; nếu tải hồ sơ lỗi vẫn giữ UID đã nhận. Gộp dữ liệu không đồng nghĩa đã quét đủ số thành viên khai báo. Với cộng đồng (`group_type=2`), nếu cả hai nguồn đều trả về một phần và không có trang tiếp theo, ứng dụng báo rõ giới hạn của nguồn đang dùng; chưa có xác nhận lấy được đầy đủ thành viên ẩn như AkaBiz.

Khi danh sách ban đầu chưa đầy đủ, phiên bản mới thử thêm nguồn **phân trang theo ID nhóm** (`getGroupInfoV2`, tham khảo mã công khai `@softtynet/zca-js` 2.3.7) trước nguồn link. Bộ đọc dùng nguyên phiên và cơ chế mã hóa/gửi yêu cầu của `zca-js` 2.2.0 đang cài; không thay thư viện đăng nhập/gửi tin. Giao diện ghi nguồn đang dùng; chẩn đoán thêm `paged_status`, `paged_page`, `paged_valid_count`, `paged_more` và mã lỗi số. Nguồn mới đã được kiểm thử ngoại tuyến, chưa xác minh trên nhóm Zalo thật. Xem [ghi nhận nghiên cứu](docs/group-member-pagination-research.md) và [ghi nhận giấy phép](connector/THIRD_PARTY_NOTICES.md).

### Chiến dịch gửi tin vào group Zalo

Trong **Thêm chiến dịch → Hành động**, chọn **Zalo – Gửi tin nhắn đến group**. Chọn tài khoản gửi, tải group tài khoản đã tham gia hoặc chọn từ kết quả quét group đã lưu của đúng tài khoản; thêm các group vào danh sách riêng. UID group được giữ riêng với SĐT/UID người dùng. Nội dung, biến thể, định dạng và một tệp đính kèm dùng chung được hỗ trợ; `{{name}}` chèn tên group.

Khi lịch tắt, tạo bản xem trước rồi xác nhận từng group hoặc lô chia sẻ. Khi bật lịch, bộ `zaloflow-scheduler` dùng cùng khung giờ Việt Nam, nghỉ giữa hai lượt gửi/lô chia sẻ, hạn mức ngày/khung giờ và tùy chọn không chạy Chủ nhật. Hạn mức tính cả lượt đã bắt đầu, lỗi hoặc chưa xác định. Lượt gửi được chốt trước khi gọi Zalo, một group chỉ được xử lý một lần trong chiến dịch; lượt lỗi/chưa xác định được ghi rõ và bỏ qua để chạy group tiếp theo, không tự thử lại. Claim bị gián đoạn được giữ tối thiểu 90 giây trước khi đánh dấu chưa xác định, nghỉ rồi tiếp tục. Cần kiểm tra hội thoại khi chưa xác định kết quả.

SDK gửi bằng `ThreadType.Group` và kiểm tra lại tài khoản còn tham gia group trước khi gửi. Không dùng UID group để nhắn riêng cho thành viên. Giữ lịch sử, tiến độ, pause/resume và bản xem trước sau khởi động lại; xóa tài khoản gửi tạm ngưng chiến dịch liên quan. Bấm **Sửa chiến dịch** để cập nhật nội dung/danh sách cho data chưa bắt đầu; các group đã xử lý giữ nguyên kết quả và không chạy lại.


Biểu mẫu gửi group gồm **7 bước** với thanh điều hướng, thu gọn từng phần và thanh nút lưu cố định. **Lưu nháp** cho phép để trống tài khoản, nội dung hoặc danh sách; bản nháp không gửi và không chạy lịch cho tới khi hoàn tất rồi bấm **Lưu chiến dịch**.

- **Gửi dạng chia sẻ** dùng `forwardMessage` của SDK hiện có, tối đa 50 group trong một lần gọi. Các group trong lô nhận cùng nội dung; không dùng biến cá nhân hóa người nhận. Tin có media hoặc định dạng thực tế được gửi riêng từng group. Số group mỗi lô giảm theo hạn mức còn lại; hạn mức tính từng group và khoảng nghỉ áp dụng một lần sau lô. Hạn mức mặc định có thể khiến lô nhỏ hơn 50 group.
- Gửi thủ công dùng **Xem trước lô chia sẻ**, hiển thị nội dung và đúng danh sách tối đa 50 group cần xác nhận. Group được thêm vào nguồn sau thời điểm xem trước không được đưa vào lô đã xác nhận. Group bị xóa khỏi nguồn trước lúc gửi được bỏ qua. Bấm xác nhận lại không gửi trùng.
- **Kiêm gắn tag ZaloFlow** lưu tối đa 10 tag nội bộ sau phản hồi gửi thành công. Tag hiển thị tại **Nhóm data → Nhóm data Group Zalo**, tách theo tài khoản; không sửa tag của AkaBiz hoặc Zalo.
- **Thêm trực tiếp** giữ danh sách riêng, có chọn group đang tham gia, chọn kết quả quét hoặc **Thêm bằng nhóm**. **Chọn nhóm data để chạy** lấy nguồn từ bộ sưu tập group của đúng tài khoản và cập nhật trước mỗi lượt xử lý. Có thể tạo/thêm/xóa group trong bộ sưu tập qua **Lưu vào nhóm data** hoặc trang quản lý riêng; không dùng SĐT khách hàng làm UID group. Gửi thủ công có nút **Làm mới từ nhóm data**. Khi xóa bộ sưu tập, chiến dịch giữ danh sách hiện tại dưới dạng danh sách riêng, cùng lịch sử đã xử lý.

SDK không gắn kết quả chia sẻ từng phần với UID từng group. Chỉ ghi thành công toàn bộ các group đã gửi trong lô khi đủ mã tin hợp lệ cho tất cả và không có lỗi. Phản hồi từng phần hoặc mất kết nối được ghi **chưa xác định**, không tự thử lại và không gắn tag; kiểm tra hội thoại trước khi chủ động tạo chiến dịch khác. Các kiểm thử dùng phản hồi SDK mô phỏng và kiểm tra cách SDK tạo yêu cầu, không gửi tin Zalo thật.

Thanh định dạng nội dung có nút **A ▾ → Màu chữ**: bôi đen đoạn cần đổi rồi chọn **Đỏ, Cam, Vàng, Xanh lá** hoặc **Mặc định**. Đây là bốn màu `TextStyle` được thư viện Zalo hiện tại hỗ trợ; không có bộ chọn màu tùy ý. Màu được giữ trong mẫu nội dung, bản xem trước và lượt gửi đã chốt, kể cả sau khi cá nhân hóa tên hoặc dùng emoji. Chọn Mặc định chỉ bỏ màu, còn **Xóa định dạng** bỏ cả màu và nhấn mạnh. Tin group có màu dùng gửi riêng từng group để giữ định dạng, kể cả khi bật tùy chọn chia sẻ theo lô. Đã kiểm thử bằng phản hồi SDK mô phỏng; chưa xác minh hiển thị trên Zalo thật.


**Sửa chiến dịch đang chạy:** áp dụng cho cả chiến dịch SĐT và group, kể cả đã mô phỏng hoặc có lượt gửi. Giữ nguyên kết quả, mã tin, tài khoản và nội dung của từng hành động đã có lượt thực hiện. Hành động đã thành công, lỗi hoặc chưa xác định không tự chạy lại. Các bước chưa thực hiện của cùng một data vẫn tiếp tục theo nội dung, media và tài khoản mới đã sửa; chỉ bỏ bước nếu người dùng tắt bước đó hoặc người nhận không còn đủ điều kiện. Lượt đang gửi vẫn hoàn tất với bản nội dung đã chốt trước đó.

Bản xem trước chưa có lượt gửi được chuyển vào **Lịch sử → Bản xem trước đã thay thế** và phải tạo lại theo thông tin mới; trang xác nhận cũ không gửi được. ID bản gửi không dùng lại. Lưu sửa không tự gửi tin; chiến dịch đang bật lịch tiếp tục phần còn lại theo lịch và giới hạn mới, còn chiến dịch tạm ngưng vẫn giữ tạm ngưng. Hạn mức đã dùng, khoảng nghỉ và nhật ký mô phỏng không bị đặt lại.


Bước chờ trên data đã chạy một phần có bản nội dung riêng và mã xác nhận riêng. Tab xác nhận cũ không gửi được nội dung mới. Đổi tài khoản cho bước chờ cần tra cứu lại người nhận bằng tài khoản mới: bộ lịch thực hiện tra cứu trước lượt gửi; gửi thủ công bấm **Tải người nhận cho bước…** rồi kiểm tra và xác nhận. Báo cáo và CSV ghi tài khoản theo từng bước. Cập nhật/sửa cấu hình không gọi gửi tin, kết bạn hay đổi tên.

Bản cập nhật sửa lỗi `edit_started_recipient` của phiên bản `56516f0`: khi khởi động, ứng dụng đối chiếu đúng nhật ký hủy bước do phiên bản đó tạo, chỉ khôi phục các bước vẫn được chọn, có nội dung cũ và chưa có bất kỳ lượt thực hiện nào. Giữ nguyên bước đã có lượt chạy, bỏ qua hợp lệ, sự đồng ý nhận tin, hạn mức và thời gian nghỉ. Việc khôi phục tự nó không gọi Zalo; bước chờ tiếp tục khi chủ tài khoản cho chạy và đủ điều kiện lịch/hạn mức. Mỗi nhật ký được xử lý một lần. Trường hợp thiếu thông tin cá nhân hóa/tài khoản được ghi cần kiểm tra, không tự tạo dữ liệu hay gửi lại bước cũ.


### Ứng dụng Windows: mở tool mới chạy

Đăng ký mới phải được quản trị viên duyệt trước khi đăng nhập. Chủ VPS cấp quyền lần đầu bằng `flask --app app:create_app grant-admin --username TEN_TAI_KHOAN`, rồi vào **Quản lý tài khoản** để duyệt/từ chối/khóa. Tài khoản cũ giữ quyền sử dụng, không tự có quyền quản trị. Nút **Đăng xuất** hiện ở góc phải mọi trang. Xem [hướng dẫn cập nhật và duyệt tài khoản](deployment/ACCOUNT-APPROVAL.md).

Thứ tự phát hành: cập nhật và kiểm thử trên VPS thật trước; khi xác nhận ổn mới đóng gói Windows từ đúng phiên bản đã thử. Workflow Windows chỉ chạy thủ công với xác nhận `vps_tested`, không tự chạy khi push. Xem [các bước kiểm thử quên mật khẩu trên VPS](deployment/ACCOUNT-RECOVERY.md#cập-nhật).

Đăng nhập có **Quên mật khẩu?**; bản web gửi mã 5 số, hiệu lực 10 phút đến email đã xác minh. Chủ VPS cấu hình Gmail SMTP bằng lệnh `configure-smtp`, không đưa mật khẩu Gmail vào Git/bộ cài. Xem [cấu hình Gmail và kiểm thử VPS](deployment/EMAIL-RECOVERY.md). Mã khôi phục dự phòng và mã hỗ trợ 15 phút vẫn dùng khi mất quyền truy cập email; xem [hướng dẫn dự phòng](deployment/ACCOUNT-RECOVERY.md). Đặt lại giữ dữ liệu/tiến độ/key, vô hiệu hóa phiên/mã cũ, không tự duyệt tài khoản.

Bản Windows có cửa sổ riêng, bộ web nội bộ và bộ lịch hoạt động theo vòng đời cửa sổ. Chỉ bắt đầu lịch khi cửa sổ hiện ra; bấm X chặn lượt mới, chờ lượt đang xử lý kết thúc rồi dừng. Dữ liệu/tiến độ lưu riêng trong `%LOCALAPPDATA%\ZaloFlow\instance`, mở lại tiếp tục bước chờ, không đặt lại lịch sử/hạn mức. Không cài dịch vụ hay tác vụ tự khởi động Windows. Thu nhỏ vẫn chạy; đóng tool/máy ngủ/tắt thì không chạy lịch.

Tải gói **ZaloFlow-Setup-Windows-x64** từ artifact của [Build Windows desktop](https://github.com/Viettax2026/du-an-codex/actions/workflows/windows-desktop.yml). Lấy `ZaloFlow-Setup-x64.exe` trong ZIP rồi chạy để cài; bộ cài tạo icon Desktop/Start, cài tệp hỗ trợ trong thư mục ẩn và giữ dữ liệu khi nâng cấp/gỡ. Chỉ cần phát bộ cài EXE cho khách. Ẩn file không ngăn sao chép; quyền sử dụng được kiểm soát bằng key. Bộ kết nối Node/SDK được đóng gói cùng ứng dụng. Cần Windows 10/11 x64, Microsoft Edge WebView2 Runtime và Internet. [Hướng dẫn sử dụng, dựng lại và chuyển dữ liệu VPS](desktop/README.md). Bản Windows không tự sao chép hoặc đồng bộ dữ liệu VPS; nếu chuyển cùng chiến dịch sang PC, dừng bộ lịch VPS trước để tránh hai nơi cùng gửi.

Bản mới có kích hoạt bằng key qua máy chủ: một key/một máy, đặt hạn dùng, gia hạn, thu hồi và hủy kích hoạt để chuyển máy. Trang quản trị key chạy riêng tại `/licenses/admin`, không dùng quyền đăng nhập của khách hàng ZaloFlow. Chỉ phát gói Windows khi đã có cấu hình công khai của máy chủ; khóa ký riêng ở VPS của chủ phần mềm. Xem [cài đặt và quản lý bản quyền](deployment/LICENSES.md).

Hai bản Windows và web vận hành tách biệt: bản web dùng database/tài khoản/phiên đăng nhập trên VPS và không yêu cầu key Windows; bản Windows dùng database/tài khoản/phiên đăng nhập riêng trên PC. Đóng Windows không dừng chiến dịch web. Dịch vụ `/licenses/` là máy chủ xác thực key riêng, chỉ nhận thông tin kích hoạt; không đồng bộ khách hàng, chiến dịch hoặc tiến độ giữa hai bản.

### Gói web cho domain và VPS mới

[Build portable web package](https://github.com/Viettax2026/du-an-codex/actions/workflows/web-package.yml) tạo artifact **zaloflow-web**, tải về thành ZIP chỉ chứa mã web và bộ cài Ubuntu 24.04. Sau khi trỏ DNS và giải nén trên VPS mới, chạy `bash web_deploy/install-web.sh --domain crm.example.com --email owner@example.com`. Có thể đặt `--name` và `--port` riêng cho từng bản cài. Script dựng Nginx/HTTPS, Python và Node 22 riêng; bộ lịch chỉ bật khi chọn `--start-scheduler` hoặc bật dịch vụ sau. ZIP không chứa Windows, kho key hoặc dữ liệu thực. Xem [hướng dẫn cài, sao lưu và chuyển dữ liệu](web_deploy/README.md).
