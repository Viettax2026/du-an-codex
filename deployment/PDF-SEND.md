# PDF có trong bản xem trước nhưng người nhận chỉ thấy chữ

Nguyên nhân được tái hiện bằng chính SDK đang ghim `zca-js 2.2.0`: SDK gửi nội dung chữ, tải PDF lên qua HTTP rồi chờ thông báo `file_done` từ WebSocket để lấy URL file và gọi API gửi file. Worker cũ không mở listener, nên phần chữ đã được gửi còn phần PDF chờ đến lúc hết giới hạn 40 giây. Có mã tin chữ không chứng minh file đã được gửi.

Bản sửa mở một listener tạm thời trước khi bắt đầu gửi PDF/MP4, chờ SDK nhận khóa kênh (tối đa 8 giây), rồi mới gọi gửi chữ và file. SDK nhận `file_done` và tiếp tục gửi file. Dừng listener sau thao tác, không bật lấy lịch sử hội thoại hoặc tự nối lại/gửi lại. Nếu kết nối ban đầu thất bại thì chưa gửi chữ/tệp; nếu mất kết nối sau khi gửi đã bắt đầu, giữ kết quả chưa xác định để tránh gửi trùng. Chỉ báo thành công khi SDK xác nhận cả chữ lẫn tệp. Ảnh và tin chỉ có chữ không mở thêm listener.

## Cập nhật và kiểm thử VPS

```bash
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/update.sh
```

Script sao lưu `instance` trước khi cập nhật. Bộ kết nối vẫn dùng `zca-js 2.2.0`, không cần tự nâng SDK hoặc sửa node_modules.

1. Tạo một chiến dịch thử mới, dùng tài khoản/người nhận thử do bạn kiểm soát hoặc đã đồng ý nhận tin. Chọn PDF từ thư viện, lưu, kiểm tra đúng tên file trong bản xem trước.
2. Gửi một lần rồi kiểm tra trên Zalo của người nhận: phải có chữ và tệp PDF; tải/mở được đúng file. Nếu kiểm thử group, chọn group thử đã tham gia và kiểm tra tương tự.
3. Kiểm tra kết quả chạy/lịch sử. Kết quả thành công phải xác nhận việc gửi cả chữ và file; nếu kênh upload không mở được, lịch sử có thông báo cố định về kênh xác nhận tải tệp.
4. Không gửi lại nguyên chiến dịch cũ để kiểm thử. Bản sửa không tự đặt lại hay thực hiện lại các lượt đã gửi/chưa xác định. Các hội thoại chỉ nhận chữ trước đây cần kiểm tra riêng; mã không tự gửi lại chữ hoặc tự gửi bù tài liệu cho khách.
5. Báo kết quả gửi PDF thực tế. Theo quy trình đã chọn, kiểm thử trên VPS thật trước rồi mới dựng bộ cài Windows có bản sửa này. Kiểm thử SDK cục bộ/CI không thay thế việc kiểm tra file thực tế ở Zalo.

## Kiểm thử tự động

`connector/document-sdk.test.mjs` dùng uploader, bộ tuần tự hóa tin nhắn và Listener thật của SDK 2.2.0, chỉ thay HTTP và server WebSocket bằng dữ liệu thử cục bộ. Bài kiểm thử tái hiện worker cũ bị kẹt sau khi gửi chữ, rồi xác minh bản sửa gọi API gửi file với đúng URL, tên, kích thước, checksum và người nhận. Có trường hợp PDF/MP4 cho cá nhân/group và trường hợp chữ được xác nhận nhưng tệp chưa có xác nhận.

`connector/attachment-listener.test.mjs` kiểm tra thứ tự chờ kết nối, thiếu khóa kênh, lỗi/đóng kết nối, đóng ngay sau khi sẵn sàng, mất kết nối sau dispatch và việc dừng listener. Không gửi tin Zalo thật hoặc sử dụng phiên/mật khẩu thực trong các bài kiểm thử này.
