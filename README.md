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

**Kênh Zalo cá nhân có gửi từng tin và lời mời kết bạn sau xác nhận.** Kênh OA/OAuth, webhook, lịch gửi, hàng đợi và ZNS chưa triển khai; số điện thoại không thay cho OA user ID.

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

Bộ kết nối khôi phục phiên AES-GCM trong tiến trình Node, không trả cookie ra HTTP. Tìm người nhận/gửi có giới hạn chờ 40 giây, Python dừng tiến trình sau 45 giây. Không có chạy hàng loạt, lập lịch, listener hoặc quét dữ liệu. Các kiểm thử dùng dữ liệu giả lập API; môi trường Codex chặn Zalo nên phải xác minh gửi thật và tin đến trên VPS với người nhận thử đã đồng ý.

Cập nhật VPS đã có bộ kết nối: git pull --ff-only origin main rồi systemctl restart zaloflow. Cơ sở dữ liệu tự thêm bảng, không xóa dữ liệu hoặc phiên QR đã có.

## Tạo và sửa chiến dịch theo số điện thoại

Form có ba phần: cài đặt chung (hành động, tài khoản, tên), danh sách SĐT và nội dung có xem trước {{name}}. Có thể nhập tối đa 500 số Việt Nam, mỗi dòng một số; +84 được chuẩn hóa về 0, loại số trùng. Phải xác nhận đồng ý nhận tin trước khi lưu danh sách. Khách hàng hiện có được giữ nguyên tên/nhóm; người mới lưu tên tạm theo số điện thoại.

Danh sách riêng lưu trong campaign_contacts và chỉ áp dụng cho chiến dịch đó; khi để trống thì dùng nhóm khách hàng như trước. Tài khoản gửi đã chọn được lưu và chọn sẵn ở màn hình gửi thật. Lưu/sửa không gọi Zalo hoặc tự gửi. Chỉ sửa được bản nháp chưa mô phỏng và chưa có bản xem trước/lần gửi thật để bảo toàn nhật ký. Cơ sở dữ liệu cũ tự thêm cột account_id và bảng liên kết, không xóa dữ liệu.

Đã có lựa chọn nhắn tin và kết bạn riêng; Media được hỗ trợ qua menu Hành động → Cập nhật nội dung + media; lịch gửi chưa triển khai. Các phần đó trong ảnh tham chiếu chưa được triển khai.


## Soạn lời mời kết bạn và tin nhắn

Hành động “Nhắn tin, kết bạn đến SĐT” có hai ô lựa chọn độc lập. Có thể chỉ nhắn tin, chỉ kết bạn hoặc cả hai. Lời mời tối đa 150 ký tự, hỗ trợ {{name}} và xem trước. Giới hạn kiểm tra cả sau khi chèn tên thật.

Tìm người nhận và tạo bản xem trước vẫn không gửi hành động nào. Người dùng xác nhận riêng “Gửi lời mời kết bạn” và “Gửi tin thật”; không tự gửi tin sau lời mời hoặc chờ chấp nhận tự động. Lời mời được lưu với friend_state riêng; tiếp nhận lời mời không có nghĩa đã chấp nhận. Double click, kết quả chưa xác định và khởi động lại không tự gửi lại lời mời. Bản xem trước có bất kỳ hành động đã xử lý không thể xóa để gửi lại.

zca-js.sendFriendRequest có thể bị Zalo từ chối nếu đã là bạn bè hoặc bị chặn. SDK lưu ý yêu cầu kết bạn có thể được xử lý như chấp nhận lời mời đã đến; ứng dụng không tự suy diễn trạng thái bạn bè. Kiểm thử API giả lập không xác minh gửi lời mời thật trên VPS. Đổi tên gợi nhớ, media và giới hạn hành động đã được bổ sung ở các bản sau (xem bên dưới). Gắn tag Zalo và lịch chạy tự động chưa triển khai.

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

Đăng ký bằng tên tài khoản từ 3–64 ký tự: chữ không dấu, số, dấu chấm, gạch dưới và gạch ngang; không phân biệt chữ hoa/thường. Không yêu cầu email. Cơ sở dữ liệu cũ tự chuyển định danh email sang tài khoản và giữ nguyên mật khẩu, dữ liệu: người dùng cũ vẫn nhập nguyên email cũ vào ô Tài khoản.

Tài khoản cũ `lienhe.viettaxco@gmail.com` được đổi thành `admin` khi khởi động phiên bản mới, giữ nguyên mật khẩu và dữ liệu. Nếu tên `admin` đã tồn tại, ứng dụng báo lỗi và không ghi đè tài khoản. Các tài khoản cũ khác giữ nguyên định danh.

## Đặt lại mật khẩu admin trên VPS

Chạy `sudo -u zaloflow /opt/zaloflow/.venv/bin/flask --app app:create_app reset-admin` trong `/opt/zaloflow`. Nhập mật khẩu mới hai lần khi được hỏi (không hiển thị khi gõ), từ 10–256 ký tự. Lệnh tạo admin nếu chưa có, hoặc đổi mật khẩu trên chính tài khoản admin hiện có, giữ nguyên dữ liệu. Không truyền mật khẩu trong dòng lệnh.

## Menu Hành động chiến dịch

Đã có đủ 12 mục theo ảnh tham chiếu:

- **Dừng / tiếp tục chiến dịch**: khóa tạo bản xem trước, mô phỏng và gửi/kết bạn/đổi tên tiếp theo. Không thu hồi hành động đã chuyển đến Zalo và không tự chạy lại khi tiếp tục.
- **Sửa**: sửa cấu hình chung của bản nháp chưa có bản xem trước/lần gửi. Chiến dịch đã xử lý dùng các mục cập nhật riêng để giữ lịch sử.
- **Nhân bản**: tạo bản nháp mới với cấu hình, tài khoản, media, giới hạn và danh sách riêng; không chép lần gửi/nhật ký. Có màn hình kiểm tra tên trước khi tạo; lưu không gọi Zalo.
- **Lấy ID chiến dịch**: sao chép ID, có hiển thị ID nếu clipboard bị chặn.
- **Cập nhật giới hạn gửi**: hạn mức riêng cho nhắn tin, kết bạn và đổi tên trong 24 giờ gần nhất; khoảng cách tối thiểu giữa các hành động của chiến dịch. 0 là không giới hạn. Một lần xử lý nội dung + media cho một người là một hành động; tính cả thất bại/đang xử lý/chưa xác định, không tính bản xem trước hoặc mô phỏng. Khóa SQLite kiểm tra và ghi nhận trước gọi mạng, chống vượt hạn mức khi mở nhiều tab. Lần gửi cũ được đưa vào bộ đếm theo thời gian tạo bản ghi, do bản cũ chưa lưu riêng thời gian bắt đầu gửi.
- **Cập nhật nội dung + media**: hỗ trợ một tệp JPG/JPEG, PNG, WEBP, PDF hoặc MP4 tối đa 10 MB. Kiểm tra định dạng và ảnh tối đa 25 triệu điểm ảnh. Media lưu riêng trong instance/media, chỉ chủ tài khoản truy cập; chỉ gửi sau xác nhận. Bản xem trước cũ giữ nguyên nội dung, lời mời và media, kể cả khi chiến dịch đổi/gỡ tệp. PDF/MP4 được SDK gửi dưới dạng tệp đính kèm; chữ và tệp có thể là hai tin trong Zalo. Chỉ báo tiếp nhận khi có mã xác nhận của tệp; nếu chỉ chữ thành công thì kết quả chưa xác định, không tự gửi lại. Chưa hỗ trợ album nhiều tệp hoặc tải media từ URL.
- **Thêm data**: bổ sung số điện thoại hoặc CSV UTF-8 có phone, tùy chọn name/email/info1…info5; tổng danh sách tối đa 500 số, CSV tối đa 2 MB. Chuẩn hóa +84, loại số trùng, giữ thông tin khách hàng đã có và yêu cầu xác nhận đồng ý. Nhóm hiện tại được chốt thành danh sách riêng trước khi bổ sung; không thay đổi lần gửi cũ.
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
